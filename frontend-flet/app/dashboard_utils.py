from __future__ import annotations

from typing import Any


DASHBOARD_INDICATORS = [
    ("Total de entregas hoje", "entregas_hoje"),
    ("Entregas concluídas", "entregas_concluidas"),
    ("Entregas em andamento", "entregas_andamento"),
    ("Entregas atrasadas", "entregas_atrasadas"),
    ("Rotas em execução", "rotas_em_execucao"),
    ("Veículos disponíveis", "veiculos_disponiveis"),
    ("Motoristas ativos", "motoristas_ativos"),
]


def get_dashboard_indicator_values(data: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for _, key in DASHBOARD_INDICATORS:
        values[key] = data.get(key, 0)
    return values
