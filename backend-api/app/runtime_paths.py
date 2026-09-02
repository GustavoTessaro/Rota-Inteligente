import os
import shutil
import sys
from pathlib import Path
from typing import Any

APP_NAME = "Rota Inteligente"
DEVELOPMENT_DATABASE_NAME = "test_entregas.db"
PACKAGED_DATABASE_NAME = "rota_inteligente.db"
WRITABLE_DATA_DIRNAME = "data"


def is_packaged_runtime() -> bool:
    if os.environ.get("ROTA_INTELIGENTE_PACKAGED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return bool(getattr(sys, "frozen", False))


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_development_database_path() -> Path:
    return (_backend_root() / DEVELOPMENT_DATABASE_NAME).resolve()


def get_seed_database_candidates() -> list[Path]:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        meipass_path = Path(meipass)
        candidates.extend([
            meipass_path / DEVELOPMENT_DATABASE_NAME,
            meipass_path / "backend-api" / DEVELOPMENT_DATABASE_NAME,
            meipass_path / "data" / DEVELOPMENT_DATABASE_NAME,
            meipass_path / "backend-api" / "data" / DEVELOPMENT_DATABASE_NAME,
        ])

    project_root = _backend_root()
    candidates.extend([
        project_root / DEVELOPMENT_DATABASE_NAME,
        project_root / "data" / DEVELOPMENT_DATABASE_NAME,
    ])
    return [path.resolve() for path in candidates if path.exists()]


def get_seed_database_path() -> Path:
    candidates = get_seed_database_candidates()
    if candidates:
        return candidates[0]
    return get_development_database_path()


def get_writable_application_directory() -> Path:
    if not is_packaged_runtime():
        return get_development_database_path().parent

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base_dir = Path(local_app_data).expanduser()
    else:
        base_dir = Path.home() / "AppData" / "Local"

    writable_dir = (base_dir / APP_NAME / WRITABLE_DATA_DIRNAME).resolve()
    return writable_dir


def get_packaged_database_path() -> Path:
    return (get_writable_application_directory() / PACKAGED_DATABASE_NAME).resolve()


def ensure_writable_application_directory() -> Path:
    directory = get_writable_application_directory()
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def ensure_packaged_database_seed() -> Path:
    """Seed strategy for the first packaged Windows run.

    The packaged database is never the active database; it is used only as a one-time
    seed source when the user data directory does not yet exist.
    """
    if not is_packaged_runtime():
        return get_development_database_path()

    destination = get_packaged_database_path()
    if destination.exists():
        return destination

    seed_source = get_seed_database_path()
    ensure_writable_application_directory()
    if seed_source.exists() and seed_source != destination:
        shutil.copy2(seed_source, destination)
    return destination


def resolve_database_url() -> str:
    explicit_database_url = os.environ.get("DATABASE_URL", "").strip()
    if explicit_database_url:
        return explicit_database_url

    if is_packaged_runtime():
        database_path = ensure_packaged_database_seed()
        return f"sqlite:///{database_path.as_posix()}"

    development_database = get_development_database_path()
    return f"sqlite:///{development_database.as_posix()}"


def maybe_copy_development_database_if_needed(copy_if_missing: bool = False) -> Path | None:
    if not is_packaged_runtime():
        return None

    database_path = get_packaged_database_path()
    if database_path.exists():
        return database_path

    if not copy_if_missing:
        return database_path

    seed_source = get_seed_database_path()
    if not seed_source.exists():
        return database_path

    ensure_writable_application_directory()
    shutil.copy2(seed_source, database_path)
    return database_path


def get_runtime_database_info() -> dict[str, Any]:
    explicit_database_url = os.environ.get("DATABASE_URL", "").strip()
    packaged_runtime = is_packaged_runtime()
    writable_directory = get_writable_application_directory()
    packaged_database = get_packaged_database_path()
    development_database = get_development_database_path()
    database_path = packaged_database if packaged_runtime and not explicit_database_url else (
        Path(explicit_database_url.replace("sqlite:///", "", 1).replace("sqlite://", "", 1)).resolve()
        if explicit_database_url.startswith("sqlite")
        else development_database
    )

    if explicit_database_url and explicit_database_url.startswith("sqlite"):
        database_path = Path(explicit_database_url.replace("sqlite:///", "", 1).replace("sqlite://", "", 1)).resolve()
    elif packaged_runtime:
        database_path = packaged_database
    else:
        database_path = development_database

    return {
        "mode": "packaged" if packaged_runtime else "development",
        "database_url": resolve_database_url(),
        "database_path": database_path,
        "database_exists": database_path.exists(),
        "writable_directory": writable_directory,
        "development_database_path": development_database,
        "packaged_database_path": packaged_database,
        "explicit_database_url": explicit_database_url,
        "should_copy_development_db": packaged_runtime and not database_path.exists() and explicit_database_url == "" and development_database.exists(),
    }
