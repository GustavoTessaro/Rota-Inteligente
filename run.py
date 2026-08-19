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
