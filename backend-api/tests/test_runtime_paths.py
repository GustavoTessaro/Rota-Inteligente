import importlib.util
import sqlite3
from pathlib import Path

from app import runtime_paths


RUNNER_PATH = Path(__file__).resolve().parents[2] / "run.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("project_run", RUNNER_PATH)
RUNNER_MODULE = importlib.util.module_from_spec(RUNNER_SPEC)
assert RUNNER_SPEC and RUNNER_SPEC.loader is not None
RUNNER_SPEC.loader.exec_module(RUNNER_MODULE)


def test_development_database_uses_project_sqlite_file(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ROTA_INTELIGENTE_PACKAGED", raising=False)
    monkeypatch.setattr(runtime_paths, "is_packaged_runtime", lambda: False)

    database_url = runtime_paths.resolve_database_url()
    expected = (Path(__file__).resolve().parents[1] / "test_entregas.db").resolve()
    assert database_url == f"sqlite:///{expected.as_posix()}"


def test_windows_packaged_runtime_uses_localappdata(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Local"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ROTA_INTELIGENTE_PACKAGED", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setattr(runtime_paths, "is_packaged_runtime", lambda: True)
    monkeypatch.setattr(runtime_paths.sys, "platform", "win32", raising=False)

    database_url = runtime_paths.resolve_database_url()
    expected = appdata / "Rota Inteligente" / "data" / "rota_inteligente.db"
    assert database_url == f"sqlite:///{expected.as_posix()}"
    assert runtime_paths.get_writable_application_directory() == expected.parent
    assert expected.parent.exists()


def test_explicit_database_url_keeps_priority(monkeypatch, tmp_path):
    explicit_url = f"sqlite:///{(tmp_path / 'custom.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", explicit_url)
    monkeypatch.setenv("ROTA_INTELIGENTE_PACKAGED", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setattr(runtime_paths, "is_packaged_runtime", lambda: True)

    assert runtime_paths.resolve_database_url() == explicit_url


def test_existing_packaged_database_is_never_overwritten(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Local"
    db_path = appdata / "Rota Inteligente" / "data" / "rota_inteligente.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("existing", encoding="utf-8")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ROTA_INTELIGENTE_PACKAGED", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setattr(runtime_paths, "is_packaged_runtime", lambda: True)

    info = runtime_paths.get_runtime_database_info()
    assert info["database_path"] == db_path
    assert info["database_exists"] is True
    assert info["should_copy_development_db"] is False


def test_path_with_spaces_is_preserved(monkeypatch, tmp_path):
    appdata = tmp_path / "Local App Data"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ROTA_INTELIGENTE_PACKAGED", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setattr(runtime_paths, "is_packaged_runtime", lambda: True)

    database_url = runtime_paths.resolve_database_url()
    expected = (appdata / "Rota Inteligente" / "data" / "rota_inteligente.db").resolve()
    assert database_url == f"sqlite:///{expected.as_posix()}"
    assert "Local App Data" in database_url


def test_meipass_is_not_used_as_writable_data_target(monkeypatch, tmp_path):
    meipass = tmp_path / "_MEIPASS"
    meipass.mkdir(parents=True, exist_ok=True)
    appdata = tmp_path / "AppData" / "Local"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ROTA_INTELIGENTE_PACKAGED", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setattr(runtime_paths, "is_packaged_runtime", lambda: True)
    monkeypatch.setattr(runtime_paths.sys, "_MEIPASS", str(meipass), raising=False)

    directory = runtime_paths.get_writable_application_directory()
    assert str(meipass) not in str(directory)
    assert directory == appdata / "Rota Inteligente" / "data"


def test_launcher_uses_localhost_url():
    assert RUNNER_MODULE.DESKTOP_API_BASE_URL == "http://127.0.0.1:8000/api"
    assert RUNNER_MODULE.BACKEND_HEALTH_URL == "http://127.0.0.1:8000/health"


def test_frozen_runtime_uses_internal_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER_MODULE.sys, "frozen", True, raising=False)
    monkeypatch.setattr(RUNNER_MODULE.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(RUNNER_MODULE, "BACKEND_PYTHON", tmp_path / "missing_backend_python.exe", raising=False)
    monkeypatch.setattr(RUNNER_MODULE, "FLET_EXE", tmp_path / "missing_flet.exe", raising=False)
    assert RUNNER_MODULE.is_frozen_runtime() is True
    assert RUNNER_MODULE._runtime_search_roots()


def test_frozen_runtime_does_not_need_external_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(RUNNER_MODULE.sys, "frozen", True, raising=False)
    monkeypatch.setattr(RUNNER_MODULE.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(RUNNER_MODULE, "BACKEND_PYTHON", tmp_path / "missing_backend_python.exe", raising=False)
    monkeypatch.setattr(RUNNER_MODULE, "FLET_EXE", tmp_path / "missing_flet.exe", raising=False)
    monkeypatch.setattr(RUNNER_MODULE, "check_port_available", lambda *args, **kwargs: True)
    assert RUNNER_MODULE.is_frozen_runtime() is True
    assert not str(RUNNER_MODULE.BACKEND_PYTHON).endswith(".venv\\Scripts\\python.exe")
    assert not str(RUNNER_MODULE.FLET_EXE).endswith(".venv\\Scripts\\flet.exe")


def test_seed_database_is_used_only_as_packaged_resource(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Local"
    seed_source = tmp_path / "_MEIPASS" / "backend-api" / "test_entregas.db"
    seed_source.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(seed_source) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS seed_table (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO seed_table (value) VALUES ('seed-content')")
        connection.commit()

    monkeypatch.setattr(runtime_paths.sys, "_MEIPASS", str(tmp_path / "_MEIPASS"), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(appdata))
    monkeypatch.setenv("ROTA_INTELIGENTE_PACKAGED", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    prepared = runtime_paths.ensure_packaged_database_seed()
    assert prepared == appdata / "Rota Inteligente" / "data" / "rota_inteligente.db"
    assert prepared.exists() is True
    with sqlite3.connect(prepared) as connection:
        rows = connection.execute("SELECT value FROM seed_table").fetchall()
    assert rows == [("seed-content",)]
    assert str(runtime_paths.get_writable_application_directory()).endswith("Rota Inteligente\\data")
