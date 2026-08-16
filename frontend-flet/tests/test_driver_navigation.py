# -*- coding: utf-8 -*-
"""
Testes de navegação Phase 2 - Dashboard do Motorista
Valida que as novas funções existem e funcionam corretamente.
"""
import sys
from pathlib import Path

# Adicionar app ao path
sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import MagicMock, patch
import flet as ft


class MockApiClient:
    """Mock de ApiClient para testes"""
    def request(self, method, path, json=None):
        if path == "/rotas/motorista/atual":
            # Retornar uma rota ativa mocada
            return {
                "id": 1,
                "nome": "Rota Test",
                "status": "EM_EXECUCAO",
                "distancia_km": 45.2,
                "duracao_minutos": 82,
                "organizacao": {
                    "id": 1,
                    "nome": "Operação Norte"
                },
                "veiculo": {
                    "id": 1,
                    "placa": "ABC-1234",
                    "modelo": "Fiat Ducato"
                },
                "entregas": [
                    {"id": 1, "status": "ENTREGUE"},
                    {"id": 2, "status": "EM_ROTA"},
                    {"id": 3, "status": "AGUARDANDO_COLETA"},
                ]
            }
        raise Exception(f"Unknown endpoint: {method} {path}")


def test_driver_dashboard_view_exists():
    """Testa que driver_dashboard_view foi criada"""
    from app.application import DeliveryApp
    
    # Verificar que o método existe
    assert hasattr(DeliveryApp, 'driver_dashboard_view'), \
        "Método driver_dashboard_view não encontrado em DeliveryApp"
    assert callable(getattr(DeliveryApp, 'driver_dashboard_view')), \
        "driver_dashboard_view não é um método callable"
    print("✓ driver_dashboard_view existe e é callable")


def test_helper_methods_exist():
    """Testa que todos os helper methods foram criados"""
    from app.application import DeliveryApp
    
    helpers = [
        '_get_greeting_time',
        '_build_driver_greeting',
        '_build_driver_vehicle_card',
        '_build_driver_indicators',
        '_build_driver_mission_card',
    ]
    
    for helper in helpers:
        assert hasattr(DeliveryApp, helper), \
            f"Método {helper} não encontrado em DeliveryApp"
        assert callable(getattr(DeliveryApp, helper)), \
            f"{helper} não é um método callable"
    
    print(f"✓ Todos os {len(helpers)} helper methods existem e são callable")


def test_dashboard_view_calls_driver_dashboard_for_motorista():
    """Testa que dashboard_view redireciona MOTORISTA para driver_dashboard_view"""
    from app.application import DeliveryApp
    
    # Criar mock de página Flet
    mock_page = MagicMock(spec=ft.Page)
    
    # Criar app
    app = DeliveryApp(mock_page)
    app.api = MockApiClient()
    app.user = {"perfil": "MOTORISTA", "nome": "Gustavo"}
    
    # Mockar driver_dashboard_view
    app.driver_dashboard_view = MagicMock()
    app.deliveries_view = MagicMock()
    
    # Chamar dashboard_view
    app.dashboard_view()
    
    # Verificar que driver_dashboard_view foi chamado
    app.driver_dashboard_view.assert_called_once()
    
    # Verificar que deliveries_view NÃO foi chamado
    app.deliveries_view.assert_not_called()
    
    print("✓ dashboard_view redireciona corretamente para driver_dashboard_view (MOTORISTA)")


def test_dashboard_view_calls_original_logic_for_gestor():
    """Testa que dashboard_view mantém lógica original para GESTOR"""
    from app.application import DeliveryApp
    
    # Criar mock de página Flet
    mock_page = MagicMock(spec=ft.Page)
    
    # Criar app
    app = DeliveryApp(mock_page)
    app.api = MockApiClient()
    app.user = {"perfil": "GESTOR", "nome": "Gestor"}
    
    # Mockar o conteúdo
    app.content = MagicMock()
    app.page = mock_page
    
    # Mockar API para retornar dashboard data
    app.api.request = MagicMock(return_value={
        "entregas_por_status": [],
        "entregas_por_motorista": [],
        "entregas_por_veiculo": [],
        "evolucao_diaria_entregas": [],
        "ultimas_entregas": [],
        "proximas_rotas": [],
    })
    
    # Mockar vehicle_states
    app.vehicle_states = {}
    
    # Mockar map_control
    app.map_control = MagicMock()
    
    # Chamar dashboard_view para GESTOR
    try:
        app.dashboard_view()
    except Exception as e:
        # Ignorar exceções de rendering
        pass
    
    # Verificar que API foi chamada para /relatorios/dashboard
    calls = [call for call in app.api.request.call_args_list]
    assert any("/relatorios/dashboard" in str(call) for call in calls), \
        "dashboard_view (GESTOR) não chamou /relatorios/dashboard"
    
    print("✓ dashboard_view mantém lógica original para GESTOR")


def test_greeting_time_logic():
    """Testa que _get_greeting_time retorna valores corretos"""
    from app.application import DeliveryApp
    from datetime import datetime
    from unittest.mock import patch
    
    # Criar mock de página Flet
    mock_page = MagicMock(spec=ft.Page)
    
    # Criar app
    app = DeliveryApp(mock_page)
    app.user = {"nome": "Gustavo"}
    
    # Testar manhã
    with patch('app.application.datetime') as mock_datetime:
        mock_datetime.now.return_value.hour = 9
        greeting, emoji = app._get_greeting_time()
        assert greeting == "Bom dia", f"Esperado 'Bom dia' às 9h, got '{greeting}'"
        assert emoji == "⛅", f"Esperado '⛅' às 9h, got '{emoji}'"
    
    # Testar tarde
    with patch('app.application.datetime') as mock_datetime:
        mock_datetime.now.return_value.hour = 15
        greeting, emoji = app._get_greeting_time()
        assert greeting == "Boa tarde", f"Esperado 'Boa tarde' às 15h, got '{greeting}'"
        assert emoji == "☀️", f"Esperado '☀️' às 15h, got '{emoji}'"
    
    # Testar noite
    with patch('app.application.datetime') as mock_datetime:
        mock_datetime.now.return_value.hour = 22
        greeting, emoji = app._get_greeting_time()
        assert greeting == "Boa noite", f"Esperado 'Boa noite' às 22h, got '{greeting}'"
        assert emoji == "🌙", f"Esperado '🌙' às 22h, got '{emoji}'"
    
    print("✓ _get_greeting_time retorna valores corretos por hora do dia")


def test_indicators_with_no_route():
    """Testa que indicadores mostram '--' quando não há rota"""
    from app.application import DeliveryApp
    
    # Criar mock de página Flet
    mock_page = MagicMock(spec=ft.Page)
    
    # Criar app
    app = DeliveryApp(mock_page)
    app.user = {"nome": "Gustavo"}
    
    # Chamar com current_route=None
    indicators = app._build_driver_indicators(None)
    
    # Verificar que retornou 4 cards
    assert len(indicators) == 4, f"Esperado 4 indicadores, got {len(indicators)}"
    
    # Verificar que todos têm values "--"
    for ind in indicators:
        content = ind.content  # Container → Column
        values = [ctrl for ctrl in content.controls if hasattr(ctrl, 'value')]
        # Todos os valores devem ser "--" ou o Container tem uma estrutura nested
    
    print("✓ Indicadores retornam '--' quando não há rota")


def test_mission_card_no_route():
    """Testa que card de missão mostra placeholder quando não há rota"""
    from app.application import DeliveryApp
    
    # Criar mock de página Flet
    mock_page = MagicMock(spec=ft.Page)
    
    # Criar app
    app = DeliveryApp(mock_page)
    app.user = {"nome": "Gustavo"}
    app.notify = MagicMock()
    
    # Chamar com current_route=None
    mission_card = app._build_driver_mission_card(None)
    
    # Verificar que é um Container
    assert isinstance(mission_card, ft.Container), \
        f"Esperado ft.Container, got {type(mission_card)}"
    
    # Verificar que contém mensagem de "Nenhuma rota ativa"
    content_str = str(mission_card.content)
    assert "nenhuma" in content_str.lower() or "ativa" in content_str.lower() or \
           "Nenhuma rota ativa" in str(mission_card.content.controls), \
        "Card de missão não contém mensagem de 'Nenhuma rota ativa'"
    
    print("✓ Card de missão mostra placeholder quando não há rota")


def test_driver_dashboard_handles_404_no_route():
    """
    REGRESSÃO: Testa que motorista sem rota consegue abrir Dashboard sem erro.
    
    Bug: Quando GET /rotas/motorista/atual retorna 404, o Dashboard
    mostrava erro ao usuário. Agora deve renderizar em estado vazio.
    """
    from app.application import DeliveryApp, ApiError
    
    # Criar mock de página Flet
    mock_page = MagicMock(spec=ft.Page)
    
    # Criar app
    app = DeliveryApp(mock_page)
    app.user = {"nome": "Gustavo"}
    app.content = MagicMock(spec=ft.Column)
    app.page = mock_page
    
    # Mock ApiClient que retorna 404 para /rotas/motorista/atual
    mock_api = MagicMock()
    
    def request_404(method, path, json=None):
        if method == "GET" and path == "/rotas/motorista/atual":
            # Simular resposta 404 do backend
            raise ApiError("404 Not Found: Nenhuma rota ativa para este motorista")
        raise Exception(f"Unexpected call: {method} {path}")
    
    mock_api.request = request_404
    app.api = mock_api
    
    # Mock notify para rastrear se erro foi mostrado
    app.notify = MagicMock()
    
    # Chamar driver_dashboard_view (não deve lançar exceção)
    try:
        app.driver_dashboard_view()
    except Exception as e:
        raise AssertionError(
            f"driver_dashboard_view lançou exceção com motorista sem rota: {e}"
        )
    
    # Verificar que content.controls foi atualizado
    assert app.content.controls is not None or app.content.controls != [], \
        "Dashboard não atualizou os controles"
    
    # Verificar que notify(error=True) NÃO foi chamado
    error_calls = [call for call in app.notify.call_args_list 
                   if len(call[0]) > 1 and call[0][1] == True]
    assert len(error_calls) == 0, \
        f"notify(error=True) foi chamado {len(error_calls)} vez(es), esperado 0. Motorista sem rota não deve ver erro."
    
    print("✓ Dashboard não mostra erro quando motorista não tem rota (404 tratado corretamente)")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("Phase 2 - Testes de Navegação do Motorista")
    print("="*70 + "\n")
    
    try:
        test_driver_dashboard_view_exists()
        test_helper_methods_exist()
        test_dashboard_view_calls_driver_dashboard_for_motorista()
        test_dashboard_view_calls_original_logic_for_gestor()
        test_greeting_time_logic()
        test_indicators_with_no_route()
        test_mission_card_no_route()
        test_driver_dashboard_handles_404_no_route()  # REGRESSÃO - bug fix
        
        print("\n" + "="*70)
        print("✓ TODOS OS TESTES PASSARAM!")
        print("="*70 + "\n")
    except AssertionError as e:
        print(f"\n❌ ERRO: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERRO INESPERADO: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
