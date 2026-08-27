import importlib.util
import sys
import types
from pathlib import Path


CONFIG_PATH = Path(__file__).parents[1] / "app" / "config.py"
PREPARE_PATH = Path(__file__).parents[2] / "tools" / "prepare_android_build.py"


def load_config(monkeypatch, generated=None):
    sys.modules.pop("app.config", None)
    sys.modules.pop("app.generated_config", None)
    if generated is None:
        generated_module = types.ModuleType("app.generated_config")
        generated_module.BUILD_API_BASE_URL = None
        generated_module.BUILD_MAPTILER_API_KEY = None
        sys.modules["app.generated_config"] = generated_module
    else:
        generated_module = types.ModuleType("app.generated_config")
        generated_module.BUILD_API_BASE_URL = generated.BUILD_API_BASE_URL
        generated_module.BUILD_MAPTILER_API_KEY = generated.BUILD_MAPTILER_API_KEY
        sys.modules["app.generated_config"] = generated_module
    spec = importlib.util.spec_from_file_location("app.config", CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import app

    sys.modules["app.config"] = module
    spec.loader.exec_module(module)
    return module


def test_config_uses_desktop_localhost_fallback(monkeypatch):
    monkeypatch.setenv("ROTA_DESKTOP_LOCAL", "1")
    config = load_config(monkeypatch)
    assert config.API_BASE_URL == "http://127.0.0.1:8000/api"
    assert config.MAPTILER_API_KEY == ""


def test_desktop_override_does_not_change_generated_android_config(monkeypatch):
    monkeypatch.setenv("ROTA_DESKTOP_LOCAL", "1")
    generated = type("Generated", (), {
        "BUILD_API_BASE_URL": "http://10.0.0.8:8000/api",
        "BUILD_MAPTILER_API_KEY": "fake-generated-key",
    })
    config = load_config(monkeypatch, generated)
    assert config.API_BASE_URL == "http://127.0.0.1:8000/api"
    assert config.BUILD_API_BASE_URL == "http://10.0.0.8:8000/api"
    assert config.MAPTILER_API_KEY == "fake-generated-key"


def test_config_uses_environment(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://example.test/api")
    monkeypatch.setenv("MAPTILER_API_KEY", "fake-map-key")
    config = load_config(monkeypatch)
    assert config.API_BASE_URL == "https://example.test/api"
    assert config.MAPTILER_API_KEY == "fake-map-key"


def test_generated_config_has_priority(monkeypatch):
    generated = type("Generated", (), {
        "BUILD_API_BASE_URL": "https://generated.test/api",
        "BUILD_MAPTILER_API_KEY": "fake-generated-key",
    })
    monkeypatch.setenv("API_BASE_URL", "https://environment.test/api")
    monkeypatch.setenv("MAPTILER_API_KEY", "fake-environment-key")
    config = load_config(monkeypatch, generated)
    assert config.API_BASE_URL == "https://generated.test/api"
    assert config.MAPTILER_API_KEY == "fake-generated-key"


def test_tracking_websocket_is_derived_from_api_url(monkeypatch):
    config = load_config(monkeypatch)
    assert config.build_tracking_ws_url("http://example.test:8000/api") == "ws://example.test:8000/ws/tracking"
    assert config.build_tracking_ws_url("https://example.test/api") == "wss://example.test/ws/tracking"


def test_prepare_script_validates_url_and_generates_without_markdown(tmp_path):
    spec = importlib.util.spec_from_file_location("prepare_android_build", PREPARE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    output = tmp_path / "generated_config.py"
    result = module.validate_api_base_url("http://10.0.0.8:8000/api")
    output.write_text(
        f"BUILD_API_BASE_URL = {result!r}\nBUILD_MAPTILER_API_KEY = {'fake-key'!r}\n",
        encoding="utf-8",
    )
    content = output.read_text(encoding="utf-8")
    assert "http://10.0.0.8:8000/api" in content
    assert "[http://" not in content


def test_prepare_script_rejects_invalid_urls():
    spec = importlib.util.spec_from_file_location("prepare_android_build", PREPARE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    for value in (
        "http://127.0.0.1:8000",
        "ftp://example.test/api",
        "http:///api",
        "[http://example.test/api](http://example.test/api)",
        "http://example.test/api/",
    ):
        try:
            module.validate_api_base_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"URL deveria ser rejeitada: {value}")