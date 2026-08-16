"""
Testes de regressão para a seleção de pedidos em Gestão de Entregas.

Valida que a sincronização de estado de checkboxes funciona corretamente:
- Clique individual habilita/desabilita o botão
- "Selecionar Todos" continua funcionando
- "Limpar seleção" funciona
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_delivery_order_toggle_state_update():
    """Verifica que _toggle_delivery_order() atualiza a view corretamente."""
    from unittest.mock import MagicMock, patch
    from app.application import DeliveryApp
    import flet as ft

    # Criar mock do page
    mock_page = MagicMock()
    mock_page.title = ""
    mock_page.theme_mode = None
    mock_page.theme = None
    mock_page.padding = 0

    app = DeliveryApp(mock_page)

    # Estado inicial: sem pedidos selecionados
    app.delivery_management_selection = {"pedido_ids": []}
    assert app.delivery_management_selection["pedido_ids"] == []

    # Mockar delivery_management_view para rastrear chamadas
    view_call_count = 0
    original_view = app.delivery_management_view

    def mock_delivery_management_view():
        nonlocal view_call_count
        view_call_count += 1

    app.delivery_management_view = mock_delivery_management_view

    # Teste 1: Marcar primeiro pedido
    app._toggle_delivery_order(order_id=1, checked=True)
    assert app.delivery_management_selection["pedido_ids"] == [1], "Pedido 1 deveria estar selecionado"
    assert view_call_count == 1, "delivery_management_view() deveria ter sido chamado após toggle individual"

    # Teste 2: Marcar segundo pedido
    app._toggle_delivery_order(order_id=2, checked=True)
    assert app.delivery_management_selection["pedido_ids"] == [1, 2], "Pedidos 1 e 2 deveriam estar selecionados"
    assert view_call_count == 2, "delivery_management_view() deveria ter sido chamado novamente"

    # Teste 3: Desmarcar primeiro pedido
    app._toggle_delivery_order(order_id=1, checked=False)
    assert app.delivery_management_selection["pedido_ids"] == [2], "Apenas pedido 2 deveria estar selecionado"
    assert view_call_count == 3, "delivery_management_view() deveria ter sido chamado novamente"

    # Teste 4: Desmarcar segundo pedido (lista vazia)
    app._toggle_delivery_order(order_id=2, checked=False)
    assert app.delivery_management_selection["pedido_ids"] == [], "Nenhum pedido deveria estar selecionado"
    assert view_call_count == 4, "delivery_management_view() deveria ter sido chamado novamente"

    # Teste 5: Não duplicar ao marcar novamente (e reconstruir view)
    app._toggle_delivery_order(order_id=1, checked=True)
    app._toggle_delivery_order(order_id=1, checked=True)  # Marcar novamente sem desmarcar
    assert app.delivery_management_selection["pedido_ids"] == [1], "Pedido 1 não deveria duplicar"
    # Ambas as chamadas reconstroem a view por consistência
    assert view_call_count == 6, "Ambas as chamadas devem reconstruir a view"


def test_select_all_clears_and_consistency():
    """Verifica que _select_all_orders() e _clear_selected_orders() funcionam."""
    from unittest.mock import MagicMock
    from app.application import DeliveryApp

    mock_page = MagicMock()
    app = DeliveryApp(mock_page)

    app.delivery_management_selection = {"pedido_ids": []}

    # Mockar delivery_management_view
    view_calls = []

    def mock_view():
        view_calls.append(app.delivery_management_selection["pedido_ids"].copy())

    app.delivery_management_view = mock_view

    available_orders = [
        {"id": 1, "numero_pedido": "PED-001"},
        {"id": 2, "numero_pedido": "PED-002"},
        {"id": 3, "numero_pedido": "PED-003"},
    ]

    # Teste 1: Selecionar todos
    app._select_all_orders(available_orders)
    assert app.delivery_management_selection["pedido_ids"] == [1, 2, 3], "Todos os pedidos deveriam estar selecionados"
    assert view_calls[-1] == [1, 2, 3]

    # Teste 2: Limpar seleção
    app._clear_selected_orders()
    assert app.delivery_management_selection["pedido_ids"] == [], "Nenhum pedido deveria estar selecionado"
    assert view_calls[-1] == []


if __name__ == "__main__":
    test_delivery_order_toggle_state_update()
    test_select_all_clears_and_consistency()
    print("✅ Todos os testes de regressão passaram!")
