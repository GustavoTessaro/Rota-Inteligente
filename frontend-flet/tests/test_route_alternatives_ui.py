from app.application import DeliveryApp


def _texts(control):
    result = []
    if hasattr(control, "value") and control.value:
        result.append(control.value)
    if hasattr(control, "text") and isinstance(control.text, str) and control.text:
        result.append(control.text)
    for child in getattr(control, "controls", []) or []:
        result.extend(_texts(child))
    child = getattr(control, "content", None)
    if child is not None:
        result.extend(_texts(child))
    return result


def test_driver_alternatives_panel_shows_recommendation_and_selection_action():
    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "MOTORISTA"}
    route = {
        "id": 7,
        "alternativas_equivalentes": False,
        "alternativa_escolhida_id": None,
        "alternativas": [
            {"id": 1, "criterio": "MAIS_RAPIDA", "duracao_prevista": 0.5, "distancia_prevista": 20, "sequencia": [3], "recomendada": True},
            {"id": 2, "criterio": "MAIS_CURTA", "duracao_prevista": 0.6, "distancia_prevista": 18, "sequencia": [3], "recomendada": False},
        ],
    }

    panel = app._route_alternatives_panel(route, allow_selection=True)
    texts = _texts(panel)

    assert "Recomendada pelo gestor" in texts
    assert sum(text == "Escolher esta alternativa" for text in texts) == 2


def test_equivalent_alternatives_are_presented_as_one_logical_choice():
    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "MOTORISTA"}
    route = {
        "alternativas_equivalentes": True,
        "alternativa_escolhida_id": None,
        "alternativas": [
            {"id": 1, "criterio": "MAIS_RAPIDA", "duracao_prevista": 1, "distancia_prevista": 1, "sequencia": [1]},
            {"id": 2, "criterio": "MAIS_CURTA", "duracao_prevista": 1, "distancia_prevista": 1, "sequencia": [1]},
        ],
    }

    panel = app._route_alternatives_panel(route, allow_selection=True)
    texts = _texts(panel)

    assert "As opções mais rápida e mais curta resultaram equivalentes." in texts
    assert texts.count("Escolher esta alternativa") == 1