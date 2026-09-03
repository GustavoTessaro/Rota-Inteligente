from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend-api"
FRONTEND_DIR = ROOT / "frontend-flet"
BACKEND_VENV = BACKEND_DIR / ".venv"
ROOT_VENV = ROOT / ".venv"
BACKEND_PYTHON = BACKEND_VENV / "Scripts" / "python.exe"
ROOT_PYTHON = ROOT_VENV / "Scripts" / "python.exe"
FLET_EXE = ROOT_VENV / "Scripts" / "flet.exe"
BACKEND_ENV = BACKEND_DIR / ".env"
BACKEND_ENV_EXAMPLE = BACKEND_DIR / ".env.example"

ENV_KEYS_TO_REPORT = {
    "DATABASE_URL": "REQUIRED_NOW",
    "JWT_SECRET": "REQUIRED_NOW",
    "MAPTILER_API_KEY": "REQUIRED_NOW",
    "GOOGLE_MAPS_API_KEY": "REQUIRED_ONLY_FOR_GOOGLE_FEATURES",
    "USE_GOOGLE_ROUTE_OPTIMIZATION": "REQUIRED_ONLY_FOR_GOOGLE_FEATURES",
    "GOOGLE_ROUTE_OPTIMIZATION_PROJECT_ID": "REQUIRED_ONLY_FOR_GOOGLE_FEATURES",
    "GOOGLE_ROUTE_OPTIMIZATION_SERVICE_ACCOUNT_FILE": "REQUIRED_ONLY_FOR_GOOGLE_FEATURES",
}


class BootstrapError(RuntimeError):
    pass


def info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def ok(message: str) -> None:
    print(f"[OK] {message}", flush=True)


def warning(message: str) -> None:
    print(f"[AVISO] {message}", flush=True)


def run_command(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        rendered = " ".join(command[:3])
        raise BootstrapError(f"Comando falhou ({result.returncode}): {rendered}")


def read_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def validate_python(python_executable: Path) -> None:
    version = platform.python_version()
    if sys.version_info[:2] != (3, 14):
        raise BootstrapError(
            f"Python incompatível: {version}. Este projeto requer Python 3.14.x."
        )
    if Path(sys.executable).resolve() != python_executable.resolve():
        raise BootstrapError("O interpretador usado pelo bootstrap não corresponde ao Python informado.")
    ok(f"Python {version}")


def ensure_venv(venv_path: Path, label: str) -> Path:
    python_path = venv_path / "Scripts" / "python.exe"
    if python_path.is_file():
        ok(f"Ambiente {label} já existente")
        return python_path
    info(f"Criando ambiente {label}...")
    run_command([sys.executable, "-m", "venv", str(venv_path)], cwd=ROOT)
    if not python_path.is_file():
        raise BootstrapError(f"Python do ambiente {label} não foi criado.")
    ok(f"Ambiente {label}")
    return python_path


def install_requirements(python_path: Path, requirements_path: Path, label: str) -> None:
    if not requirements_path.is_file():
        raise BootstrapError(f"Manifesto não encontrado: {requirements_path}")
    info(f"Instalando dependências {label}...")
    run_command([str(python_path), "-m", "pip", "install", "-r", str(requirements_path)], cwd=ROOT)
    ok(f"Dependências {label}")


def pip_check(python_path: Path, label: str) -> None:
    info(f"Validando dependências {label}...")
    run_command([str(python_path), "-m", "pip", "check"], cwd=ROOT)
    ok(f"Pip check {label}")


def ensure_backend_env() -> dict[str, str]:
    if not BACKEND_ENV.is_file():
        if not BACKEND_ENV_EXAMPLE.is_file():
            raise BootstrapError("backend-api/.env e backend-api/.env.example não foram encontrados.")
        shutil.copy2(BACKEND_ENV_EXAMPLE, BACKEND_ENV)
        info("backend-api/.env criado a partir de backend-api/.env.example; nenhum valor foi preenchido automaticamente.")
    else:
        ok("Configuração backend-api/.env já existente")
    return read_env_values(BACKEND_ENV)


def report_env(values: dict[str, str]) -> bool:
    pending_critical = False
    for key, category in ENV_KEYS_TO_REPORT.items():
        value = values.get(key, "").strip()
        state = "SET" if value else "EMPTY/MISSING"
        print(f"[CONFIG] {key}={state} ({category})")
        if category == "REQUIRED_NOW" and not value:
            pending_critical = True
    service_account = values.get("GOOGLE_ROUTE_OPTIMIZATION_SERVICE_ACCOUNT_FILE", "").strip()
    if service_account:
        configured_path = Path(service_account)
        if not configured_path.is_absolute():
            configured_path = BACKEND_DIR / configured_path
        if not configured_path.is_file():
            warning("Conta de serviço Google não encontrada. O sistema básico pode iniciar, mas a otimização real Google ficará indisponível até a credencial ser configurada.")
    if not values.get("MAPTILER_API_KEY", "").strip():
        warning("MAPTILER_API_KEY não configurada; o Dashboard/mapa não renderizará os tiles até essa chave ser configurada.")
    return pending_critical


def import_check(python_path: Path, cwd: Path, module: str, label: str) -> None:
    run_command([str(python_path), "-c", f"import {module}"], cwd=cwd)
    ok(label)


def validate_runtime_imports() -> None:
    if not BACKEND_PYTHON.is_file() or not ROOT_PYTHON.is_file() or not FLET_EXE.is_file():
        raise BootstrapError("Executável essencial de backend, frontend ou Flet não foi encontrado.")
    import_check(BACKEND_PYTHON, BACKEND_DIR, "fastapi", "Import fastapi")
    import_check(BACKEND_PYTHON, BACKEND_DIR, "uvicorn", "Import uvicorn")
    import_check(BACKEND_PYTHON, BACKEND_DIR, "sqlalchemy", "Import sqlalchemy")
    import_check(BACKEND_PYTHON, BACKEND_DIR, "app.main", "Import app.main")
    import_check(ROOT_PYTHON, FRONTEND_DIR, "flet", "Import flet")
    import_check(ROOT_PYTHON, FRONTEND_DIR, "flet_map", "Import flet_map")
    import_check(ROOT_PYTHON, FRONTEND_DIR, "flet_geolocator", "Import flet_geolocator")
    import_check(ROOT_PYTHON, FRONTEND_DIR, "websockets", "Import websockets")
    import_check(ROOT_PYTHON, FRONTEND_DIR, "app.application", "Import app.application")
    ok("Flet")
    ok("WebSocket")


def main() -> int:
    print("=" * 40)
    print(" Rota Inteligente - Preparação do ambiente")
    print("=" * 40)
    try:
        validate_python(Path(sys.executable))
        env_values = ensure_backend_env()
        pending_critical = report_env(env_values)
        backend_python = ensure_venv(BACKEND_VENV, "backend")
        if backend_python != BACKEND_PYTHON:
            raise BootstrapError("Caminho inesperado do Python do backend.")
        install_requirements(BACKEND_PYTHON, BACKEND_DIR / "requirements.txt", "backend")
        pip_check(BACKEND_PYTHON, "backend")
        root_python = ensure_venv(ROOT_VENV, "frontend")
        if root_python != ROOT_PYTHON:
            raise BootstrapError("Caminho inesperado do Python do frontend.")
        install_requirements(ROOT_PYTHON, FRONTEND_DIR / "requirements.txt", "frontend")
        pip_check(ROOT_PYTHON, "frontend")
        validate_runtime_imports()
        info("Banco development será preparado pelo backend no primeiro startup.")
        print("=" * 40)
        if pending_critical:
            print(" Instalação concluída com pendências")
            print("=" * 40)
            print("Edite:")
            print("backend-api/.env")
            print("e depois execute:")
            print(r".\.venv\Scripts\python.exe run.py")
        else:
            print(" Instalação concluída")
            print("=" * 40)
            print("Agora execute:")
            print(r".\.venv\Scripts\python.exe run.py")
        return 0
    except (OSError, BootstrapError) as exc:
        print(f"[ERRO] {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
