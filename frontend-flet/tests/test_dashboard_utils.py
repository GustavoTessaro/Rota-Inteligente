import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "app" / "dashboard_utils.py"
SPEC = importlib.util.spec_from_file_location("frontend_dashboard_utils", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

get_dashboard_indicator_values = MODULE.get_dashboard_indicator_values


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
