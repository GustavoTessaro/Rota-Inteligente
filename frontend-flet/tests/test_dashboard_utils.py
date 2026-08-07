import importlib.util
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "app" / "dashboard_utils.py"
SPEC = importlib.util.spec_from_file_location("frontend_dashboard_utils", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

get_dashboard_indicator_values = MODULE.get_dashboard_indicator_values
DashboardRefreshController = MODULE.DashboardRefreshController


def test_get_dashboard_indicator_values_uses_live_dashboard_payload():
    data = {
        "entregas_hoje": 12,
        "entregas_concluidas": 8,
        "entregas_andamento": 4,
        "entregas_atrasadas": 2,
        "rotas_em_execucao": 3,
        "veiculos_disponiveis": 6,
        "motoristas_ativos": 5,
    }

    values = get_dashboard_indicator_values(data)

    assert values["entregas_hoje"] == 12
    assert values["entregas_andamento"] == 4
    assert values["entregas_atrasadas"] == 2
    assert values["rotas_em_execucao"] == 3
    assert values["veiculos_disponiveis"] == 6
    assert values["motoristas_ativos"] == 5


def test_dashboard_refresh_controller_does_not_run_concurrently():
    counter = {"value": 0}
    active = {"value": 0}

    def callback():
        active["value"] += 1
        if active["value"] > 1:
            counter["value"] += 1
        else:
            time.sleep(0.05)
        active["value"] -= 1

    controller = DashboardRefreshController(callback=callback, interval=0.01)
    controller.start()
    controller.refresh_once()
    controller.refresh_once()
    controller.stop()

    assert counter["value"] == 0


def test_dashboard_refresh_controller_recovers_from_callback_errors():
    calls = {"value": 0}

    def callback():
        calls["value"] += 1
        if calls["value"] == 1:
            raise RuntimeError("boom")

    controller = DashboardRefreshController(callback=callback, interval=0.01)
    controller.start()
    time.sleep(0.06)
    controller.stop()

    assert calls["value"] >= 2
