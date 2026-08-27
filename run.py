import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend-api"
FRONTEND_DIR = ROOT / "frontend-flet"
BACKEND_ENV = BACKEND_DIR / ".env"
BACKEND_EXAMPLE_ENV = BACKEND_DIR / ".env.example"
BACKEND_VENV = BACKEND_DIR / ".venv"
ROOT_VENV = ROOT / ".venv"
BACKEND_PYTHON = BACKEND_VENV / "Scripts" / "python.exe"
ROOT_PYTHON = ROOT_VENV / "Scripts" / "python.exe"
FLET_EXE = ROOT_VENV / "Scripts" / "flet.exe"
SQLITE_DB_URL = "sqlite:///./test_entregas.db"

import socket
import subprocess
import sys
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

def wait_for_backend(
    process: subprocess.Popen,
    timeout: float = 30.0,
    healthcheck: Callable[[str], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    check = healthcheck or _healthcheck
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("O backend encerrou antes de ficar saudável.")
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
    stop_process(frontend, "frontend")
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
        cleanup(frontend, backend)

if __name__ == "__main__":
    sys.exit(run())

def get_host_python() -> Path:
    return Path(sys.executable)


def run_command(command: list[str], cwd: Path | None = None) -> None:
    print(f"Running: {' '.join(command)}")
    subprocess.check_call(command, cwd=str(cwd) if cwd else None)


def ensure_venv(path: Path) -> None:
    if path.exists():
        print(f"Virtual environment already exists at {path}")
        return
    print(f"Creating virtual environment at {path}")
    run_command([str(get_host_python()), "-m", "venv", str(path)])


def ensure_pip_packages(python: Path, requirements: Path) -> None:
    if not python.exists():
        raise FileNotFoundError(f"Python interpreter not found in virtual environment: {python}")
    print(f"Upgrading pip in {python.parent.parent}")
    run_command([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    print(f"Installing requirements from {requirements}")
    run_command([str(python), "-m", "pip", "install", "-r", str(requirements)])


def ensure_backend_env() -> None:
    if not BACKEND_ENV.exists():
        if BACKEND_EXAMPLE_ENV.exists():
            shutil.copy(BACKEND_EXAMPLE_ENV, BACKEND_ENV)
            print(f"Created backend .env from {BACKEND_EXAMPLE_ENV}")
        else:
            raise FileNotFoundError(f"Missing {BACKEND_ENV} and {BACKEND_EXAMPLE_ENV}")

    content = BACKEND_ENV.read_text(encoding="utf-8")
    lines = content.splitlines()
    updated = False
    for index, line in enumerate(lines):
        if line.strip().startswith("DATABASE_URL="):
            if line.strip() != f"DATABASE_URL={SQLITE_DB_URL}":
                lines[index] = f"DATABASE_URL={SQLITE_DB_URL}"
                updated = True
            break
    else:
        lines.append(f"DATABASE_URL={SQLITE_DB_URL}")
        updated = True

    if updated:
        BACKEND_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Updated backend DATABASE_URL to SQLite in {BACKEND_ENV}")
    else:
        print("Backend .env already configured for SQLite.")


def load_frontend_map_config() -> None:
    if os.getenv("MAPTILER_API_KEY"):
        print("MAPTILER_API_KEY carregada =", True)
        return
    for line in BACKEND_ENV.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "MAPTILER_API_KEY":
            os.environ["MAPTILER_API_KEY"] = value.strip().strip('"').strip("'")
            print("MAPTILER_API_KEY carregada =", bool(os.environ["MAPTILER_API_KEY"]))
            return
    print("MAPTILER_API_KEY carregada = False")


def load_frontend_runtime_config() -> None:
    for config_path in (FRONTEND_DIR / ".env", BACKEND_ENV):
        if not config_path.exists():
            continue
        for line in config_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"API_BASE_URL", "MAPTILER_API_KEY"}:
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def start_process(command: list[str], cwd: Path, title: str) -> subprocess.Popen:
    print(f"Starting {title}: {' '.join(command)}")
    creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        creationflags=creationflags,
        env=os.environ.copy(),
    )


if __name__ == "__main__":
    try:
        ensure_backend_env()
        load_frontend_runtime_config()
        load_frontend_map_config()

        ensure_venv(BACKEND_VENV)
        ensure_venv(ROOT_VENV)

        ensure_pip_packages(BACKEND_PYTHON, BACKEND_DIR / "requirements.txt")
        ensure_pip_packages(ROOT_PYTHON, FRONTEND_DIR / "requirements.txt")

        backend_cmd = [
            str(BACKEND_PYTHON),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--reload",
            "--reload-dir",
            "app",
        ]
        frontend_cmd = [
            str(FLET_EXE),
            "run",
            str(FRONTEND_DIR / "main.py"),
        ]

        start_process(backend_cmd, BACKEND_DIR, "backend")
        start_process(frontend_cmd, ROOT, "frontend")

        print("Backend and frontend have been started in separate windows.")
        print("If the frontend window does not appear, check the terminal output for errors.")
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {exc.cmd}")
    except Exception as exc:
        print(f"Error: {exc}")
