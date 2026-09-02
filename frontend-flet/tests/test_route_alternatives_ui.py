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
        "entregas": [
            {"id": 3, "entrega_id": 16, "cliente": {"nome": "Cliente A"}},
        ],
        "alternativas": [
            {"id": 1, "criterio": "MAIS_RAPIDA", "duracao_prevista": 0.5, "distancia_prevista": 20, "sequencia": [3], "recomendada": True},
            {"id": 2, "criterio": "MAIS_CURTA", "duracao_prevista": 0.6, "distancia_prevista": 18, "sequencia": [3], "recomendada": False},
        ],
    }

    panel = app._route_alternatives_panel(route, allow_selection=True)
    texts = _texts(panel)

    assert "Recomendada pelo gestor" in texts
    assert sum(text == "Escolher esta alternativa" for text in texts) == 2
    assert "Sequência: 1. Cliente A" in texts
    assert "#3" not in texts


def test_equivalent_alternatives_are_presented_as_one_logical_choice():
    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "MOTORISTA"}
    route = {
        "alternativas_equivalentes": True,
        "alternativa_escolhida_id": None,
        "entregas": [
            {"id": 1, "entrega_id": 16, "cliente": {"nome": "Cliente Um"}},
        ],
        "alternativas": [
            {"id": 1, "criterio": "MAIS_RAPIDA", "duracao_prevista": 1, "distancia_prevista": 1, "sequencia": [1]},
            {"id": 2, "criterio": "MAIS_CURTA", "duracao_prevista": 1, "distancia_prevista": 1, "sequencia": [1]},
        ],
    }

    panel = app._route_alternatives_panel(route, allow_selection=True)
    texts = _texts(panel)

    assert "As opções mais rápida e mais curta resultaram equivalentes." in texts
    assert texts.count("Escolher esta alternativa") == 1


def test_driver_alternatives_panel_preserves_sequence_order_and_uses_fallback_label():
    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": "MOTORISTA"}
    route = {
        "alternativas_equivalentes": False,
        "alternativa_escolhida_id": 2,
        "entregas": [
            {"id": 10, "entrega_id": 16, "cliente": {"nome": "Cliente Dez"}},
            {"id": 11, "entrega_id": 17, "cliente": {}},
            {"id": 12, "entrega_id": 18, "cliente": {"nome": "Cliente Doze"}},
        ],
        "alternativas": [
            {
                "id": 2,
                "criterio": "MAIS_CURTA",
                "duracao_prevista": 1,
                "distancia_prevista": 1,
                "sequencia": [12, 10, 11],
                "selecionada": True,
            },
        ],
    }

    panel = app._route_alternatives_panel(route)
    texts = _texts(panel)

    assert "Sequência: 1. Cliente Doze → 2. Cliente Dez → 3. Parada 3" in texts
    assert "#12" not in texts
    assert "#10" not in texts
    assert "#11" not in texts
    assert "Rota selecionada" in texts