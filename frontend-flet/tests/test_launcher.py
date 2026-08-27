import importlib.util
import socket
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest


LAUNCHER_PATH = Path(__file__).parents[2] / "run.py"
SPEC = importlib.util.spec_from_file_location("launcher", LAUNCHER_PATH)
launcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(launcher)


def test_port_available_and_occupied():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        assert launcher.check_port_available(port=port) is False

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as free_listener:
        free_listener.bind(("127.0.0.1", 0))
        port = free_listener.getsockname()[1]
    assert launcher.check_port_available(port=port) is True


def test_wait_for_backend_requires_healthcheck():
    process = Mock()
    process.poll.side_effect = [None, None]
    checks = iter([False, True])
    launcher.wait_for_backend(process, timeout=1, healthcheck=lambda _: next(checks), sleep=lambda _: None)
    assert process.poll.call_count == 2


def test_wait_for_backend_fails_when_process_exits():
    process = Mock()
    process.poll.return_value = 1
    with pytest.raises(RuntimeError, match="encerrou"):
        launcher.wait_for_backend(process, timeout=1, healthcheck=lambda _: True, sleep=lambda _: None)


def test_wait_for_backend_timeout():
    process = Mock()
    process.poll.return_value = None
    with pytest.raises(TimeoutError, match="healthcheck"):
        launcher.wait_for_backend(process, timeout=0, healthcheck=lambda _: False, sleep=lambda _: None)


def test_frontend_starts_only_after_backend_health(monkeypatch, tmp_path):
    backend = Mock()
    backend.poll.return_value = None
    frontend = Mock()
    frontend.poll.return_value = None
    frontend.wait.return_value = 0
    starts = []
    backend_path = tmp_path / "backend-python"
    flet_path = tmp_path / "flet.exe"
    backend_path.touch()
    flet_path.touch()
    monkeypatch.setattr(launcher, "BACKEND_PYTHON", backend_path)
    monkeypatch.setattr(launcher, "FLET_EXE", flet_path)
    monkeypatch.setattr(launcher, "check_port_available", lambda: True)
    monkeypatch.setattr(launcher, "wait_for_backend", lambda process: starts.append("healthy"))
    monkeypatch.setattr(launcher, "start_process", lambda command, cwd, env: starts.append(command[0]) or (backend if len(starts) == 1 else frontend))
    assert launcher.run() == 0
    assert starts[0] == str(launcher.BACKEND_PYTHON)
    assert starts[1] == "healthy"
    assert starts[2] == str(launcher.FLET_EXE)
    assert backend.terminate.call_count == 1


def test_backend_failure_does_not_start_frontend(monkeypatch, tmp_path):
    backend = Mock()
    backend.poll.return_value = 1
    starts = []
    backend_path = tmp_path / "backend-python"
    flet_path = tmp_path / "flet.exe"
    backend_path.touch()
    flet_path.touch()
    monkeypatch.setattr(launcher, "BACKEND_PYTHON", backend_path)
    monkeypatch.setattr(launcher, "FLET_EXE", flet_path)
    monkeypatch.setattr(launcher, "check_port_available", lambda: True)
    monkeypatch.setattr(launcher, "start_process", lambda command, cwd, env: starts.append(command) or backend)
    monkeypatch.setattr(launcher, "wait_for_backend", lambda process: (_ for _ in ()).throw(RuntimeError("backend failed")))
    assert launcher.run() == 1
    assert len(starts) == 1


def test_cleanup_terminates_children_and_handles_already_stopped():
    frontend = Mock()
    backend = Mock()
    frontend.poll.return_value = None
    backend.poll.return_value = None
    launcher.cleanup(frontend, backend)
    frontend.terminate.assert_called_once_with()
    backend.terminate.assert_called_once_with()

    stopped = Mock()
    stopped.poll.return_value = 0
    launcher.stop_process(stopped, "stopped")
    stopped.terminate.assert_not_called()


def test_exception_path_cleans_up(monkeypatch, tmp_path):
    backend = Mock()
    backend.poll.return_value = None
    backend_path = tmp_path / "backend-python"
    flet_path = tmp_path / "flet.exe"
    backend_path.touch()
    flet_path.touch()
    monkeypatch.setattr(launcher, "BACKEND_PYTHON", backend_path)
    monkeypatch.setattr(launcher, "FLET_EXE", flet_path)
    monkeypatch.setattr(launcher, "check_port_available", lambda: True)
    monkeypatch.setattr(launcher, "start_process", lambda command, cwd, env: backend)
    monkeypatch.setattr(launcher, "wait_for_backend", Mock(side_effect=ValueError("unexpected")))
    assert launcher.run() == 1
    backend.terminate.assert_called_once_with()