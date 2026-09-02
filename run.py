import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend-api"
FRONTEND_DIR = ROOT / "frontend-flet"
BACKEND_VENV = BACKEND_DIR / ".venv"
ROOT_VENV = ROOT / ".venv"
BACKEND_PYTHON = BACKEND_VENV / "Scripts" / "python.exe"
FLET_EXE = ROOT_VENV / "Scripts" / "flet.exe"
BACKEND_HOST = "0.0.0.0"
BACKEND_PORT = 8000
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
DESKTOP_API_BASE_URL = "http://127.0.0.1:8000/api"


def is_frozen_runtime() -> bool:
    return bool(getattr(sys, "frozen", False))


def log(message: str) -> None:
    print(f"[Launcher] {message}", flush=True)


def check_port_available(host: str = "127.0.0.1", port: int = BACKEND_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def process_creation_flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def start_process(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        creationflags=process_creation_flags(),
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
    )


def _runtime_search_roots() -> list[Path]:
    roots = [ROOT]
    if is_frozen_runtime():
        if getattr(sys, "_MEIPASS", None):
            roots.append(Path(sys._MEIPASS))
        if getattr(sys, "executable", None):
            roots.append(Path(sys.executable).resolve().parent)
        roots.extend([BACKEND_DIR, FRONTEND_DIR])
    return roots


def _import_from_candidates(module_name: str, candidates: list[str | Path]) -> object:
    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        if path.exists() and path.is_file():
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError(f"Módulo {module_name} não encontrado em: {candidates}")


def load_frontend_entrypoint():
    candidates = [
        ROOT / "frontend-flet" / "main.py",
        ROOT / "main.py",
        FRONTEND_DIR / "main.py",
    ]
    if is_frozen_runtime() and getattr(sys, "_MEIPASS", None):
        meipass_root = Path(sys._MEIPASS)
        candidates.extend([
            meipass_root / "frontend-flet" / "main.py",
            meipass_root / "main.py",
        ])
    module = _import_from_candidates("frozen_frontend_entrypoint", candidates)
    return getattr(module, "main", None) or getattr(module, "app_main", None)


def start_backend_frozen() -> tuple[object, threading.Thread]:
    import uvicorn

    for root in _runtime_search_roots():
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    from app.main import app

    config = uvicorn.Config(app=app, host=BACKEND_HOST, port=BACKEND_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return server, thread


def start_frontend_frozen():
    import flet as ft
    frontend_main = load_frontend_entrypoint()
    if frontend_main is None:
        raise FileNotFoundError("Função principal do frontend Flet não foi encontrada para runtime congelado.")
    ft.app(frontend_main)
    return 0


def wait_for_backend(
    process: subprocess.Popen | object,
    timeout: float = 30.0,
    healthcheck: Callable[[str], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    check = healthcheck or _healthcheck
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if hasattr(process, "poll") and process.poll() is not None:
            raise RuntimeError("O backend encerrou antes de ficar saudável.")
        should_exit = getattr(process, "should_exit", None)
        if isinstance(should_exit, bool) and should_exit:
            raise RuntimeError("O backend foi sinalizado para encerrar antes de ficar saudável.")
        if check(BACKEND_HEALTH_URL):
            return
        sleep(0.2)
    raise TimeoutError("O backend não respondeu ao healthcheck dentro do prazo.")


def _healthcheck(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def stop_process(process: subprocess.Popen | None, name: str) -> None:
    if process is None or process.poll() is not None:
        return
    log(f"Encerrando {name}...")
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def cleanup(frontend: subprocess.Popen | None, backend: subprocess.Popen | None) -> None:
    if frontend is not None and hasattr(frontend, "terminate"):
        stop_process(frontend, "frontend")
    if backend is not None:
        should_exit = getattr(backend, "should_exit", None)
        if isinstance(should_exit, bool) and should_exit:
            return
    stop_process(backend, "backend")


def build_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["API_BASE_URL"] = DESKTOP_API_BASE_URL
    environment["ROTA_DESKTOP_LOCAL"] = "1"
    return environment


def run() -> int:
    backend = None
    frontend = None
    try:
        log("Verificando ambiente...")
        if is_frozen_runtime():
            backend, backend_thread = start_backend_frozen()
            wait_for_backend(backend)
            log("Backend pronto.")
            log("Iniciando Rota Inteligente...")
            return start_frontend_frozen()

        if not BACKEND_PYTHON.is_file():
            raise FileNotFoundError(f"Interpretador do backend não encontrado: {BACKEND_PYTHON}")
        if not FLET_EXE.is_file():
            raise FileNotFoundError(f"Flet não encontrado: {FLET_EXE}")
        if not check_port_available():
            raise RuntimeError("A porta 8000 já está ocupada. Feche o processo que a utiliza e tente novamente.")

        environment = build_environment()
        backend_command = [
            str(BACKEND_PYTHON),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            BACKEND_HOST,
            "--port",
            str(BACKEND_PORT),
        ]
        frontend_command = [str(FLET_EXE), "run", str(FRONTEND_DIR / "main.py")]

        log("Iniciando backend...")
        backend = start_process(backend_command, BACKEND_DIR, environment)
        wait_for_backend(backend)
        log("Backend pronto.")

        log("Iniciando Rota Inteligente...")
        frontend = start_process(frontend_command, ROOT, environment)
        frontend.wait()
        log("Aplicação encerrada.")
        return 0
    except KeyboardInterrupt:
        log("Interrupção recebida.")
        return 130
    except Exception as exc:
        log(f"Erro: {exc}")
        return 1
    finally:
        if backend is not None:
            should_exit = getattr(backend, "should_exit", None)
            if isinstance(should_exit, bool):
                backend.should_exit = True
        cleanup(frontend, backend)


if __name__ == "__main__":
    sys.exit(run())
