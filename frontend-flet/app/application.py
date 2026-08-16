from datetime import datetime, timezone
from urllib.parse import quote

import asyncio
import json
import threading
import time

import flet as ft

try:
    import websockets
except Exception:  # pragma: no cover - optional dependency during import
    websockets = None

from .api_client import ApiClient, ApiError
from .config import build_tracking_ws_url
from .dashboard_utils import DASHBOARD_INDICATORS, DashboardRefreshController, get_dashboard_indicator_values
from .map_view import MapView
from .tracking_client import build_marker, update_vehicle_state


STATUS_COLORS = {
    "AGUARDANDO_COLETA": ft.Colors.ORANGE,
    "COLETADA": ft.Colors.BLUE,
    "EM_ROTA": ft.Colors.PURPLE,
    "ENTREGUE": ft.Colors.GREEN,
    "NAO_ENTREGUE": ft.Colors.RED,
    "CANCELADA": ft.Colors.GREY,
}


class DeliveryApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.api = ApiClient()
        self.user = None
        self.websocket_client = None
        self.websocket_state = "desconectado"
        self.vehicle_states = {}
        self.connection_indicator = None
        self.dashboard_data = {}
        self.dashboard_active = False
        self.delivery_management_selection = {
            "pedido_ids": [],
            "pontos_coleta_ids": [],
            "ponto_coleta_id": None,
        }
        self.generated_route = None
        self.selected_route_id = None
        self.selected_marker_id = None
        self.selected_route_status_filter = ""
        self.dashboard_refresh_controller = DashboardRefreshController(callback=self._refresh_dashboard, interval=5.0)
        self.content = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def _toggle_delivery_order(self, order_id, checked):
        selected = self.delivery_management_selection.get("pedido_ids", [])
        if checked and order_id not in selected:
            selected.append(order_id)
        elif not checked and order_id in selected:
            selected = [item for item in selected if item != order_id]
        self.delivery_management_selection["pedido_ids"] = selected
        self.delivery_management_view()

    def start(self):
        self.page.title = "Gestão de Entregas"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        self.page.padding = 0
        self.show_login()

    def _refresh_dashboard(self):
        if self.user is None or self.user.get("perfil") == "MOTORISTA":
            return
        try:
            data = self.api.request("GET", "/relatorios/dashboard")
            self.dashboard_data = data
            if self.content.controls and getattr(self, "dashboard_active", False):
                self.dashboard_view()
        except Exception:
            pass

    def _start_dashboard_refresh_loop(self):
        if not getattr(self, "dashboard_active", False):
            return
        self.dashboard_refresh_controller.start()

    def _set_connection_state(self, state: str):
        self.websocket_state = state
        if self.connection_indicator is not None:
            self.connection_indicator.content = ft.Text(
                {
                    "conectado": "● Conectado",
                    "reconectando": "● Reconectando",
                    "desconectado": "● Desconectado",
                }[state],
                color={
                    "conectado": ft.Colors.GREEN,
                    "reconectando": ft.Colors.ORANGE,
                    "desconectado": ft.Colors.RED,
                }[state],
            )
            try:
                self.page.update()
            except Exception:
                pass

    def _refresh_map_markers(self):
        if not getattr(self, "map_control", None):
            return
        markers = [build_marker(state) for state in self.vehicle_states.values() if state.get("latitude") is not None and state.get("longitude") is not None]
        try:
            if hasattr(self.map_control, "set_markers"):
                self.map_control.set_markers(markers)
        except Exception:
            pass

    def _select_route_marker(self, marker):
        self.selected_marker_id = str(marker.get("id"))
        self.selected_route_id = str(marker.get("route_id")) if marker.get("route_id") is not None else None
        self.selected_route_status_filter = ""
        self.routes_view(status_filter="")

    def _clear_route_selection(self):
        self.selected_marker_id = None
        self.selected_route_id = None
        self.selected_route_status_filter = ""
        self.routes_view(status_filter="")

    def _connect_tracking_socket(self):
        if self.websocket_client is not None or websockets is None:
            return

        def runner():
            self._set_connection_state("reconectando")
            while self.user is not None:
                try:
                    async def _listen():
                        async with websockets.connect(build_tracking_ws_url()) as ws:
                            self.websocket_client = ws
                            self._set_connection_state("conectado")
                            async for raw_message in ws:
                                if not raw_message:
                                    break
                                try:
                                    data = json.loads(raw_message)
                                except Exception:
                                    continue
                                self.vehicle_states = update_vehicle_state(self.vehicle_states, data)
                                self._refresh_map_markers()

                    asyncio.run(_listen())
                except Exception:
                    self.websocket_client = None
                    if self.user is not None:
                        self._set_connection_state("reconectando")
                        time.sleep(3)
                    else:
                        break
            self.websocket_client = None
            if self.user is None:
                self._set_connection_state("desconectado")

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()

    def _disconnect_tracking_socket(self):
        self.user = None
        if self.websocket_client is not None:
            try:
                self.websocket_client.close()
            except Exception:
                pass
            self.websocket_client = None
        self._set_connection_state("desconectado")

    def notify(self, message: str, error=False):
        color = ft.Colors.RED_700 if error else ft.Colors.GREEN_700

        # debug log para terminal do flet
        try:
            print(f"[notify] message={message!r} error={error}")
        except Exception:
            pass

        if error:
            def _close(_):
                try:
                    self.page.close(dialog)
                    self.page.update()
                except Exception:
                    try:
                        dialog.open = False
                        self.page.update()
                    except Exception:
                        pass

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Erro"),
                content=ft.Text(message),
                actions=[ft.TextButton("OK", on_click=_close)],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            try:
                self.page.dialog = dialog
                self.page.open(dialog)
                self.page.update()
            except Exception:
                try:
                    self.page.dialog = dialog
                    dialog.open = True
                    self.page.update()
                except Exception:
                    pass
            return

        def _close(_):
            try:
                snack.open = False
                self.page.update()
            except Exception:
                pass

        # duração maior para testes e visibilidade
        snack = ft.SnackBar(content=ft.Text(message), bgcolor=color,
                             action=ft.TextButton("Fechar", on_click=_close), duration=5000)

        # Compatibilidade com diferentes versões do Flet
        try:
            if hasattr(self.page, "show_snack_bar"):
                # API mais nova
                self.page.show_snack_bar(snack)
                try:
                    self.page.update()
                except Exception:
                    pass
            else:
                # fallback: atribui à propriedade e abre
                self.page.snack_bar = snack
                snack.open = True
                self.page.update()
        except Exception:
            # última tentativa silenciosa
            try:
                self.page.snack_bar = snack
                snack.open = True
                self.page.update()
            except Exception:
                pass

    def show_login(self):
        email = ft.TextField(label="E-mail", value="admin@sistema.com", prefix_icon=ft.Icons.EMAIL)
        password = ft.TextField(
            label="Senha", value="123456", password=True, can_reveal_password=True,
            prefix_icon=ft.Icons.LOCK,
        )

        def submit(_):
            try:
                self.user = self.api.login(email.value.strip(), password.value)
                self.show_shell()
            except ApiError as exc:
                self.notify(str(exc), True)

        self.page.clean()
        self.page.add(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.LOCAL_SHIPPING, size=70, color=ft.Colors.INDIGO),
                        ft.Text("Gestão de Entregas", size=28, weight=ft.FontWeight.BOLD),
                        ft.Text("Acesse sua operação", color=ft.Colors.GREY_700),
                        email, password,
                        ft.FilledButton("Entrar", icon=ft.Icons.LOGIN, on_click=submit, height=48),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    tight=True,
                    spacing=18,
                ),
                width=420,
                padding=30,
                border_radius=20,
                bgcolor=ft.Colors.WHITE,
                shadow=ft.BoxShadow(blur_radius=25, color=ft.Colors.BLACK12),
            )
        )
        self.page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.page.vertical_alignment = ft.MainAxisAlignment.CENTER
        self.page.update()

    def show_shell(self):
        driver = self.user["perfil"] == "MOTORISTA"
        admin_user = self.user["perfil"] == "ADMIN"
        destinations = [
            ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD, label="Dashboard"),
            ft.NavigationRailDestination(icon=ft.Icons.LOCAL_SHIPPING, label="Gestão de Entregas"),
            ft.NavigationRailDestination(icon=ft.Icons.TRIP_ORIGIN, label="Rotas"),
        ]
        if not driver:
            destinations += [
                ft.NavigationRailDestination(icon=ft.Icons.RECEIPT_LONG, label="Pedidos"),
                ft.NavigationRailDestination(icon=ft.Icons.PEOPLE, label="Clientes"),
                ft.NavigationRailDestination(icon=ft.Icons.INVENTORY_2, label="Produtos"),
                ft.NavigationRailDestination(icon=ft.Icons.DIRECTIONS_CAR, label="Veículos"),
            ]
            if admin_user:
                destinations += [
                    ft.NavigationRailDestination(icon=ft.Icons.DOMAIN, label="Organizações"),
                ]
            destinations += [
                ft.NavigationRailDestination(icon=ft.Icons.BAR_CHART, label="Relatórios"),
                ft.NavigationRailDestination(icon=ft.Icons.MANAGE_ACCOUNTS, label="Usuários"),
            ]

        def navigate(event):
            selected_index = event.control.selected_index
            self.dashboard_active = selected_index == 0
            if self.dashboard_active:
                self._start_dashboard_refresh_loop()
            else:
                self.dashboard_refresh_controller.stop()

            # O shell do usuário seleciona ações pelo índice do menu lateral.
            actions = [self.dashboard_view, self.delivery_management_view, self.routes_view]
            if not driver:
                actions += [
                    self.orders_view,
                    self.clients_view,
                    self.products_view,
                    self.vehicles_view,
                ]
                if admin_user:
                    actions += [self.organizations_view]
                actions += [
                    self.reports_view,
                    self.users_view,
                ]
            if selected_index < len(actions):
                actions[selected_index]()
            else:
                self.notify("Tela não disponível na navegação atual.", True)

        rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            destinations=destinations,
            on_change=navigate,
        )
        self.navigation_rail = rail
        self.page.clean()
        self.page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        self.page.vertical_alignment = ft.MainAxisAlignment.START
        self.connection_indicator = ft.Container(
            content=ft.Text("● Desconectado", color=ft.Colors.RED),
            padding=12,
        )
        self.page.appbar = ft.AppBar(
            title=ft.Text("Gestão de Entregas"),
            actions=[
                self.connection_indicator,
                ft.Container(ft.Text(f'{self.user["nome"]} · {self.user["perfil"]}'), padding=12),
                ft.IconButton(ft.Icons.LOGOUT, tooltip="Sair", on_click=lambda _: self.logout()),
            ],
        )
        self._connect_tracking_socket()
        self.page.add(ft.Row([rail, ft.VerticalDivider(width=1), self.content], expand=True))
        self.dashboard_active = True
        self._start_dashboard_refresh_loop()
        self.dashboard_view()

    def logout(self):
        self.api.token = None
        self.user = None
        self.dashboard_active = False
        self.dashboard_refresh_controller.stop()
        self._disconnect_tracking_socket()
        self.page.appbar = None
        self.show_login()

    def heading(self, title, subtitle=""):
        return ft.Column([
            ft.Text(title, size=26, weight=ft.FontWeight.BOLD),
            ft.Text(subtitle, color=ft.Colors.GREY_700),
        ])

    def header_bar(self, title, subtitle="", actions=None):
        return ft.Container(
            ft.Row(
                [
                    self.heading(title, subtitle),
                    ft.Row(actions or [], tight=True, alignment=ft.MainAxisAlignment.END),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.START,
                expand=True,
            ),
            padding=20,
            width=float("inf"),
        )

    def dashboard_view(self):
        if self.user["perfil"] == "MOTORISTA":
            self.driver_dashboard_view()
            return
        try:
            data = self.dashboard_data or self.api.request("GET", "/relatorios/dashboard")
            self.dashboard_data = data
            indicator_values = get_dashboard_indicator_values(data)
            cards = []
            for (label, key), icon in zip(DASHBOARD_INDICATORS, [
                ft.Icons.CALENDAR_TODAY,
                ft.Icons.CHECK_CIRCLE,
                ft.Icons.ROUTE,
                ft.Icons.WARNING,
                ft.Icons.DIRECTIONS_RUN,
                ft.Icons.DIRECTIONS_CAR,
                ft.Icons.PERSON,
            ]):
                cards.append(ft.Container(
                    ft.Column([
                        ft.Icon(icon, color=ft.Colors.INDIGO),
                        ft.Text(str(indicator_values.get(key, 0)), size=28, weight=ft.FontWeight.BOLD),
                        ft.Text(label),
                    ]),
                    padding=18, width=220, border_radius=14, bgcolor=ft.Colors.INDIGO_50,
                ))

            def build_bar_item(label, value, max_value):
                width = 240 if max_value > 0 else 50
                bar_width = int((value / max_value) * width) if max_value > 0 else 0
                return ft.Column([
                    ft.Row([
                        ft.Text(label, size=12),
                        ft.Text(str(value), size=12, weight=ft.FontWeight.BOLD),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Container(height=14, width=width, bgcolor=ft.Colors.GREY_200, border_radius=7, padding=1,
                                 content=ft.Container(width=bar_width, bgcolor=ft.Colors.INDIGO, border_radius=7)),
                ], tight=True)

            status_items = data.get("entregas_por_status", [])
            max_status = max((item["quantidade"] for item in status_items), default=1)
            status_chart = ft.Column(
                [ft.Text("Entregas por status", weight=ft.FontWeight.BOLD)] +
                [build_bar_item(item["status"].replace("_", " ").title(), item["quantidade"], max_status)
                 for item in status_items],
                spacing=10,
            )

            driver_items = data.get("entregas_por_motorista", [])[:5]
            max_driver = max((item["quantidade"] for item in driver_items), default=1)
            driver_chart = ft.Column(
                [ft.Text("Entregas por motorista", weight=ft.FontWeight.BOLD)] +
                [build_bar_item(item["nome"], item["quantidade"], max_driver) for item in driver_items],
                spacing=10,
            )

            vehicle_items = data.get("entregas_por_veiculo", [])[:5]
            max_vehicle = max((item["quantidade"] for item in vehicle_items), default=1)
            vehicle_chart = ft.Column(
                [ft.Text("Entregas por veículo", weight=ft.FontWeight.BOLD)] +
                [build_bar_item(item["nome"], item["quantidade"], max_vehicle) for item in vehicle_items],
                spacing=10,
            )

            evolution_items = data.get("evolucao_diaria_entregas", [])
            max_evolution = max((item["quantidade"] for item in evolution_items), default=1)
            evolution_chart = ft.Column(
                [ft.Text("Evolução diária das entregas", weight=ft.FontWeight.BOLD)] +
                [build_bar_item(item["data"], item["quantidade"], max_evolution) for item in evolution_items],
                spacing=10,
            )

            latest_deliveries = [
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.LOCAL_SHIPPING),
                    title=ft.Text(f'Entrega #{item["id"]} · Pedido #{item["pedido_id"]}'),
                    subtitle=ft.Text(f'{item["status"].replace("_", " ")} · {item.get("data_entrega") or item.get("previsao_entrega") or "-"}'),
                )
                for item in data.get("ultimas_entregas", [])
            ]

            next_routes = [
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.TRIP_ORIGIN),
                    title=ft.Text(f'Rota #{item["id"]} · {item["nome"]}'),
                    subtitle=ft.Text(f'{item["status"].replace("_", " ")} · {item.get("data_planejada") or "-"}'),
                )
                for item in data.get("proximas_rotas", [])
            ]

            dashboard_markers = []
            for state in self.vehicle_states.values():
                lat = state.get("latitude")
                lng = state.get("longitude")
                if lat is None or lng is None:
                    continue
                label = state.get("title") or f"Motorista {state.get('vehicle_id')}"
                route_id = state.get("route_id")
                dashboard_markers.append({
                    "id": state.get("id"),
                    "lat": lat,
                    "lng": lng,
                    "title": label,
                    "label": f"Rota #{route_id}" if route_id else label,
                    "route_id": route_id,
                })
            self.map_control = MapView(
                markers=dashboard_markers,
                height=320,
                width=760,
                on_marker_click=self._select_route_marker,
                selected_marker_id=self.selected_marker_id,
                title="Motoristas em atividade",
            ).build()
            map_control = self.map_control

            self.content.controls = [
                self.header_bar("Dashboard", "Indicadores e monitoramento operacional"),
                ft.Container(ft.Row(cards, wrap=True, spacing=12), padding=20),
                ft.Container(ft.Row([
                    ft.Container(status_chart, expand=True, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                    ft.Container(driver_chart, expand=True, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                ], wrap=True, spacing=12), padding=20),
                ft.Container(ft.Row([
                    ft.Container(vehicle_chart, expand=True, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                    ft.Container(evolution_chart, expand=True, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                ], wrap=True, spacing=12), padding=20),
                ft.Container(
                    ft.Column([
                        ft.Text("Monitoramento de motoristas", weight=ft.FontWeight.BOLD),
                        ft.Text("Clique em um marcador para abrir a tela de Rotas e selecionar o motorista."),
                        ft.Divider(height=10),
                        map_control,
                    ]),
                    padding=20,
                    border_radius=14,
                    bgcolor=ft.Colors.WHITE,
                    shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
                ),
                ft.Container(ft.Row([
                    ft.Container(ft.Column([ft.Text("Últimas entregas", weight=ft.FontWeight.BOLD)] + (latest_deliveries or [ft.Text("Nenhuma entrega encontrada.")]), tight=True), expand=True, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                    ft.Container(ft.Column([ft.Text("Próximas rotas", weight=ft.FontWeight.BOLD)] + (next_routes or [ft.Text("Nenhuma rota agendada.")]), tight=True), expand=True, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                ], wrap=True, spacing=12), padding=20),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    # ===================================================================
    # Phase 2: Driver Dashboard
    # ===================================================================

    def driver_dashboard_view(self):
        """
        Dashboard exclusivo para motoristas.
        Exibe saudação, veículo, indicadores e próxima missão.
        """
        try:
            # Buscar rota ativa do motorista (Phase 1 endpoint)
            current_route = None
            try:
                current_route = self.api.request("GET", "/rotas/motorista/atual")
            except ApiError as exc:
                # 404 é esperado se não há rota ativa
                if "404" not in str(exc).lower():
                    raise

            # Montar componentes
            greeting_card = self._build_driver_greeting()
            vehicle_card = self._build_driver_vehicle_card(current_route)
            indicator_cards = self._build_driver_indicators(current_route)
            mission_card = self._build_driver_mission_card(current_route)

            # Atualizar view
            self.content.controls = [
                self.header_bar("Dashboard", "Sua operação de hoje"),
                greeting_card,
                vehicle_card,
                ft.Container(ft.Row(indicator_cards, wrap=True, spacing=12), padding=20),
                mission_card,
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def _get_greeting_time(self) -> tuple:
        """
        Retorna (saudação, período) baseado na hora atual.
        Ex: ("Bom dia", "⛅"), ("Boa tarde", "☀️"), ("Boa noite", "🌙")
        """
        hour = datetime.now().hour
        if hour < 12:
            return "Bom dia", "⛅"
        elif hour < 18:
            return "Boa tarde", "☀️"
        else:
            return "Boa noite", "🌙"

    def _build_driver_greeting(self) -> ft.Container:
        """
        Card de saudação com nome, data e emoticon de período.
        """
        greeting, emoji = self._get_greeting_time()
        today = datetime.now().strftime("%A, %d de %B de %Y")
        driver_name = self.user.get("nome", "Motorista")

        # Localizar nome do dia em português
        days_pt = {
            "Monday": "segunda-feira",
            "Tuesday": "terça-feira",
            "Wednesday": "quarta-feira",
            "Thursday": "quinta-feira",
            "Friday": "sexta-feira",
            "Saturday": "sábado",
            "Sunday": "domingo",
        }
        months_pt = {
            "January": "janeiro",
            "February": "fevereiro",
            "March": "março",
            "April": "abril",
            "May": "maio",
            "June": "junho",
            "July": "julho",
            "August": "agosto",
            "September": "setembro",
            "October": "outubro",
            "November": "novembro",
            "December": "dezembro",
        }
        now = datetime.now()
        day_name = days_pt.get(now.strftime("%A"), now.strftime("%A"))
        month_name = months_pt.get(now.strftime("%B"), now.strftime("%B"))
        today_pt = f"{day_name.capitalize()}, {now.day} de {month_name} de {now.year}"

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text(f"{greeting}, {driver_name}!", size=24, weight=ft.FontWeight.BOLD),
                        ft.Text(today_pt, size=14, color=ft.Colors.GREY_700),
                    ], spacing=4),
                    ft.Text(emoji, size=32),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START),
            ]),
            padding=20,
            border_radius=14,
            bgcolor=ft.Colors.INDIGO_50,
        )

    def _build_driver_vehicle_card(self, current_route) -> ft.Container:
        """
        Card com informações do veículo vinculado à rota ativa.
        Se não há rota ativa, mostra placeholder.
        """
        vehicle_info = "--"
        if current_route and current_route.get("veiculo"):
            veiculo = current_route["veiculo"]
            placa = veiculo.get("placa", "--")
            modelo = veiculo.get("modelo", "--")
            vehicle_info = f"{modelo} ({placa})"

        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.DIRECTIONS_CAR, size=28, color=ft.Colors.INDIGO),
                ft.Column([
                    ft.Text("Veículo", size=12, color=ft.Colors.GREY_700),
                    ft.Text(vehicle_info, size=14, weight=ft.FontWeight.BOLD),
                ], spacing=2),
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=16,
            margin=ft.margin.symmetric(horizontal=20, vertical=10),
            border_radius=12,
            bgcolor=ft.Colors.WHITE,
            border=ft.border.all(1, ft.Colors.GREY_300),
        )

    def _build_driver_indicators(self, current_route) -> list:
        """
        Retorna lista com 4 cards de indicadores:
        1. Entregas concluídas hoje
        2. Entregas pendentes
        3. Distância prevista (da rota atual)
        4. Tempo previsto (da rota atual)
        
        Se dados não disponíveis, usa fallback "--".
        """
        indicators = [
            {"label": "Concluídas hoje", "value": "--", "icon": ft.Icons.CHECK_CIRCLE, "color": ft.Colors.GREEN},
            {"label": "Pendentes", "value": "--", "icon": ft.Icons.PENDING_ACTIONS, "color": ft.Colors.ORANGE},
            {"label": "Distância", "value": "--", "icon": ft.Icons.ROUTE, "color": ft.Colors.BLUE},
            {"label": "Tempo", "value": "--", "icon": ft.Icons.SCHEDULE, "color": ft.Colors.PURPLE},
        ]

        # Extrair valores da rota se disponível
        if current_route:
            # Distância e duração da rota atual
            distance = current_route.get("distancia_km")
            duration = current_route.get("duracao_minutos")

            if distance is not None:
                indicators[2]["value"] = f"{distance:.1f} km"
            if duration is not None:
                hours = duration // 60
                minutes = duration % 60
                if hours > 0:
                    indicators[3]["value"] = f"{hours}h {minutes}m"
                else:
                    indicators[3]["value"] = f"{minutes}m"

            # Contar entregas concluídas e pendentes
            entregas = current_route.get("entregas", [])
            if entregas:
                completed = sum(1 for e in entregas if e.get("status") == "ENTREGUE")
                pending = len(entregas) - completed
                indicators[0]["value"] = str(completed)
                indicators[1]["value"] = str(pending)

        # Montar cards
        cards = []
        for ind in indicators:
            card = ft.Container(
                content=ft.Column([
                    ft.Icon(ind["icon"], size=24, color=ind["color"]),
                    ft.Text(str(ind["value"]), size=20, weight=ft.FontWeight.BOLD),
                    ft.Text(ind["label"], size=12, color=ft.Colors.GREY_700),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
                padding=16,
                width=160,
                border_radius=12,
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1, ft.Colors.GREY_300),
            )
            cards.append(card)

        return cards

    def _build_driver_mission_card(self, current_route) -> ft.Container:
        """
        Card principal "Próxima Missão" com dados da rota ativa.
        Contém botão "Iniciar Rota" com navegação placeholder para Phase 3.
        
        Estrutura pronta para receber em Phase 3:
        - Mapa da rota
        - Sequência de carregamento
        - Navegação turn-by-turn
        - Atualização de status
        """
        def handle_start_route(_):
            """
            Placeholder para Phase 3: Rota Ativa.
            Aqui será implementada navegação para driver_route_view().
            """
            if not current_route:
                self.notify("Nenhuma rota ativa para iniciar.", True)
                return

            # Phase 3: Descomentar e implementar navegação
            # self.driver_route_view(current_route["id"])
            self.notify("Phase 3 - Rota Ativa (em desenvolvimento)", False)

        if not current_route:
            # Rota não disponível
            mission_content = ft.Column([
                ft.Icon(ft.Icons.TRIP_ORIGIN, size=48, color=ft.Colors.GREY_400),
                ft.Text("Nenhuma rota ativa", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("Aguarde até que uma rota seja atribuída a você.", color=ft.Colors.GREY_700),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)
        else:
            # Rota ativa disponível
            route_id = current_route.get("id", "--")
            route_name = current_route.get("nome", "--")
            status = current_route.get("status", "--").replace("_", " ")
            
            # Organização (ponto de coleta)
            org_name = "--"
            if current_route.get("organizacao"):
                org_name = current_route["organizacao"].get("nome", "--")
            
            # Entregas
            entregas = current_route.get("entregas", [])
            num_entregas = len(entregas)
            
            # Próxima entrega pendente
            proxima_entrega_text = "Nenhuma entrega pendente"
            for entrega in entregas:
                if entrega.get("status") not in {"ENTREGUE", "CANCELADA"}:
                    # Extrair informações
                    endereco = entrega.get("endereco_destino_id", "--")
                    proxima_entrega_text = f"Entrega #{entrega.get('id', '--')}"
                    break
            
            # Distância e duração
            distance = current_route.get("distancia_km", "--")
            duration = current_route.get("duracao_minutos", "--")
            if duration != "--":
                hours = int(duration) // 60
                minutes = int(duration) % 60
                duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            else:
                duration = "--"

            mission_content = ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text("Operação", size=12, color=ft.Colors.GREY_700),
                        ft.Text(org_name, size=16, weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Text(f"{num_entregas} entrega(s)", weight=ft.FontWeight.BOLD),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Divider(height=10),
                ft.Column([
                    ft.Text("Próxima entrega", size=12, color=ft.Colors.GREY_700),
                    ft.Text(proxima_entrega_text, size=14, weight=ft.FontWeight.BOLD),
                ], spacing=2),
                ft.Row([
                    ft.Column([
                        ft.Text("Distância", size=12, color=ft.Colors.GREY_700),
                        ft.Text(f"{distance} km" if distance != "--" else "--", weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Column([
                        ft.Text("Duração", size=12, color=ft.Colors.GREY_700),
                        ft.Text(duration, weight=ft.FontWeight.BOLD),
                    ]),
                    ft.Column([
                        ft.Text("Status", size=12, color=ft.Colors.GREY_700),
                        ft.Text(status, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO),
                    ]),
                ], spacing=20),
                ft.Divider(height=10),
                ft.Row([
                    ft.FilledButton(
                        "Iniciar Rota",
                        icon=ft.Icons.PLAY_ARROW,
                        on_click=handle_start_route,
                        expand=True,
                    ),
                ]),
            ], spacing=12)

        return ft.Container(
            content=mission_content,
            padding=20,
            margin=ft.margin.symmetric(horizontal=20, vertical=10),
            border_radius=14,
            bgcolor=ft.Colors.WHITE,
            shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
        )

    # ===================================================================
    # Phase 3: Driver Route View (Placeholder)
    # ===================================================================
    # def driver_route_view(self, route_id: int):
    #     """
    #     Tela de rota ativa para o motorista.
    #     
    #     Será implementada na Phase 3 com:
    #     - Mapa interativo com rota e marcadores
    #     - Sequência de carregamento/entrega
    #     - Turn-by-turn navigation
    #     - Botões para pausar/retomar/finalizar rota
    #     - Atualização de status de entregas
    #     - Notificações de próximas paradas
    #     """
    #     pass

    def deliveries_view(self, offset=0, status_filter=""):
        page_size = 10
        try:
            if self.user["perfil"] == "MOTORISTA":
                path = "/entregas/minhas"
            else:
                params = [f"limit={page_size}", f"offset={offset}"]
                if status_filter:
                    params.append(f"status={status_filter}")
                path = "/entregas?" + "&".join(params)
            deliveries = self.api.request("GET", path)
            if self.user["perfil"] == "MOTORISTA" and status_filter:
                deliveries = [item for item in deliveries if item["status"] == status_filter]
            status_dropdown = ft.Dropdown(
                label="Status",
                value=status_filter or None,
                options=[self.option(value) for value in [
                    "AGUARDANDO_COLETA", "COLETADA", "EM_ROTA",
                    "ENTREGUE", "NAO_ENTREGUE", "CANCELADA",
                ]],
            )
            rows = []
            for item in deliveries:
                status = item["status"]
                actions = []
                if self.user["perfil"] in ("ADMIN", "GESTOR", "MOTORISTA"):
                    actions.append(ft.PopupMenuButton(
                        icon=ft.Icons.EDIT,
                        tooltip="Atualizar status",
                        items=[
                            ft.PopupMenuItem(
                                content=ft.Text(value.replace("_", " ").title()),
                                on_click=lambda _, delivery_id=item["id"], new_status=value:
                                    self.update_status(delivery_id, new_status),
                            )
                            for value in ["AGUARDANDO_COLETA", "COLETADA", "EM_ROTA",
                                          "NAO_ENTREGUE", "CANCELADA"]
                        ],
                    ))
                    actions.append(ft.IconButton(
                        ft.Icons.EDIT_NOTE, tooltip="Editar entrega",
                        on_click=lambda _, delivery=item: self.delivery_dialog(delivery),
                    ))
                    if self.user["perfil"] != "MOTORISTA":
                        actions.append(ft.IconButton(
                            ft.Icons.DELETE, tooltip="Excluir entrega",
                            icon_color=ft.Colors.RED_700,
                            on_click=lambda _, delivery=item: self.confirm_delete_delivery(delivery),
                        ))
                    actions.append(ft.IconButton(
                        ft.Icons.DONE_ALL, tooltip="Comprovar e concluir",
                        on_click=lambda _, delivery_id=item["id"]: self.receipt_dialog(delivery_id),
                    ))
                    actions.append(ft.IconButton(
                        ft.Icons.REPORT_PROBLEM, tooltip="Ocorrências",
                        on_click=lambda _, delivery=item: self.incidents_dialog(delivery),
                    ))
                    actions.append(ft.IconButton(
                        ft.Icons.HISTORY, tooltip="Histórico",
                        on_click=lambda _, delivery=item: self.delivery_history_dialog(delivery),
                    ))
                rows.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.LOCAL_SHIPPING, color=STATUS_COLORS.get(status)),
                    title=ft.Text(f'Entrega #{item["id"]} · Pedido #{item["pedido_id"]}'),
                    subtitle=ft.Text(
                        f'{status.replace("_", " ")} · Previsão: {item["previsao_entrega"] or "não informada"}'
                    ),
                    trailing=ft.Row(actions, tight=True),
                ))
            self.content.controls = [
                self.header_bar("Entregas", f"{len(deliveries)} registro(s)", [
                    ft.FilledButton("Nova entrega", icon=ft.Icons.ADD,
                                    visible=self.user["perfil"] != "MOTORISTA",
                                    on_click=lambda _: self.delivery_dialog()),
                    self.page_controls(
                        lambda _: self.deliveries_view(max(0, offset - page_size), status_filter),
                        lambda _: self.deliveries_view(offset + page_size, status_filter),
                        can_previous=offset > 0,
                        can_next=len(deliveries) == page_size and self.user["perfil"] != "MOTORISTA",
                    ),
                ]),
                ft.Container(ft.Row([
                    status_dropdown,
                    ft.IconButton(
                        ft.Icons.SEARCH,
                        tooltip="Filtrar",
                        on_click=lambda _: self.deliveries_view(0, status_dropdown.value or ""),
                    ),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.deliveries_view()),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhuma entrega encontrada.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def routes_view(self, offset=0, status_filter=""):
        page_size = 10
        try:
            params = [f"limit={page_size}", f"offset={offset}"]
            if status_filter:
                params.append(f"status={status_filter}")
            routes = self.api.request("GET", "/rotas?" + "&".join(params))
            status_dropdown = ft.Dropdown(
                label="Status",
                value=status_filter or None,
                options=[self.option(value) for value in self.route_status_options()],
            )
            rows = []
            if self.user["perfil"] == "MOTORISTA":
                for item in routes:
                    rows.append(self._driver_route_panel(item))
            else:
                for item in routes:
                    status = item["status"]
                    actions = [
                        ft.IconButton(
                            ft.Icons.INFO,
                            tooltip="Detalhes da rota",
                            on_click=lambda _, rota=item: self.route_details_dialog(rota),
                        ),
                        ft.IconButton(
                            ft.Icons.PLAY_ARROW,
                            tooltip="Iniciar rota",
                            visible=self.user["perfil"] != "MOTORISTA",
                            disabled=status in {"EM_EXECUCAO", "FINALIZADA", "CANCELADA"},
                            on_click=lambda _, rota=item: self.change_route_status(rota, "EM_EXECUCAO"),
                        ),
                        ft.IconButton(
                            ft.Icons.PAUSE,
                            tooltip="Pausar rota",
                            visible=self.user["perfil"] != "MOTORISTA",
                            disabled=status != "EM_EXECUCAO",
                            on_click=lambda _, rota=item: self.change_route_status(rota, "PAUSADA", event="PAUSA", observation="Pausada pela interface"),
                        ),
                        ft.IconButton(
                            ft.Icons.PLAY_ARROW,
                            tooltip="Retomar rota",
                            visible=self.user["perfil"] != "MOTORISTA",
                            disabled=status != "PAUSADA",
                            on_click=lambda _, rota=item: self.change_route_status(rota, "EM_EXECUCAO", event="RETOMADA", observation="Retomada pela interface"),
                        ),
                        ft.IconButton(
                            ft.Icons.DONE,
                            tooltip="Concluir rota",
                            visible=self.user["perfil"] != "MOTORISTA",
                            disabled=status not in {"EM_EXECUCAO", "PAUSADA", "PRONTA"},
                            on_click=lambda _, rota=item: self.change_route_status(rota, "FINALIZADA"),
                        ),
                        ft.IconButton(
                            ft.Icons.CANCEL,
                            tooltip="Cancelar rota",
                            visible=self.user["perfil"] != "MOTORISTA",
                            disabled=status in {"FINALIZADA", "CANCELADA"},
                            on_click=lambda _, rota=item: self.change_route_status(rota, "CANCELADA"),
                        ),
                    ]
                    rows.append(ft.ListTile(
                        leading=ft.Icon(ft.Icons.TRIP_ORIGIN, color=ft.Colors.PURPLE),
                        title=ft.Text(f'{item["nome"]} · {status.replace("_", " ")}'),
                        subtitle=ft.Text(
                            f'Veículo: {item["veiculo_id"] or "-"} · Motorista: {item["motorista_id"] or "-"} '
                            f'· Entregas: {len(item.get("entregas") or [])} · Progresso: {item.get("progresso_percentual") or 0}%'
                        ),
                        trailing=ft.Row(actions, tight=True),
                    ))
            self.content.controls = [
                self.header_bar("Rotas", f"{len(routes)} rota(s)", [
                    self.page_controls(
                        lambda _: self.routes_view(max(0, offset - page_size), status_filter),
                        lambda _: self.routes_view(offset + page_size, status_filter),
                        can_previous=offset > 0,
                        can_next=len(routes) == page_size,
                    ),
                ]),
                ft.Container(ft.Row([
                    status_dropdown,
                    ft.IconButton(
                        ft.Icons.SEARCH,
                        tooltip="Filtrar",
                        on_click=lambda _: self.routes_view(0, status_dropdown.value or ""),
                    ),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.routes_view()),
                    ft.FilledButton("Mostrar todos", on_click=lambda _: self._clear_route_selection(), visible=bool(self.selected_marker_id or self.selected_route_id)),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhuma rota encontrada.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def route_status_options(self):
        return [
            "PLANEJADA", "AGUARDANDO_MOTORISTA", "AGUARDANDO_VEICULO",
            "PRONTA", "EM_EXECUCAO", "PAUSADA", "FINALIZADA", "CANCELADA",
        ]

    def _sorted_route_entries(self, route):
        entries = list(route.get("entregas") or [])
        return sorted(entries, key=lambda item: (
            int(item.get("sequencia_otimizada") or item.get("ordem_visita") or 0),
            int(item.get("entrega_id") or item.get("id") or 0),
        ))

    def _driver_route_snapshot(self, route):
        snapshot = []
        for entry in self._sorted_route_entries(route):
            delivery_id = entry.get("entrega_id")
            if delivery_id is None:
                continue
            try:
                delivery = self.api.request("GET", f"/entregas/{delivery_id}")
                pedido = self.api.request("GET", f"/pedidos/{delivery['pedido_id']}")
                cliente = self.api.request("GET", f"/clientes/{pedido['cliente_id']}")
                addresses = self.api.request("GET", f"/clientes/{pedido['cliente_id']}/enderecos")
                address = next((item for item in addresses if item["id"] == delivery["endereco_destino_id"]), None)
                snapshot.append({
                    "entry": entry,
                    "delivery": delivery,
                    "cliente": cliente,
                    "address": address,
                    "order": int(entry.get("sequencia_otimizada") or entry.get("ordem_visita") or 0),
                })
            except ApiError:
                continue
        return snapshot

    def _next_driver_stop(self, route):
        for stop in self._driver_route_snapshot(route):
            if stop["delivery"]["status"] not in {"ENTREGUE", "CANCELADA"}:
                return stop
        return None

    def _driver_route_panel(self, route):
        route_progress = int(route.get("progresso_percentual") or 0)
        next_stop = self._next_driver_stop(route)
        stops = self._driver_route_snapshot(route)
        has_pending = any(stop["delivery"]["status"] not in {"ENTREGUE", "CANCELADA"} for stop in stops)
        next_stop_text = "-"
        next_stop_address = "-"
        if next_stop:
            next_stop_text = f"{next_stop['cliente'].get('nome')}"
            next_stop_address = next_stop['address']['logradouro'] if next_stop['address'] else "Endereço não informado"
            if next_stop['address']:
                next_stop_address = (
                    f"{next_stop['address'].get('logradouro', '')}, {next_stop['address'].get('numero', '')} - "
                    f"{next_stop['address'].get('bairro', '')}, {next_stop['address'].get('cidade', '')}"
                ).strip(', ')

        def start_execution(_):
            self.change_route_status(route, "EM_EXECUCAO", event="PARTIDA", observation="Execução iniciada pelo motorista", progress=max(route_progress, 5))

        def pause_execution(_):
            self.change_route_status(route, "PAUSADA", event="PAUSA", observation="Rota pausada pelo motorista", progress=route_progress)

        def resume_execution(_):
            self.change_route_status(route, "EM_EXECUCAO", event="RETOMADA", observation="Rota retomada pelo motorista", progress=route_progress)

        def finish_current_delivery(_):
            if not next_stop:
                self.notify("Nenhuma entrega pendente para concluir.", True)
                return
            delivery_id = next_stop["delivery"]["id"]
            try:
                self.api.request(
                    "POST",
                    f"/entregas/{delivery_id}/comprovante",
                    json={
                        "nome_recebedor": next_stop["cliente"].get("nome", "Recebedor"),
                        "documento_recebedor": f"DOC-{delivery_id}",
                        "observacao": "Entrega confirmada na execução da rota",
                    },
                )
                self.api.request(
                    "PATCH",
                    f"/entregas/{delivery_id}/status",
                    json={"status": "ENTREGUE", "observacao": "Entrega concluída pela execução da rota"},
                )
                completed = sum(1 for stop in stops if stop["delivery"]["status"] == "ENTREGUE") + 1
                total = len(stops) or 1
                new_progress = min(100, int((completed / total) * 100))
                if completed >= total:
                    self.change_route_status(route, "FINALIZADA", progress=100, event="FINALIZADA", observation="Todas as entregas concluídas")
                else:
                    self.change_route_status(route, "EM_EXECUCAO", progress=new_progress, event="ENTREGA_REALIZADA", observation=f"Entrega {delivery_id} concluída")
                self.notify("Entrega concluída e rota atualizada.")
            except ApiError as exc:
                self.notify(str(exc), True)

        action_buttons = []
        if self.user["perfil"] == "MOTORISTA":
            if route.get("status") in {"PLANEJADA", "PRONTA", "AGUARDANDO_MOTORISTA", "AGUARDANDO_VEICULO"}:
                action_buttons.append(ft.FilledButton("Iniciar execução", icon=ft.Icons.PLAY_ARROW, on_click=start_execution))
            elif route.get("status") == "EM_EXECUCAO":
                action_buttons.append(ft.FilledButton("Pausar rota", icon=ft.Icons.PAUSE, on_click=pause_execution))
            elif route.get("status") == "PAUSADA":
                action_buttons.append(ft.FilledButton("Retomar rota", icon=ft.Icons.PLAY_ARROW, on_click=resume_execution))
            if has_pending:
                action_buttons.append(ft.FilledButton("Concluir entrega atual", icon=ft.Icons.DONE, on_click=finish_current_delivery))
            if not has_pending and route.get("status") not in {"FINALIZADA", "CANCELADA"}:
                action_buttons.append(ft.FilledButton("Finalizar rota", icon=ft.Icons.FLAG, on_click=lambda _: self.change_route_status(route, "FINALIZADA", progress=100, event="FINALIZADA", observation="Rota finalizada pelo motorista")))

        stop_rows = []
        for stop in stops:
            delivery = stop["delivery"]
            stop_rows.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.LOCATION_ON, color=ft.Colors.INDIGO if delivery["status"] != "ENTREGUE" else ft.Colors.GREEN),
                    title=ft.Text(f"{stop['order']}. {stop['cliente'].get('nome')}") ,
                    subtitle=ft.Text(f"{stop['address'] and (stop['address'].get('logradouro') or '') or 'Endereço não informado'} · {delivery['status'].replace('_', ' ').title()}"),
                    trailing=ft.Text(f"#{delivery['id']}"),
                )
            )

        return ft.Container(
            content=ft.Column([
                ft.Text(f"Rota: {route['nome']}", size=22, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text(f"Veículo: {route.get('veiculo_id') or '-'}"),
                    ft.Text(f"Status: {route['status'].replace('_', ' ')}"),
                ], wrap=True),
                ft.Row([
                    ft.Text(f"Progresso: {route_progress}%"),
                    ft.Text(f"Entregas: {len(stops)}"),
                ], wrap=True),
                ft.ProgressBar(value=min(max(route_progress / 100, 0), 1), bar_height=10),
                ft.Divider(),
                ft.Text("Próxima parada", weight=ft.FontWeight.BOLD),
                ft.Text(next_stop_text),
                ft.Text(f"Endereço: {next_stop_address}", color=ft.Colors.GREY_700),
                ft.Divider(),
                ft.Row(action_buttons, wrap=True),
                ft.Divider(),
                ft.Text("Entregas da rota", weight=ft.FontWeight.BOLD),
                *stop_rows,
            ], tight=True, spacing=10),
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.WHITE,
            shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
        )

    def change_route_status(self, route, new_status, progress=None, event=None, observation=None):
        try:
            payload = {"status": new_status}
            if new_status == "EM_EXECUCAO":
                payload.update({"evento": event or "PARTIDA", "observacao": observation or "Iniciada pela interface"})
            elif new_status == "PAUSADA":
                payload.update({"evento": event or "PAUSA", "observacao": observation or "Pausada pela interface"})
            elif new_status == "FINALIZADA":
                payload.update({"evento": event or "FINALIZADA", "observacao": observation or "Concluída pela interface"})
            elif new_status == "CANCELADA":
                payload.update({"evento": event or "FINALIZADA", "observacao": observation or "Cancelada pela interface"})
            if progress is not None:
                payload["progresso_percentual"] = max(0, min(100, int(progress)))
            self.api.request("PATCH", f"/rotas/{route['id']}/status", json=payload)
            self.notify("Status da rota atualizado.")
            self.routes_view()
        except ApiError as exc:
            self.notify(str(exc), True)

    def delivery_management_view(self):
        try:
            orders = self.api.request("GET", "/pedidos?limit=100&offset=0")
            organizations = self.api.request("GET", "/organizacoes?limit=100&offset=0")
            vehicles = self.api.request("GET", "/veiculos?limit=100&offset=0")
            users = self.api.request("GET", "/usuarios?limit=100&offset=0")
        except ApiError as exc:
            self.notify(str(exc), True)
            return

        available_orders = [item for item in orders if item.get("status") not in {"CANCELADO", "FINALIZADO"}]
        selected_order_ids = self.delivery_management_selection.get("pedido_ids", [])

        order_checkboxes = []
        for order in available_orders:
            address_label = "Endereço não cadastrado"
            cliente_nome = "Cliente"
            try:
                if order.get("cliente_id") is not None:
                    client = self.api.request("GET", f"/clientes/{order['cliente_id']}")
                    cliente_nome = client.get("nome") or "Cliente"
                    addresses = self.api.request("GET", f"/clientes/{order['cliente_id']}/enderecos")
                    address = next((item for item in addresses if item["id"] == order.get("endereco_entrega_id")), None)
                    if address:
                        address_label = f"{address.get('logradouro', '')}, {address.get('numero', '')} - {address.get('bairro', '')}, {address.get('cidade', '')}"
            except Exception:
                pass
            priority_label = ""
            priority = order.get("prioridade") or order.get("priority")
            if priority:
                priority_label = f" · Prioridade: {priority}"
            status_label = f" · Status: {order.get('status') or '-'}"
            order_checkboxes.append(
                ft.Checkbox(
                    label=f"Pedido #{order['id']} — {order.get('numero_pedido') or '-'} — {cliente_nome} — {address_label}{status_label}{priority_label}",
                    value=(order['id'] in selected_order_ids),
                    on_change=lambda e, order_id=order["id"]: self._toggle_delivery_order(order_id, e.control.value),
                )
            )

        selected_orders = [order for order in available_orders if order["id"] in selected_order_ids]
        selected_order_org_ids = {order.get("organizacao_id") for order in selected_orders if order.get("organizacao_id") is not None}
        detected_org_id = None
        detected_org = None
        if len(selected_order_org_ids) == 1:
            detected_org_id = next(iter(selected_order_org_ids))
            detected_org = next((org for org in organizations if org["id"] == detected_org_id), None)

        driver_options = [self.option(str(item["id"]), item["nome"]) for item in users if item.get("perfil") == "MOTORISTA" and item.get("ativo")]
        vehicle_options = [self.option(str(item["id"]), f"{item.get('placa')} · {item.get('modelo')}") for item in vehicles if item.get("ativo")]
        driver_dropdown = ft.Dropdown(label="Motorista", options=driver_options, value=None)
        vehicle_dropdown = ft.Dropdown(label="Veículo", options=vehicle_options, value=None)

        def generate(_):
            pedido_ids = self.delivery_management_selection.get("pedido_ids") or []
            if not pedido_ids:
                self.notify("Selecione ao menos um pedido para gerar a rota.", True)
                return

            org_ids = []
            for pedido_id in pedido_ids:
                order = next((item for item in orders if item["id"] == pedido_id), None)
                if not order:
                    self.notify(f"Pedido {pedido_id} não encontrado.", True)
                    return
                if order.get("organizacao_id") is None:
                    self.notify(f"Pedido #{pedido_id} está sem organização vinculada. Vincule o pedido antes de gerar a rota.", True)
                    return
                if order.get("endereco_entrega_id") is None:
                    self.notify(f"Pedido #{pedido_id} precisa de endereço de entrega válido antes de entrar em rota.", True)
                    return
                org_ids.append(order["organizacao_id"])

            unique_org_ids = set(org_ids)
            if len(unique_org_ids) != 1:
                self.notify("Os pedidos selecionados pertencem a pontos de coleta diferentes. Gere uma rota para cada organização.", True)
                return

            org_id = next(iter(unique_org_ids))
            organization = next((item for item in organizations if item["id"] == org_id), None)
            if organization is None:
                self.notify("Organização detectada não foi encontrada.", True)
                return
            if organization.get("endereco_id") is None:
                self.notify("A organização selecionada não possui um endereço principal geocodificado.", True)
                return
            principal_endpoint = self.api.request("GET", f"/organizacoes/{org_id}/enderecos")
            principal_address = next((item for item in principal_endpoint if item["id"] == organization["endereco_id"]), None)
            if principal_address is None or principal_address.get("latitude") is None or principal_address.get("longitude") is None:
                self.notify("A organização selecionada não possui um endereço principal geocodificado.", True)
                return

            payload = {
                "nome": f"Rota gerada {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')}",
                "descricao": "Rota gerada a partir da Gestão de Entregas",
                "organizacao_id": int(org_id),
                "pedido_ids": pedido_ids,
                "motorista_id": int(driver_dropdown.value) if driver_dropdown.value else None,
                "veiculo_id": int(vehicle_dropdown.value) if vehicle_dropdown.value else None,
                "status": "OTIMIZANDO",
            }
            try:
                generated = self.api.request("POST", "/rotas/gerar", json=payload)
                self.generated_route = self.api.request("GET", f"/rotas/{generated['id']}")
                self.notify("Rota gerada com sucesso.")
                self.delivery_management_view()
            except ApiError as exc:
                self.notify(str(exc), True)

        route_details = []
        if self.generated_route:
            route = self.generated_route
            route_details = [
                ft.Text(route.get("nome") or "Rota gerada", weight=ft.FontWeight.BOLD, size=20),
                ft.Text(f"ID da rota: {route.get('id') or '-'}"),
                ft.Text(f"Status: {route.get('status', '-').replace('_', ' ')}"),
                ft.Text(f"Quantidade de entregas: {len(route.get('entregas') or [])}"),
                ft.Text(f"Distância prevista: {route.get('distancia_prevista') or '-'} km"),
                ft.Text(f"Duração prevista: {route.get('duracao_prevista') or '-'} h"),
                ft.Text(f"Progresso: {route.get('progresso_percentual') or 0}%"),
                ft.Text(f"Organização: {route.get('organizacao_id') or '-'}"),
                ft.Text(f"Origem: {route.get('origem_endereco_id') or '-'}"),
                ft.Text(f"Motorista: {route.get('motorista_id') or '-'}"),
                ft.Text(f"Veículo: {route.get('veiculo_id') or '-'}"),
                ft.Text(f"Observações: {route.get('observacoes') or '-'}"),
                ft.Divider(),
                ft.FilledButton("Ver rotas", on_click=lambda _: self.routes_view()),
            ]
        else:
            route_details = [
                ft.Text("Resumo da rota", weight=ft.FontWeight.BOLD, size=20),
                ft.Text("Nenhuma rota gerada ainda."),
            ]

        origin_summary = "-"
        if detected_org is not None:
            try:
                org_addresses = self.api.request("GET", f"/organizacoes/{detected_org['id']}/enderecos")
                principal_address = next((item for item in org_addresses if item["id"] == detected_org.get("endereco_id")), None)
                if principal_address:
                    origin_summary = (
                        f"{principal_address.get('logradouro', '')}, {principal_address.get('numero', '')} - "
                        f"{principal_address.get('bairro', '')}, {principal_address.get('cidade', '')}/{principal_address.get('estado', '')}"
                    )
            except Exception:
                origin_summary = "-"

        summary_panel = ft.Column([
            ft.Text("Resumo da seleção", weight=ft.FontWeight.BOLD, size=20),
            ft.Text(f"Pedidos selecionados: {len(selected_orders)}"),
            *[ft.Text(f"• Pedido #{order['id']} — {order.get('numero_pedido') or '-'}") for order in selected_orders],
            ft.Divider(),
            ft.Text("Ponto de coleta detectado", weight=ft.FontWeight.BOLD),
            ft.Text(f"Organização: {detected_org.get('nome') if detected_org else 'Nenhuma organização detectada.'}"),
            ft.Text(f"Origem: {origin_summary}"),
            ft.Text(f"Pedidos: {len(selected_orders)}"),
            ft.Divider(),
            ft.Text("Use este formulário para gerar rotas otimizadas via POST /rotas/gerar."),
        ], spacing=8, tight=True)

        self.content.controls = [
            self.header_bar("Gestão de Entregas", "Crie rotas otimizadas a partir dos pedidos disponíveis"),
            ft.Container(
                ft.Row([
                    ft.Column([
                        ft.Text("Pedidos disponíveis", weight=ft.FontWeight.BOLD, size=18),
                        ft.Container(
                            ft.Column(order_checkboxes or [ft.Text("Nenhum pedido disponível.")], spacing=6, scroll=ft.ScrollMode.AUTO),
                            padding=12,
                            border_radius=14,
                            bgcolor=ft.Colors.WHITE,
                            shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
                            height=420,
                            width=520,
                        ),
                        ft.Row([
                            ft.FilledButton("Selecionar todos", on_click=lambda _: self._select_all_orders(available_orders)),
                            ft.FilledButton("Limpar seleção", on_click=lambda _: self._clear_selected_orders()),
                        ], spacing=12),
                        ft.Divider(),
                        ft.Text("Atribuição opcional", weight=ft.FontWeight.BOLD, size=18),
                        ft.Row([driver_dropdown, vehicle_dropdown], spacing=12),
                        ft.Divider(),
                        ft.FilledButton("Gerar Rota Otimizada", icon=ft.Icons.ROUTE, on_click=generate, disabled=not bool(selected_order_ids)),
                        ft.Text(
                            "Selecione ao menos um pedido para habilitar a geração de rota." if not selected_order_ids else "",
                            color=ft.Colors.ORANGE_700,
                        ),
                    ], spacing=12),
                    ft.Container(summary_panel, width=420),
                ], expand=True, spacing=20),
                padding=20,
            ),
            ft.Container(
                ft.Column(route_details, spacing=8),
                padding=20,
                border_radius=14,
                bgcolor=ft.Colors.WHITE,
                shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
            ),
        ]
        self.page.update()

    def _select_all_orders(self, available_orders):
        self.delivery_management_selection["pedido_ids"] = [order["id"] for order in available_orders]
        self.delivery_management_view()

    def _clear_selected_orders(self):
        self.delivery_management_selection["pedido_ids"] = []
        self.delivery_management_view()

    def route_details_dialog(self, route):
        progress = int(route.get("progresso_percentual") or 0)
        content = ft.Column([
            ft.Text(f'Nome: {route["nome"]}'),
            ft.Text(f'Descrição: {route.get("descricao") or "-"}'),
            ft.Text(f'Status: {route["status"].replace("_", " ")}'),
            ft.Text(f'Veículo: {route.get("veiculo_id") or "-"}'),
            ft.Text(f'Motorista: {route.get("motorista_id") or "-"}'),
            ft.Text(f'Organização: {route.get("organizacao_id")}'),
            ft.Text(f'Entregas: {len(route.get("entregas") or [])}'),
            ft.Text(f'Data planejada: {route.get("data_planejada") or "-"}'),
            ft.Text(f'Progresso: {progress}%'),
            ft.ProgressBar(value=min(max(progress / 100, 0), 1), bar_height=8),
        ], tight=True)
        dialog = ft.AlertDialog(
            title=ft.Text(f'Rota #{route["id"]}'),
            content=content,
            actions=[
                ft.TextButton("Fechar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Iniciar", visible=self.user["perfil"] != "MOTORISTA" and route.get("status") not in {"EM_EXECUCAO", "FINALIZADA", "CANCELADA"}, on_click=lambda _: (self.close_dialog(dialog), self.change_route_status(route, "EM_EXECUCAO"))),
                ft.FilledButton("Pausar", visible=self.user["perfil"] != "MOTORISTA" and route.get("status") == "EM_EXECUCAO", on_click=lambda _: (self.close_dialog(dialog), self.change_route_status(route, "PAUSADA", event="PAUSA", observation="Pausada pela interface"))),
                ft.FilledButton("Retomar", visible=self.user["perfil"] != "MOTORISTA" and route.get("status") == "PAUSADA", on_click=lambda _: (self.close_dialog(dialog), self.change_route_status(route, "EM_EXECUCAO", event="RETOMADA", observation="Retomada pela interface"))),
                ft.FilledButton("Concluir", visible=self.user["perfil"] != "MOTORISTA", on_click=lambda _: (self.close_dialog(dialog), self.change_route_status(route, "FINALIZADA"))),
                ft.FilledButton("Cancelar", visible=self.user["perfil"] != "MOTORISTA", on_click=lambda _: (self.close_dialog(dialog), self.change_route_status(route, "CANCELADA"))),
            ],
        )
        self.open_dialog(dialog)

    def vehicles_view(self, search="", offset=0):
        page_size = 10
        try:
            params = [f"limit={page_size}", f"offset={offset}"]
            if search.strip():
                params.append(f"busca={quote(search.strip())}")
            path = "/veiculos?" + "&".join(params)
            vehicles = self.api.request("GET", path)
            search_field = ft.TextField(
                label="Buscar veículo",
                value=search,
                prefix_icon=ft.Icons.SEARCH,
                on_submit=lambda event: self.vehicles_view(event.control.value),
            )
            rows = []
            for item in vehicles:
                actions = []
                if self.user["perfil"] in ("ADMIN", "GESTOR"):
                    actions.extend([
                        ft.IconButton(
                            ft.Icons.EDIT,
                            tooltip="Editar veículo",
                            on_click=lambda _, vehicle=item: self.vehicle_dialog(vehicle),
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE,
                            tooltip="Excluir veículo",
                            icon_color=ft.Colors.RED_700,
                            on_click=lambda _, vehicle=item: self.confirm_delete_vehicle(vehicle),
                        ),
                    ])
                rows.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.DIRECTIONS_CAR, color=STATUS_COLORS.get(item["status"], ft.Colors.GREY)),
                    title=ft.Text(f'{item["placa"]} · {item["status"].replace("_", " ")}'),
                    subtitle=ft.Text(
                        f'{item["tipo"]} · {item["marca"]} {item["modelo"]} · {item["ano"]} · {item["cor"]} · '
                        f'{item["capacidade_carga"]} kg · {item["capacidade_volume"]} m³ · '
                        f'{"Ativo" if item["ativo"] else "Inativo"}'
                    ),
                    trailing=ft.Row(actions, tight=True),
                ))
            self.content.controls = [
                self.header_bar("Veículos", f"{len(vehicles)} veículo(s)", [
                    ft.FilledButton("Novo veículo", icon=ft.Icons.ADD,
                                    visible=self.user["perfil"] != "MOTORISTA",
                                    on_click=lambda _: self.vehicle_dialog()),
                    self.page_controls(
                        lambda _: self.vehicles_view(max(0, offset - page_size), search),
                        lambda _: self.vehicles_view(offset + page_size, search),
                        can_previous=offset > 0,
                        can_next=len(vehicles) == page_size,
                    ),
                ]),
                ft.Container(ft.Row([
                    search_field,
                    ft.IconButton(ft.Icons.SEARCH, tooltip="Buscar", on_click=lambda _: self.vehicles_view(search_field.value, 0)),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.vehicles_view()),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhum veículo encontrado.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def vehicle_dialog(self, vehicle=None):
        try:
            users = self.api.request("GET", "/usuarios?limit=100&offset=0")
            organizations = self.api.request("GET", "/organizacoes?limit=100&offset=0") if self.user["perfil"] == "ADMIN" else []
        except ApiError as exc:
            self.notify(str(exc), True)
            return

        error_message = ft.Text("", color=ft.Colors.RED_700)
        license_plate = ft.TextField(label="Placa", value=(vehicle or {}).get("placa", ""))
        model = ft.TextField(label="Modelo", value=(vehicle or {}).get("modelo", ""))
        brand = ft.TextField(label="Marca", value=(vehicle or {}).get("marca", ""))
        year = ft.TextField(label="Ano", value=str((vehicle or {}).get("ano", "")))
        color = ft.TextField(label="Cor", value=(vehicle or {}).get("cor", ""))
        capacity_weight = ft.TextField(label="Capacidade de carga (kg)", value=str((vehicle or {}).get("capacidade_carga") or "0"))
        capacity_volume = ft.TextField(label="Capacidade de volume (m³)", value=str((vehicle or {}).get("capacidade_volume") or "0"))
        type_field = ft.Dropdown(
            label="Tipo",
            value=(vehicle or {}).get("tipo", "CARRO"),
            options=[self.option(value) for value in ["CARRO", "VAN", "UTILITARIO", "CAMINHAO", "CARRETA", "OUTRO"]],
        )
        status_field = ft.Dropdown(
            label="Status",
            value=(vehicle or {}).get("status", "DISPONIVEL"),
            options=[self.option(value) for value in ["DISPONIVEL", "EM_ROTTA", "MANUTENCAO"]],
        )
        mileage = ft.TextField(label="Quilometragem", value=str((vehicle or {}).get("quilometragem") or "0"))
        active = ft.Checkbox(label="Ativo", value=(vehicle or {}).get("ativo", True))
        driver = ft.Dropdown(
            label="Motorista",
            value=str((vehicle or {}).get("motorista_id")) if (vehicle or {}).get("motorista_id") else None,
            options=[self.option(item["id"], item["nome"]) for item in users if item["perfil"] == "MOTORISTA" and item["ativo"]],
        )
        organization = ft.Dropdown(
            label="Organização",
            value=str((vehicle or {}).get("organizacao_id")) if (vehicle or {}).get("organizacao_id") else None,
            options=[self.option(item["id"], item["nome"]) for item in organizations],
            visible=self.user["perfil"] == "ADMIN",
        )

        def save(_):
            fields_to_validate = [license_plate, model, brand, year, color, capacity_weight, capacity_volume, mileage]
            if self.user["perfil"] == "ADMIN":
                fields_to_validate.append(organization)
            self.clear_errors(*fields_to_validate, driver)
            errors = []
            valid = all([
                self.require_text(license_plate, "Informe a placa do veículo.", 5),
                self.require_text(model, "Informe o modelo.", 2),
                self.require_text(brand, "Informe a marca.", 2),
                self.require_text(year, "Informe o ano.", 4),
                self.require_text(color, "Informe a cor.", 2),
                self.validate_positive_number(capacity_weight, "Informe a carga maior ou igual a zero."),
                self.validate_positive_number(capacity_volume, "Informe o volume maior ou igual a zero."),
                self.validate_positive_number(mileage, "Informe uma quilometragem maior ou igual a zero.", allow_zero=True),
            ])
            if not self.require_text(license_plate, "Informe a placa do veículo.", 5):
                errors.append("Placa: informe a placa do veículo.")
            if not self.require_text(model, "Informe o modelo.", 2):
                errors.append("Modelo: informe o modelo.")
            if not self.require_text(brand, "Informe a marca.", 2):
                errors.append("Marca: informe a marca.")
            if not self.require_text(year, "Informe o ano.", 4):
                errors.append("Ano: informe o ano.")
            if not self.require_text(color, "Informe a cor.", 2):
                errors.append("Cor: informe a cor.")
            if not self.validate_positive_number(capacity_weight, "Informe a carga maior ou igual a zero."):
                errors.append("Capacidade de carga: informe um valor maior ou igual a zero.")
            if not self.validate_positive_number(capacity_volume, "Informe o volume maior ou igual a zero."):
                errors.append("Capacidade de volume: informe um valor maior ou igual a zero.")
            if not self.validate_positive_number(mileage, "Informe uma quilometragem maior ou igual a zero.", allow_zero=True):
                errors.append("Quilometragem: informe um valor maior ou igual a zero.")
            if self.user["perfil"] == "ADMIN" and organization.visible and not organization.value:
                self.set_error(organization, "Selecione a organização.")
                errors.append("Organização: selecione a organização.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            try:
                payload = {
                    "placa": license_plate.value.strip(),
                    "modelo": model.value.strip(),
                    "marca": brand.value.strip(),
                    "ano": int(year.value),
                    "cor": color.value.strip(),
                    "capacidade_carga": self.money(capacity_weight.value),
                    "capacidade_volume": self.money(capacity_volume.value),
                    "tipo": type_field.value,
                    "status": status_field.value,
                    "quilometragem": int(mileage.value),
                    "ativo": active.value,
                    "motorista_id": int(driver.value) if driver.value else None,
                }
                if self.user["perfil"] == "ADMIN":
                    payload["organizacao_id"] = int(organization.value) if organization.value else None
                if vehicle:
                    self.api.request("PUT", f'/veiculos/{vehicle["id"]}', json=payload)
                    message = "Veículo atualizado."
                else:
                    self.api.request("POST", "/veiculos", json=payload)
                    message = "Veículo cadastrado."
                self.close_dialog(dialog)
                self.notify(message)
                self.vehicles_view()
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return
            except ValueError:
                self.notify("Informe valores numéricos válidos para ano, carga, volume e quilometragem.", True)

        dialog = ft.AlertDialog(
            title=ft.Text("Editar veículo" if vehicle else "Novo veículo"),
            content=ft.Column([
                error_message,
                license_plate, model, brand, year, color,
                capacity_weight, capacity_volume, type_field, status_field, mileage,
                driver, organization if self.user["perfil"] == "ADMIN" else ft.Row(),
                active,
            ], tight=True, width=440, height=420, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        self.open_dialog(dialog)

    def confirm_delete_vehicle(self, vehicle):
        def delete(_):
            try:
                self.api.request("DELETE", f'/veiculos/{vehicle["id"]}')
                self.close_dialog(dialog)
                self.notify("Veículo excluído.")
                self.vehicles_view()
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir veículo"),
            content=ft.Text(f'Deseja excluir o veículo {vehicle["placa"]} ({vehicle["modelo"]})?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def update_status(self, delivery_id, status):
        try:
            self.api.request("PATCH", f"/entregas/{delivery_id}/status",
                             json={"status": status, "observacao": "Atualizado pelo aplicativo"})
            self.notify("Status atualizado.")
            self.deliveries_view()
        except ApiError as exc:
            self.notify(str(exc), True)

    def confirm_delete_delivery(self, delivery):
        def delete(_):
            try:
                self.api.request("DELETE", f'/entregas/{delivery["id"]}')
                self.close_dialog(dialog)
                self.notify("Entrega excluída.")
                self.deliveries_view()
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir entrega"),
            content=ft.Text(f'Deseja excluir a entrega #{delivery["id"]}?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def delivery_dialog(self, delivery=None):
        try:
            orders = self.api.request("GET", "/pedidos")
            users = self.api.request("GET", "/usuarios")
            clients = self.api.request("GET", "/clientes")
            addresses = []
            for client in clients:
                for address in self.api.request("GET", f'/clientes/{client["id"]}/enderecos'):
                    label = f'{client["nome"]} - {address["logradouro"]}, {address["numero"]} ({address["tipo"]})'
                    addresses.append({"id": address["id"], "label": label})
        except ApiError as exc:
            self.notify(str(exc), True)
            return
        error_message = ft.Text("", color=ft.Colors.RED_700)

        order = ft.Dropdown(
            label="Pedido",
            value=str(delivery["pedido_id"]) if delivery else None,
            options=[self.option(item["id"], item["numero_pedido"]) for item in orders if item["status"] != "CANCELADO"],
        )
        driver = ft.Dropdown(
            label="Motorista",
            value=str(delivery["entregador_id"]) if delivery and delivery["entregador_id"] else None,
            options=[self.option(item["id"], item["nome"]) for item in users if item["perfil"] == "MOTORISTA" and item["ativo"]],
        )
        origin = ft.Dropdown(
            label="Endereço de origem",
            value=str(delivery["endereco_origem_id"]) if delivery else None,
            options=[self.option(item["id"], item["label"]) for item in addresses],
        )
        destination = ft.Dropdown(
            label="Endereço de destino",
            value=str(delivery["endereco_destino_id"]) if delivery else None,
            options=[self.option(item["id"], item["label"]) for item in addresses],
        )
        due = ft.TextField(
            label="Previsão de entrega",
            value=(delivery or {}).get("previsao_entrega") or "",
            hint_text="YYYY-MM-DDTHH:MM:SS",
        )
        notes = ft.TextField(label="Observações", value=(delivery or {}).get("observacoes") or "", multiline=True)

        def save(_):
            self.clear_errors(order, origin, destination, due)
            errors = []
            valid = True
            if not self.require_dropdown(order, "Selecione o pedido."):
                errors.append("Pedido: selecione um pedido.")
                valid = False
            if not self.require_dropdown(origin, "Selecione o endereço de origem."):
                errors.append("Origem: selecione um endereço de origem.")
                valid = False
            if not self.require_dropdown(destination, "Selecione o endereço de destino."):
                errors.append("Destino: selecione um endereço de destino.")
                valid = False
            if origin.value and destination.value and origin.value == destination.value:
                self.set_error(destination, "Origem e destino devem ser diferentes.")
                errors.append("Destino: origem e destino devem ser diferentes.")
                valid = False
            if due.value.strip():
                try:
                    datetime.fromisoformat(due.value.strip())
                except ValueError:
                    self.set_error(due, "Use o formato YYYY-MM-DDTHH:MM:SS.")
                    errors.append("Previsão: use o formato YYYY-MM-DDTHH:MM:SS.")
                    valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            payload = {
                "pedido_id": int(order.value),
                "entregador_id": int(driver.value) if driver.value else None,
                "endereco_origem_id": int(origin.value),
                "endereco_destino_id": int(destination.value),
                "previsao_entrega": due.value.strip() or None,
                "observacoes": notes.value.strip() or None,
            }
            try:
                if delivery:
                    self.api.request("PUT", f'/entregas/{delivery["id"]}', json=payload)
                    message = "Entrega atualizada."
                else:
                    self.api.request("POST", "/entregas", json=payload)
                    message = "Entrega cadastrada."
                self.close_dialog(dialog)
                self.notify(message)
                self.deliveries_view()
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Editar entrega" if delivery else "Nova entrega"),
            content=ft.Column([error_message, order, driver, origin, destination, due, notes], tight=True, width=460, height=420, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        self.open_dialog(dialog)

    def receipt_dialog(self, delivery_id):
        receipt = None
        try:
            receipt = self.api.request("GET", f"/entregas/{delivery_id}/comprovante")
        except ApiError:
            receipt = None
        error_message = ft.Text("", color=ft.Colors.RED_700)
        name = ft.TextField(label="Nome do recebedor", value=(receipt or {}).get("nome_recebedor", ""))
        document = ft.TextField(label="Documento", value=(receipt or {}).get("documento_recebedor", ""))
        note = ft.TextField(label="Observação", value=(receipt or {}).get("observacao") or "", multiline=True)

        def save(_):
            self.clear_errors(name, document)
            errors = []
            valid = True
            if not self.require_text(name, "Informe pelo menos 2 caracteres.", 2):
                errors.append("Nome do recebedor: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(document, "Informe pelo menos 3 caracteres.", 3):
                errors.append("Documento: informe pelo menos 3 caracteres.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            try:
                payload = {
                    "nome_recebedor": name.value, "documento_recebedor": document.value,
                    "observacao": note.value,
                }
                if receipt:
                    self.api.request("PUT", f"/entregas/{delivery_id}/comprovante", json=payload)
                    message = "Comprovante atualizado."
                else:
                    self.api.request("POST", f"/entregas/{delivery_id}/comprovante", json=payload)
                    self.api.request("PATCH", f"/entregas/{delivery_id}/status",
                                     json={"status": "ENTREGUE", "observacao": "Entrega confirmada"})
                    message = "Entrega concluída com comprovante."
                self.close_dialog(dialog)
                self.notify(message)
                self.deliveries_view()
            except ApiError as exc:
                # mantém diálogo aberto com os valores e exibe feedback inline
                error_message.value = str(exc)
                self.page.update()
                return

        def delete(_):
            try:
                self.api.request("DELETE", f"/entregas/{delivery_id}/comprovante")
                self.close_dialog(dialog)
                self.notify("Comprovante excluído.")
                self.deliveries_view()
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        actions = [ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog))]
        if receipt:
            actions.append(ft.TextButton("Excluir", on_click=delete))
        actions.append(ft.FilledButton("Salvar", on_click=save))
        dialog = ft.AlertDialog(
            title=ft.Text("Editar comprovante" if receipt else "Comprovante de entrega"),
            content=ft.Column([error_message, name, document, note], tight=True, width=360, height=360, scroll=ft.ScrollMode.AUTO),
            actions=actions,
        )
        self.open_dialog(dialog)

    def delivery_history_dialog(self, delivery):
        try:
            history = self.api.request("GET", f'/entregas/{delivery["id"]}/historico')
        except ApiError as exc:
            self.notify(str(exc), True)
            return
        rows = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.HISTORY),
                title=ft.Text(f'{item["status_anterior"] or "CRIADA"} -> {item["status_novo"]}'),
                subtitle=ft.Text(item.get("observacao") or "Sem observação"),
            )
            for item in history
        ]
        dialog = ft.AlertDialog(
            title=ft.Text(f'Histórico da entrega #{delivery["id"]}'),
            content=ft.Column(rows or [ft.Text("Nenhum histórico encontrado.")], tight=True, width=520),
            actions=[ft.TextButton("Fechar", on_click=lambda _: self.close_dialog(dialog))],
        )
        self.open_dialog(dialog)

    def incidents_dialog(self, delivery):
        try:
            incidents = self.api.request("GET", f'/entregas/{delivery["id"]}/ocorrencias')
        except ApiError as exc:
            self.notify(str(exc), True)
            return
        rows = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.REPORT_PROBLEM),
                title=ft.Text(item["tipo"]),
                subtitle=ft.Text(item["descricao"]),
                trailing=ft.Row([
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="Editar ocorrência",
                        on_click=lambda _, incident=item: self.incident_dialog(delivery, incident, dialog),
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE,
                        tooltip="Excluir ocorrência",
                        icon_color=ft.Colors.RED_700,
                        on_click=lambda _, incident=item: self.delete_incident(delivery, incident, dialog),
                    ),
                ], tight=True),
            )
            for item in incidents
        ]
        dialog = ft.AlertDialog(
            title=ft.Text(f'Ocorrências da entrega #{delivery["id"]}'),
            content=ft.Column(rows or [ft.Text("Nenhuma ocorrência registrada.")], tight=True, width=560),
            actions=[
                ft.TextButton("Fechar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Nova ocorrência", icon=ft.Icons.ADD,
                                on_click=lambda _: self.incident_dialog(delivery, parent_dialog=dialog)),
            ],
        )
        self.open_dialog(dialog)

    def incident_dialog(self, delivery, incident=None, parent_dialog=None):
        error_message = ft.Text("", color=ft.Colors.RED_700)
        kind = ft.TextField(label="Tipo", value=(incident or {}).get("tipo", ""))
        description = ft.TextField(label="Descrição", value=(incident or {}).get("descricao", ""), multiline=True)

        def save(_):
            self.clear_errors(kind, description)
            payload = {"tipo": kind.value.strip(), "descricao": description.value.strip()}
            errors = []
            valid = True
            if not self.require_text(kind, "Informe pelo menos 2 caracteres.", 2):
                errors.append("Tipo: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(description, "Informe pelo menos 5 caracteres.", 5):
                errors.append("Descrição: informe pelo menos 5 caracteres.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            try:
                if incident:
                    self.api.request(
                        "PUT",
                        f'/entregas/{delivery["id"]}/ocorrencias/{incident["id"]}',
                        json=payload,
                    )
                    message = "Ocorrência atualizada."
                else:
                    self.api.request("POST", f'/entregas/{delivery["id"]}/ocorrencias', json=payload)
                    message = "Ocorrência registrada."
                self.close_dialog(dialog)
                if parent_dialog:
                    parent_dialog.open = False
                self.notify(message)
                self.incidents_dialog(delivery)
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Editar ocorrência" if incident else "Nova ocorrência"),
            content=ft.Column([error_message, kind, description], tight=True, width=420),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        self.open_dialog(dialog)

    def delete_incident(self, delivery, incident, parent_dialog):
        try:
            self.api.request("DELETE", f'/entregas/{delivery["id"]}/ocorrencias/{incident["id"]}')
            parent_dialog.open = False
            self.notify("Ocorrência excluída.")
            self.incidents_dialog(delivery)
        except ApiError as exc:
            # mantém diálogo pai aberto e notifica o erro
            self.page.update()
            self.notify(str(exc), True)
            return

    def close_dialog(self, dialog, update=True):
        self.page.close(dialog)
        if update:
            self.page.update()

    def open_dialog(self, dialog):
        self.page.open(dialog)
        self.page.update()

    def show_error_dialog(self, message, title="Atenção"):
        dialog = ft.AlertDialog(
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[ft.TextButton("Fechar", on_click=lambda _: self.close_dialog(dialog))],
        )
        self.open_dialog(dialog)

    def option(self, value, text=None):
        return ft.DropdownOption(key=str(value), text=text or str(value))

    def money(self, value):
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return 0

    def only_digits(self, value):
        return "".join(char for char in str(value or "") if char.isdigit())

    def format_document(self, value):
        digits = self.only_digits(value)
        if len(digits) == 11:
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
        if len(digits) == 14:
            return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
        return value or ""

    def format_phone(self, value):
        digits = self.only_digits(value)
        if len(digits) == 10:
            return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
        if len(digits) == 11:
            return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
        return value or ""

    def format_zip_code(self, value):
        digits = self.only_digits(value)
        if len(digits) == 8:
            return f"{digits[:5]}-{digits[5:]}"
        return value or ""

    def page_controls(self, previous_action, next_action, can_previous=True, can_next=True):
        return ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, tooltip="Anterior", disabled=not can_previous, on_click=previous_action),
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, tooltip="Próxima", disabled=not can_next, on_click=next_action),
        ], tight=True)

    def clear_errors(self, *fields):
        for field in fields:
            if hasattr(field, "error"):
                field.error = None
            if hasattr(field, "error_text"):
                field.error_text = None

    def set_error(self, field, message):
        if hasattr(field, "error"):
            field.error = message
        elif hasattr(field, "error_text"):
            field.error_text = message

    def require_text(self, field, message, min_length=1):
        if len((field.value or "").strip()) < min_length:
            self.set_error(field, message)
            return False
        return True

    def require_dropdown(self, field, message):
        if not field.value:
            self.set_error(field, message)
            return False
        return True

    def validate_email_field(self, field, required=True):
        value = (field.value or "").strip()
        if not value and not required:
            return True
        if "@" not in value or "." not in value.split("@")[-1]:
            self.set_error(field, "Informe um e-mail válido.")
            return False
        return True

    def validate_positive_number(self, field, message, allow_zero=True):
        try:
            value = float(str(field.value or "").replace(",", "."))
        except ValueError:
            self.set_error(field, message)
            return False
        if value < 0 or (not allow_zero and value == 0):
            self.set_error(field, message)
            return False
        return True

    def clients_view(self, search="", offset=0):
        page_size = 10
        try:
            params = [f"limit={page_size}", f"offset={offset}"]
            if search.strip():
                params.append(f"busca={quote(search.strip())}")
            path = "/clientes?" + "&".join(params)
            clients = self.api.request("GET", path)
            search_field = ft.TextField(
                label="Buscar cliente",
                value=search,
                prefix_icon=ft.Icons.SEARCH,
                on_submit=lambda event: self.clients_view(event.control.value),
            )
            rows = []
            for item in clients:
                status = "Ativo" if item["ativo"] else "Inativo"
                contact = self.format_phone(item.get("telefone")) or item.get("email") or "Sem contato"
                document = self.format_document(item.get("cpf_cnpj"))
                subtitle = f"{contact} · {status}"
                if document:
                    subtitle = f"{document} · {subtitle}"
                actions = [
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="Editar cliente",
                        on_click=lambda _, client=item: self.client_dialog(client),
                    ),
                    ft.IconButton(
                        ft.Icons.HOME,
                        tooltip="Endereços",
                        on_click=lambda _, client=item: self.addresses_dialog(client),
                    ),
                ]
                if self.user["perfil"] == "ADMIN":
                    actions += [
                        ft.IconButton(
                            ft.Icons.TOGGLE_ON if item["ativo"] else ft.Icons.TOGGLE_OFF,
                            tooltip="Desativar cliente" if item["ativo"] else "Ativar cliente",
                            on_click=lambda _, client=item: self.set_client_status(
                                client["id"], not client["ativo"]
                            ),
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE,
                            tooltip="Excluir cliente",
                            icon_color=ft.Colors.RED_700,
                            on_click=lambda _, client=item: self.confirm_delete_client(client),
                        ),
                    ]
                rows.append(ft.ListTile(
                    leading=ft.CircleAvatar(content=ft.Text(item["nome"][0].upper())),
                    title=ft.Text(item["nome"]),
                    subtitle=ft.Text(subtitle),
                    trailing=ft.Row(actions, tight=True),
                ))
            self.content.controls = [
                self.header_bar("Clientes", f"{len(clients)} cliente(s)", [
                    ft.FilledButton("Novo cliente", icon=ft.Icons.ADD,
                                    on_click=lambda _: self.client_dialog()),
                ]),
                ft.Container(ft.Row([
                    search_field,
                    ft.IconButton(ft.Icons.SEARCH, tooltip="Buscar", on_click=lambda _: self.clients_view(search_field.value, 0)),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.clients_view()),
                    self.page_controls(
                        lambda _: self.clients_view(search, max(0, offset - page_size)),
                        lambda _: self.clients_view(search, offset + page_size),
                        can_previous=offset > 0,
                        can_next=len(clients) == page_size,
                    ),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhum cliente encontrado.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def organizations_view(self, search="", offset=0):
        page_size = 10
        try:
            params = [f"limit={page_size}", f"offset={offset}"]
            if search.strip():
                params.append(f"busca={quote(search.strip())}")
            path = "/organizacoes?" + "&".join(params)
            organizations = self.api.request("GET", path)
            search_field = ft.TextField(
                label="Buscar organização",
                value=search,
                prefix_icon=ft.Icons.SEARCH,
                on_submit=lambda event: self.organizations_view(event.control.value),
            )
            rows = []
            for item in organizations:
                status = "Ativa" if item["ativo"] else "Inativa"
                subtitle = f'{item["cnpj"]} · {item["email"]} · {status}'
                actions = [
                    ft.IconButton(
                        ft.Icons.HOME,
                        tooltip="Endereços",
                        on_click=lambda _, org=item: self.organization_addresses_dialog(org),
                    ),
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="Editar organização",
                        on_click=lambda _, org=item: self.organization_dialog(org),
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE,
                        tooltip="Excluir organização",
                        icon_color=ft.Colors.RED_700,
                        on_click=lambda _, org=item: self.confirm_delete_organization(org),
                    ),
                ]
                rows.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.DOMAIN),
                    title=ft.Text(item["nome"]),
                    subtitle=ft.Text(subtitle),
                    trailing=ft.Row(actions, tight=True),
                ))
            self.content.controls = [
                self.header_bar("Organizações", f"{len(organizations)} organização(ões)", [
                    ft.FilledButton("Nova organização", icon=ft.Icons.ADD,
                                    on_click=lambda _: self.organization_dialog()),
                ]),
                ft.Container(ft.Row([
                    search_field,
                    ft.IconButton(ft.Icons.SEARCH, tooltip="Buscar", on_click=lambda _: self.organizations_view(search_field.value, 0)),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.organizations_view()),
                    self.page_controls(
                        lambda _: self.organizations_view(search, max(0, offset - page_size)),
                        lambda _: self.organizations_view(search, offset + page_size),
                        can_previous=offset > 0,
                        can_next=len(organizations) == page_size,
                    ),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhuma organização encontrada.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def organization_dialog(self, organization=None):
        error_message = ft.Text("", color=ft.Colors.RED_700)
        name = ft.TextField(label="Nome", value=(organization or {}).get("nome", ""))
        cnpj = ft.TextField(label="CNPJ", value=(organization or {}).get("cnpj") or "")
        email = ft.TextField(label="E-mail", value=(organization or {}).get("email") or "")
        phone = ft.TextField(label="Telefone", value=(organization or {}).get("telefone") or "")
        active = ft.Checkbox(label="Ativo", value=(organization or {}).get("ativo", True))

        def validate():
            errors = []
            valid = True
            self.clear_errors(name, cnpj, email)
            if len(name.value.strip()) < 2:
                self.set_error(name, "Informe pelo menos 2 caracteres.")
                errors.append("Nome: informe pelo menos 2 caracteres.")
                valid = False
            cnpj_digits = self.only_digits(cnpj.value)
            if len(cnpj_digits) != 14:
                self.set_error(cnpj, "CNPJ deve ter 14 dígitos.")
                errors.append("CNPJ: informe 14 dígitos.")
                valid = False
            if not self.validate_email_field(email):
                errors.append("E-mail: informe um e-mail válido.")
                valid = False
            self.page.update()
            return valid, errors

        def save(_):
            valid, errors = validate()
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            payload = {
                "nome": name.value.strip(),
                "cnpj": self.only_digits(cnpj.value),
                "email": email.value.strip(),
                "telefone": self.only_digits(phone.value) or None,
                "endereco": (organization or {}).get("endereco") or "",
                "ativo": active.value,
            }
            try:
                if organization:
                    self.api.request("PUT", f'/organizacoes/{organization["id"]}', json=payload)
                    message = "Organização atualizada."
                else:
                    self.api.request("POST", "/organizacoes", json=payload)
                    message = "Organização cadastrada."
                self.close_dialog(dialog)
                self.notify(message)
                self.organizations_view()
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Editar organização" if organization else "Nova organização"),
            content=ft.Column([error_message, name, cnpj, email, phone, active], tight=True, width=420, height=360, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        self.open_dialog(dialog)

    def confirm_delete_organization(self, organization):
        def delete(_):
            try:
                self.api.request("DELETE", f'/organizacoes/{organization["id"]}')
                dialog.open = False
                self.notify("Organização excluída.")
                self.organizations_view()
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir organização"),
            content=ft.Text(f'Deseja excluir "{organization["nome"]}"?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def client_dialog(self, client=None):
        error_message = ft.Text("", color=ft.Colors.RED_700)
        name = ft.TextField(label="Nome", value=(client or {}).get("nome", ""))
        document = ft.TextField(label="CPF/CNPJ", value=(client or {}).get("cpf_cnpj") or "")
        email = ft.TextField(label="E-mail", value=(client or {}).get("email") or "")
        phone = ft.TextField(label="Telefone", value=(client or {}).get("telefone") or "")
        notes = ft.TextField(
            label="Observações",
            value=(client or {}).get("observacoes") or "",
            multiline=True,
        )

        def validate():
            errors = []
            valid = True
            self.clear_errors(name, document, email, phone)

            if len(name.value.strip()) < 2:
                self.set_error(name, "Informe pelo menos 2 caracteres.")
                errors.append("Nome: informe pelo menos 2 caracteres.")
                valid = False

            document_digits = self.only_digits(document.value)
            if document.value.strip() and len(document_digits) not in (11, 14):
                self.set_error(document, "Use 11 dígitos para CPF ou 14 para CNPJ.")
                errors.append("CPF/CNPJ: use 11 dígitos para CPF ou 14 para CNPJ.")
                valid = False

            email_value = email.value.strip()
            if email_value and ("@" not in email_value or "." not in email_value.split("@")[-1]):
                self.set_error(email, "Informe um e-mail válido.")
                errors.append("E-mail: informe um e-mail válido.")
                valid = False

            phone_digits = self.only_digits(phone.value)
            if phone.value.strip() and not 10 <= len(phone_digits) <= 11:
                self.set_error(phone, "Use DDD + número, com 10 ou 11 dígitos.")
                errors.append("Telefone: use DDD + número, com 10 ou 11 dígitos.")
                valid = False

            self.page.update()
            return valid, errors

        def save(_):
            valid, errors = validate()
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            payload = {
                "nome": name.value.strip(),
                "cpf_cnpj": self.only_digits(document.value) or None,
                "email": email.value.strip() or None,
                "telefone": self.only_digits(phone.value) or None,
                "observacoes": notes.value.strip() or None,
            }
            try:
                if client:
                    self.api.request("PUT", f'/clientes/{client["id"]}', json=payload)
                    message = "Cliente atualizado."
                else:
                    self.api.request("POST", "/clientes", json=payload)
                    message = "Cliente cadastrado."
                dialog.open = False
                self.notify(message)
                self.clients_view()
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Editar cliente" if client else "Novo cliente"),
            content=ft.Column([error_message, name, document, email, phone, notes], tight=True, width=360, height=420, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        self.open_dialog(dialog)

    def addresses_dialog(self, client, on_return=None):
        """
        Diálogo de gerenciamento de endereços do cliente.
        
        Args:
            client: Dicionário do cliente
            on_return: Callback chamado ao fechar (não fecha pedido/pai)
        """
        try:
            addresses = self.api.request("GET", f'/clientes/{client["id"]}/enderecos')
        except ApiError as exc:
            self.notify(str(exc), True)
            return

        rows = []
        for item in addresses:
            # Mostrar endereço formatado sem o campo tipo
            rows.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.HOME),
                title=ft.Text(f'{item["logradouro"]}, {item["numero"]}'),
                subtitle=ft.Text(f'{item["bairro"]} · {item["cidade"]}/{item["estado"]}'),
                trailing=ft.Row([
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="Editar endereço",
                        on_click=lambda _, address=item: self.address_dialog(client, dialog, on_return, address),
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE,
                        tooltip="Excluir endereço",
                        icon_color=ft.Colors.RED_700,
                        on_click=lambda _, address=item: self.confirm_delete_address(client, address, dialog, on_return),
                    ),
                ], tight=True),
            ))

        def on_close(_):
            self.close_dialog(dialog)
            if on_return:
                on_return()

        dialog = ft.AlertDialog(
            title=ft.Text(f'Endereços - {client["nome"]}'),
            content=ft.Column(rows or [ft.Text("Nenhum endereço cadastrado.")], tight=True, width=520),
            actions=[
                ft.TextButton("Fechar", on_click=on_close),
                ft.FilledButton("Novo endereço", icon=ft.Icons.ADD,
                                on_click=lambda _: self.address_dialog(client, dialog, on_return)),
            ],
        )
        self.open_dialog(dialog)

    def organization_addresses_dialog(self, organization, on_return=None):
        try:
            addresses = self.api.request("GET", f'/organizacoes/{organization["id"]}/enderecos')
        except ApiError as exc:
            self.notify(str(exc), True)
            return

        rows = []
        for item in addresses:
            principal_badge = " ★ Principal" if item.get("principal") else ""
            rows.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.STAR if item.get("principal") else ft.Icons.HOME),
                title=ft.Text(f'{item["logradouro"]}, {item["numero"]}{principal_badge}', weight=ft.FontWeight.BOLD if item.get("principal") else None),
                subtitle=ft.Text(f'{item["bairro"]} · {item["cidade"]}/{item["estado"]}'),
                trailing=ft.Row([
                    ft.IconButton(
                        ft.Icons.EDIT,
                        tooltip="Editar endereço",
                        on_click=lambda _, address=item: self.organization_address_dialog(organization, dialog, on_return, address),
                    ),
                    ft.IconButton(
                        ft.Icons.DELETE,
                        tooltip="Excluir endereço",
                        icon_color=ft.Colors.RED_700,
                        on_click=lambda _, address=item: self.confirm_delete_organization_address(organization, address, dialog, on_return),
                    ),
                ], tight=True),
            ))

        def on_close(_):
            self.close_dialog(dialog)
            if on_return:
                on_return()

        dialog = ft.AlertDialog(
            title=ft.Text(f'Endereços - {organization["nome"]}'),
            content=ft.Column(rows or [ft.Text("Nenhum endereço cadastrado.")], tight=True, width=520),
            actions=[
                ft.TextButton("Fechar", on_click=on_close),
                ft.FilledButton("Novo endereço", icon=ft.Icons.ADD,
                                on_click=lambda _: self.organization_address_dialog(organization, dialog, on_return)),
            ],
        )
        self.open_dialog(dialog)

    def organization_address_dialog(self, organization, parent_dialog=None, on_return=None, address=None):
        error_message = ft.Text("", color=ft.Colors.RED_700)
        info_message = ft.Text("", color=ft.Colors.BLUE_700)

        try:
            existing_addresses = self.api.request("GET", f'/organizacoes/{organization["id"]}/enderecos') if address is None else []
        except ApiError:
            existing_addresses = []

        zip_code = ft.TextField(
            label="CEP",
            value=(address or {}).get("cep", ""),
            helper_text="Informe para auto-preenchimento",
            on_change=lambda _: self.clear_errors(zip_code),
        )
        street = ft.TextField(label="Logradouro", value=(address or {}).get("logradouro", ""), read_only=(address is not None))
        number = ft.TextField(label="Número", value=(address or {}).get("numero", ""))
        complement = ft.TextField(label="Complemento", value=(address or {}).get("complemento") or "")
        district = ft.TextField(label="Bairro", value=(address or {}).get("bairro", ""), read_only=(address is not None))
        city = ft.TextField(label="Cidade", value=(address or {}).get("cidade", ""), read_only=(address is not None))
        state = ft.TextField(label="UF", value=(address or {}).get("estado", "SC"), read_only=(address is not None))
        default_principal = (address or {}).get("principal", False) or (address is None and not existing_addresses)
        principal_checkbox = ft.Checkbox(
            label="Marcar como endereço principal",
            value=default_principal,
        )
        geocoded_address_text = ft.Text("", color=ft.Colors.GREEN_700, size=12)
        geocoded_coords = ft.Text("", color=ft.Colors.GREEN_700, size=10)

        def lookup_cep_auto(_=None):
            cep_value = self.only_digits(zip_code.value)
            if len(cep_value) != 8:
                return
            if address is not None:
                return
            self.clear_errors(zip_code, street, district, city, state)
            info_message.value = "Consultando CEP..."
            self.page.update()
            try:
                result = self.api.request("GET", f'/organizacoes/{organization["id"]}/enderecos/lookup-cep/{cep_value}')
                if result.get("success"):
                    street.value = result.get("logradouro", "")
                    district.value = result.get("bairro", "")
                    city.value = result.get("cidade", "")
                    state.value = result.get("estado", "").upper()
                    info_message.value = "CEP preenchido com sucesso!"
                else:
                    self.set_error(zip_code, result.get("error", "CEP não encontrado"))
                    info_message.value = ""
            except ApiError as exc:
                self.set_error(zip_code, str(exc))
                info_message.value = ""
            self.page.update()

        def geocodify(_=None):
            self.clear_errors(number, street, district, city, state, zip_code)
            errors = []
            valid = True
            if not self.require_text(street, "Informe o logradouro.", 2):
                errors.append("Logradouro: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(number, "Informe o número.", 1):
                errors.append("Número: informe o número.")
                valid = False
            if not self.require_text(district, "Informe o bairro.", 2):
                errors.append("Bairro: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(city, "Informe a cidade.", 2):
                errors.append("Cidade: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(state, "Informe a UF.", 2):
                errors.append("UF: informe a UF com 2 letras.")
                valid = False
            if len((state.value or "").strip()) != 2:
                self.set_error(state, "Informe com 2 letras.")
                valid = False
            if len(self.only_digits(zip_code.value)) != 8:
                self.set_error(zip_code, "Informe 8 dígitos.")
                errors.append("CEP: informe 8 dígitos.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                geocoded_address_text.value = ""
                geocoded_coords.value = ""
                self.page.update()
                return
            error_message.value = ""
            info_message.value = "Localizando endereço..."
            geocoded_address_text.value = ""
            geocoded_coords.value = ""
            self.page.update()
            try:
                payload = {
                    "logradouro": street.value.strip(),
                    "numero": number.value.strip(),
                    "complemento": complement.value.strip() or None,
                    "bairro": district.value.strip(),
                    "cidade": city.value.strip(),
                    "estado": state.value.strip().upper(),
                    "cep": self.only_digits(zip_code.value),
                }
                result = self.api.request("POST", f'/organizacoes/{organization["id"]}/enderecos/geocodificar', json=payload)
                if result.get("success"):
                    geocoded_address_text.value = result.get("endereco_formatado") or "Endereço não formatado"
                    lat = result.get("latitude")
                    lng = result.get("longitude")
                    if lat and lng:
                        geocoded_coords.value = f"Coordenadas: {lat:.4f}, {lng:.4f}"
                    info_message.value = "✓ Endereço localizado! Clique em Salvar para confirmar."
                else:
                    error_message.value = result.get("error", "Não foi possível localizar o endereço")
                    geocoded_address_text.value = ""
                    geocoded_coords.value = ""
                    info_message.value = ""
            except ApiError as exc:
                error_message.value = str(exc)
                geocoded_address_text.value = ""
                geocoded_coords.value = ""
                info_message.value = ""
            self.page.update()

        def save(_):
            if not geocoded_address_text.value:
                error_message.value = "Você deve geocodificar o endereço primeiro. Clique em 'Localizar endereço'."
                self.page.update()
                return
            payload = {
                "logradouro": street.value.strip(),
                "numero": number.value.strip(),
                "complemento": complement.value.strip() or None,
                "bairro": district.value.strip(),
                "cidade": city.value.strip(),
                "estado": state.value.strip().upper(),
                "cep": self.only_digits(zip_code.value),
                "tipo": "OUTRO",
                "principal": principal_checkbox.value,
            }
            try:
                if address:
                    self.api.request("PUT", f'/organizacoes/{organization["id"]}/enderecos/{address["id"]}', json=payload)
                    message = "Endereço atualizado."
                else:
                    self.api.request("POST", f'/organizacoes/{organization["id"]}/enderecos', json=payload)
                    message = "Endereço cadastrado."
                self.close_dialog(dialog)
                self.notify(message)
                if on_return:
                    on_return()
                    self.page.update()
                elif parent_dialog:
                    self.organization_addresses_dialog(organization, on_return)
                else:
                    self.organization_addresses_dialog(organization)
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        if address is not None:
            geocoded_address_text.value = address.get("endereco_formatado") or f"{address.get('logradouro')}, {address.get('numero')}"
            if address.get("latitude") and address.get("longitude"):
                geocoded_coords.value = f"Coordenadas: {float(address['latitude']):.4f}, {float(address['longitude']):.4f}"

        # Build actions list conditionally
        actions_list = [
            ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
        ]
        if not address:
            actions_list.append(ft.TextButton("Localizar endereço", on_click=geocodify, icon=ft.Icons.LOCATION_ON))
        actions_list.append(ft.FilledButton("Salvar", on_click=save))

        dialog = ft.AlertDialog(
            title=ft.Text("Editar endereço" if address else "Novo endereço"),
            content=ft.Column([
                error_message,
                info_message,
                ft.Divider(height=10),
                zip_code,
                street,
                number,
                complement,
                district,
                city,
                state,
                principal_checkbox,
                ft.Divider(height=10),
                ft.Text("Endereço encontrado:", weight=ft.FontWeight.BOLD, size=12),
                geocoded_address_text,
                geocoded_coords,
            ], tight=True, width=480, height=600, scroll=ft.ScrollMode.AUTO),
            actions=actions_list,
        )
        if address is None:
            zip_code.on_blur = lookup_cep_auto
        self.open_dialog(dialog)

    def confirm_delete_organization_address(self, organization, address, parent_dialog, on_return=None):
        def delete(_):
            try:
                self.api.request("DELETE", f'/organizacoes/{organization["id"]}/enderecos/{address["id"]}')
                dialog.open = False
                parent_dialog.open = False
                self.notify("Endereço excluído.")
                if on_return:
                    on_return()
                else:
                    self.organization_addresses_dialog(organization)
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir endereço"),
            content=ft.Text(f'Deseja excluir "{address["logradouro"]}, {address["numero"]}"?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def address_dialog(self, client, parent_dialog=None, on_return=None, address=None):
        """Novo diálogo de endereço com CEP → geocodificação → confirmação.
        
        Fluxo:
        1. CEP informado
        2. Consulta viaCEP para auto-preenchimento
        3. Usuário informa número/complemento
        4. Sistema geocodifica com Google Maps
        5. Usuário confirma endereço encontrado
        6. Salva com latitude/longitude
        """
        error_message = ft.Text("", color=ft.Colors.RED_700)
        info_message = ft.Text("", color=ft.Colors.BLUE_700)
        
        # Campos em ordem: CEP, logradouro, número, complemento, bairro, cidade, UF
        zip_code = ft.TextField(
            label="CEP",
            value=(address or {}).get("cep", ""),
            helper_text="Informe para auto-preenchimento",
            on_change=lambda _: self.clear_errors(zip_code),
        )
        street = ft.TextField(
            label="Logradouro",
            value=(address or {}).get("logradouro", ""),
            read_only=(address is not None),  # Apenas leitura se editando
        )
        number = ft.TextField(
            label="Número",
            value=(address or {}).get("numero", ""),
        )
        complement = ft.TextField(
            label="Complemento",
            value=(address or {}).get("complemento") or "",
        )
        district = ft.TextField(
            label="Bairro",
            value=(address or {}).get("bairro", ""),
            read_only=(address is not None),
        )
        city = ft.TextField(
            label="Cidade",
            value=(address or {}).get("cidade", ""),
            read_only=(address is not None),
        )
        state = ft.TextField(
            label="UF",
            value=(address or {}).get("estado", "SC"),
            read_only=(address is not None),
        )
        
        # Campo de confirmação do endereço geocodificado
        geocoded_address_text = ft.Text("", color=ft.Colors.GREEN_700, size=12)
        geocoded_coords = ft.Text("", color=ft.Colors.GREEN_700, size=10)

        def lookup_cep_auto(_=None):
            """Consulta CEP ao perder foco."""
            cep_value = self.only_digits(zip_code.value)
            if len(cep_value) != 8:
                return
            
            if address is not None:  # Se editando, não faz lookup
                return
            
            self.clear_errors(zip_code, street, district, city, state)
            info_message.value = "Consultando CEP..."
            self.page.update()
            
            try:
                result = self.api.request("GET", f'/clientes/{client["id"]}/enderecos/lookup-cep/{cep_value}')
                if result.get("success"):
                    street.value = result.get("logradouro", "")
                    district.value = result.get("bairro", "")
                    city.value = result.get("cidade", "")
                    state.value = result.get("estado", "").upper()
                    # Não preencher automaticamente o campo 'complemento' vindo do ViaCEP
                    info_message.value = "CEP preenchido com sucesso!"
                else:
                    self.set_error(zip_code, result.get("error", "CEP não encontrado"))
                    info_message.value = ""
            except ApiError as exc:
                self.set_error(zip_code, str(exc))
                info_message.value = ""
            
            self.page.update()

        def geocodify(_=None):
            """Geocodifica o endereço completo."""
            self.clear_errors(number, street, district, city, state, zip_code)
            errors = []
            valid = True
            
            if not self.require_text(street, "Informe o logradouro.", 2):
                errors.append("Logradouro: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(number, "Informe o número.", 1):
                errors.append("Número: informe o número.")
                valid = False
            if not self.require_text(district, "Informe o bairro.", 2):
                errors.append("Bairro: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(city, "Informe a cidade.", 2):
                errors.append("Cidade: informe pelo menos 2 caracteres.")
                valid = False
            if not self.require_text(state, "Informe a UF.", 2):
                errors.append("UF: informe a UF com 2 letras.")
                valid = False
            if len((state.value or "").strip()) != 2:
                self.set_error(state, "Informe com 2 letras.")
                valid = False
            if len(self.only_digits(zip_code.value)) != 8:
                self.set_error(zip_code, "Informe 8 dígitos.")
                errors.append("CEP: informe 8 dígitos.")
                valid = False
            
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                geocoded_address_text.value = ""
                geocoded_coords.value = ""
                self.page.update()
                return
            
            error_message.value = ""
            info_message.value = "Localizando endereço..."
            geocoded_address_text.value = ""
            geocoded_coords.value = ""
            self.page.update()
            
            try:
                payload = {
                    "logradouro": street.value.strip(),
                    "numero": number.value.strip(),
                    "complemento": complement.value.strip() or None,
                    "bairro": district.value.strip(),
                    "cidade": city.value.strip(),
                    "estado": state.value.strip().upper(),
                    "cep": self.only_digits(zip_code.value),
                }
                result = self.api.request(
                    "POST",
                    f'/clientes/{client["id"]}/enderecos/geocodificar',
                    json=payload
                )
                
                if result.get("success"):
                    # Mostrar endereço geocodificado
                    geocoded_address_text.value = result.get("endereco_formatado") or "Endereço não formatado"
                    lat = result.get("latitude")
                    lng = result.get("longitude")
                    if lat and lng:
                        geocoded_coords.value = f"Coordenadas: {lat:.4f}, {lng:.4f}"
                    info_message.value = "✓ Endereço localizado! Clique em Salvar para confirmar."
                else:
                    error_message.value = result.get("error", "Não foi possível localizar o endereço")
                    geocoded_address_text.value = ""
                    geocoded_coords.value = ""
                    info_message.value = ""
            except ApiError as exc:
                error_message.value = str(exc)
                geocoded_address_text.value = ""
                geocoded_coords.value = ""
                info_message.value = ""
            
            self.page.update()

        def save(_):
            """Salva o endereço após confirmação."""
            if not geocoded_address_text.value:
                error_message.value = "Você deve geocodificar o endereço primeiro. Clique em 'Localizar endereço'."
                self.page.update()
                return
            
            payload = {
                "logradouro": street.value.strip(),
                "numero": number.value.strip(),
                "complemento": complement.value.strip() or None,
                "bairro": district.value.strip(),
                "cidade": city.value.strip(),
                "estado": state.value.strip().upper(),
                "cep": self.only_digits(zip_code.value),
                "tipo": "OUTRO",  # Campo tipo não mais editável, sempre "OUTRO"
            }
            
            try:
                if address:
                    self.api.request(
                        "PUT",
                        f'/clientes/{client["id"]}/enderecos/{address["id"]}',
                        json=payload,
                    )
                    message = "Endereço atualizado."
                else:
                    self.api.request("POST", f'/clientes/{client["id"]}/enderecos', json=payload)
                    message = "Endereço cadastrado."
                
                self.close_dialog(dialog)
                self.notify(message)
                
                # Callback para retornar ao pedido/pai sem fechar
                if on_return:
                    on_return()
                    self.page.update()
                # Se não há callback, atualiza apenas addresses_dialog
                elif parent_dialog:
                    self.addresses_dialog(client, on_return)
                else:
                    self.addresses_dialog(client)
                    
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        # Observação: se editando endereço existente, não geocodifica novamente
        if address is not None:
            geocoded_address_text.value = address.get("endereco_formatado") or f"{address.get('logradouro')}, {address.get('numero')}"
            if address.get("latitude") and address.get("longitude"):
                geocoded_coords.value = f"Coordenadas: {float(address['latitude']):.4f}, {float(address['longitude']):.4f}"

        actions_list = [
            ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
        ]
        if not address:
            actions_list.append(ft.TextButton("Localizar endereço", on_click=geocodify, icon=ft.Icons.LOCATION_ON))
        actions_list.append(ft.FilledButton("Salvar", on_click=save))

        dialog = ft.AlertDialog(
            title=ft.Text("Editar endereço" if address else "Novo endereço"),
            content=ft.Column([
                error_message,
                info_message,
                ft.Divider(height=10),
                zip_code,
                street,
                number,
                complement,
                district,
                city,
                state,
                ft.Divider(height=10),
                ft.Text("Endereço encontrado:", weight=ft.FontWeight.BOLD, size=12),
                geocoded_address_text,
                geocoded_coords,
            ], tight=True, width=480, height=600, scroll=ft.ScrollMode.AUTO),
            actions=actions_list,
        )

        # Se não estiver editando, configurar on_blur no CEP
        if address is None:
            zip_code.on_blur = lookup_cep_auto

        self.open_dialog(dialog)

    def confirm_delete_address(self, client, address, parent_dialog, on_return=None):
        def delete(_):
            try:
                self.api.request("DELETE", f'/clientes/{client["id"]}/enderecos/{address["id"]}')
                dialog.open = False
                parent_dialog.open = False
                self.notify("Endereço excluído.")
                if on_return:
                    on_return()
                else:
                    self.addresses_dialog(client)
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir endereço"),
            content=ft.Text(f'Deseja excluir "{address["logradouro"]}, {address["numero"]}"?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def set_client_status(self, client_id, active):
        try:
            self.api.request("PATCH", f"/clientes/{client_id}/status", json={"ativo": active})
            self.notify("Cliente ativado." if active else "Cliente desativado.")
            self.clients_view()
        except ApiError as exc:
            self.notify(str(exc), True)

    def confirm_delete_client(self, client):
        def delete(_):
            try:
                self.api.request("DELETE", f'/clientes/{client["id"]}')
                dialog.open = False
                self.notify("Cliente excluído.")
                self.clients_view()
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir cliente"),
            content=ft.Text(f'Deseja excluir "{client["nome"]}"?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def products_view(self, search="", offset=0):
        page_size = 10
        try:
            products = self.api.request("GET", f"/produtos?limit={page_size}&offset={offset}")
            if search.strip():
                term = search.strip().lower()
                products = [
                    item for item in products
                    if term in item["nome"].lower() or term in (item.get("descricao") or "").lower()
                ]
            search_field = ft.TextField(
                label="Buscar produto",
                value=search,
                prefix_icon=ft.Icons.SEARCH,
                on_submit=lambda event: self.products_view(event.control.value),
            )
            rows = []
            for item in products:
                status = "Ativo" if item["ativo"] else "Inativo"
                rows.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.INVENTORY_2),
                    title=ft.Text(item["nome"]),
                    subtitle=ft.Text(
                        f'R$ {float(item["valor_declarado"]):.2f} · {item["peso"]} kg · {status}'
                    ),
                    trailing=ft.Row([
                        ft.IconButton(ft.Icons.EDIT, tooltip="Editar produto",
                                      on_click=lambda _, product=item: self.product_dialog(product)),
                        ft.IconButton(
                            ft.Icons.TOGGLE_ON if item["ativo"] else ft.Icons.TOGGLE_OFF,
                            tooltip="Desativar produto" if item["ativo"] else "Ativar produto",
                            on_click=lambda _, product=item: self.set_product_status(
                                product["id"], not product["ativo"]
                            ),
                        ),
                        ft.IconButton(ft.Icons.DELETE, tooltip="Excluir produto",
                                      icon_color=ft.Colors.RED_700,
                                      on_click=lambda _, product=item: self.confirm_delete_product(product)),
                    ], tight=True),
                ))
            self.content.controls = [
                self.header_bar("Produtos", f"{len(products)} produto(s)", [
                    ft.FilledButton("Novo produto", icon=ft.Icons.ADD,
                                    on_click=lambda _: self.product_dialog()),
                ]),
                ft.Container(ft.Row([
                    search_field,
                    ft.IconButton(ft.Icons.SEARCH, tooltip="Buscar", on_click=lambda _: self.products_view(search_field.value, 0)),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.products_view()),
                    self.page_controls(
                        lambda _: self.products_view(search, max(0, offset - page_size)),
                        lambda _: self.products_view(search, offset + page_size),
                        can_previous=offset > 0,
                        can_next=len(products) == page_size and not search.strip(),
                    ),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhum produto encontrado.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def product_dialog(self, product=None):
        error_message = ft.Text("", color=ft.Colors.RED_700)
        name = ft.TextField(label="Nome", value=(product or {}).get("nome", ""))
        description = ft.TextField(label="Descrição", value=(product or {}).get("descricao") or "", multiline=True)
        weight = ft.TextField(label="Peso", value=str((product or {}).get("peso") or "0"))
        volume = ft.TextField(label="Volume", value=str((product or {}).get("volume") or "0"))
        declared = ft.TextField(label="Valor declarado", value=str((product or {}).get("valor_declarado") or "0"))

        def save(_):
            self.clear_errors(name, weight, volume, declared)
            errors = []
            valid = True
            if not self.require_text(name, "Informe pelo menos 2 caracteres.", 2):
                errors.append("Nome: informe pelo menos 2 caracteres.")
                valid = False
            if not self.validate_positive_number(weight, "Informe um peso igual ou maior que zero."):
                errors.append("Peso: informe um valor maior ou igual a zero.")
                valid = False
            if not self.validate_positive_number(volume, "Informe um volume igual ou maior que zero."):
                errors.append("Volume: informe um valor maior ou igual a zero.")
                valid = False
            if not self.validate_positive_number(declared, "Informe um valor igual ou maior que zero."):
                errors.append("Valor declarado: informe um valor maior ou igual a zero.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            payload = {
                "nome": name.value.strip(),
                "descricao": description.value.strip() or None,
                "peso": self.money(weight.value),
                "volume": self.money(volume.value),
                "valor_declarado": self.money(declared.value),
            }
            try:
                if product:
                    self.api.request("PUT", f'/produtos/{product["id"]}', json=payload)
                    message = "Produto atualizado."
                else:
                    self.api.request("POST", "/produtos", json=payload)
                    message = "Produto cadastrado."
                self.close_dialog(dialog)
                self.notify(message)
                self.products_view()
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Editar produto" if product else "Novo produto"),
            content=ft.Column([error_message, name, description, weight, volume, declared], tight=True, width=380, height=420, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        self.open_dialog(dialog)

    def set_product_status(self, product_id, active):
        try:
            self.api.request("PATCH", f"/produtos/{product_id}/status", json={"ativo": active})
            self.notify("Produto ativado." if active else "Produto desativado.")
            self.products_view()
        except ApiError as exc:
            self.notify(str(exc), True)

    def confirm_delete_product(self, product):
        def delete(_):
            try:
                self.api.request("DELETE", f'/produtos/{product["id"]}')
                dialog.open = False
                self.notify("Produto excluído.")
                self.products_view()
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir produto"),
            content=ft.Text(f'Deseja excluir "{product["nome"]}"?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def users_view(self, search="", offset=0):
        if self.user["perfil"] != "ADMIN":
            self.content.controls = [
                ft.Container(self.heading("Usuários", "Acesso restrito a administradores."), padding=20),
            ]
            self.page.update()
            return
        page_size = 10
        try:
            users = self.api.request("GET", f"/usuarios?limit={page_size}&offset={offset}")
            if search.strip():
                term = search.strip().lower()
                users = [
                    item for item in users
                    if term in item["nome"].lower() or term in item["email"].lower() or term in item["perfil"].lower()
                ]
            search_field = ft.TextField(
                label="Buscar usuário",
                value=search,
                prefix_icon=ft.Icons.SEARCH,
                on_submit=lambda event: self.users_view(event.control.value),
            )
            rows = []
            for item in users:
                status = "Ativo" if item["ativo"] else "Inativo"
                rows.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.PERSON),
                    title=ft.Text(item["nome"]),
                    subtitle=ft.Text(f'{item["email"]} · {item["perfil"]} · {status}'),
                    trailing=ft.Row([
                        ft.IconButton(ft.Icons.EDIT, tooltip="Editar usuário",
                                      on_click=lambda _, user=item: self.user_dialog(user)),
                        ft.IconButton(
                            ft.Icons.TOGGLE_ON if item["ativo"] else ft.Icons.TOGGLE_OFF,
                            tooltip="Desativar usuário" if item["ativo"] else "Ativar usuário",
                            on_click=lambda _, user=item: self.set_user_status(user["id"], not user["ativo"]),
                        ),
                        ft.IconButton(ft.Icons.DELETE, tooltip="Excluir usuário",
                                      icon_color=ft.Colors.RED_700,
                                      on_click=lambda _, user=item: self.confirm_delete_user(user)),
                    ], tight=True),
                ))
            self.content.controls = [
                self.header_bar("Usuários", f"{len(users)} usuário(s)", [
                    ft.FilledButton("Novo usuário", icon=ft.Icons.ADD,
                                    on_click=lambda _: self.user_dialog()),
                ]),
                ft.Container(ft.Row([
                    search_field,
                    ft.IconButton(ft.Icons.SEARCH, tooltip="Buscar", on_click=lambda _: self.users_view(search_field.value, 0)),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.users_view()),
                    self.page_controls(
                        lambda _: self.users_view(search, max(0, offset - page_size)),
                        lambda _: self.users_view(search, offset + page_size),
                        can_previous=offset > 0,
                        can_next=len(users) == page_size and not search.strip(),
                    ),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhum usuário encontrado.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def user_dialog(self, user=None):
        name = ft.TextField(label="Nome", value=(user or {}).get("nome", ""))
        email = ft.TextField(label="E-mail", value=(user or {}).get("email", ""))
        password = ft.TextField(
            label="Senha",
            value="" if user else "123456",
            password=True,
            can_reveal_password=True,
            helper="Deixe em branco para manter a senha atual." if user else None,
        )
        phone = ft.TextField(label="Telefone", value=(user or {}).get("telefone") or "")
        profile = ft.Dropdown(
            label="Perfil",
            value=(user or {}).get("perfil", "GESTOR"),
            options=[self.option(value) for value in ["ADMIN", "GESTOR", "MOTORISTA"]],
        )
        organization = ft.Dropdown(
            label="Organização",
            value=str((user or {}).get("organizacao_id")) if (user or {}).get("organizacao_id") else None,
            options=[],
        )
        error_message = ft.Text("", color=ft.Colors.RED_700)

        def load_organizations():
            try:
                orgs = self.api.request("GET", "/organizacoes?limit=100&offset=0")
                organization.options = [self.option(item["id"], item["nome"]) for item in orgs]
                if user and user.get("organizacao_id"):
                    organization.value = str(user["organizacao_id"])
                self.page.update()
            except ApiError as exc:
                self.notify(str(exc), True)

        load_organizations()

        def save(_):
            self.clear_errors(name, email, password, profile, organization)
            # validações e coleta de mensagens para feedback
            errors = []
            if not self.require_text(name, "Informe pelo menos 2 caracteres.", 2):
                errors.append("Nome: informe pelo menos 2 caracteres.")
            if not self.validate_email_field(email):
                errors.append("E-mail: informe um e-mail válido.")
            if not self.require_dropdown(profile, "Selecione o perfil."):
                errors.append("Perfil: selecione o perfil.")
            if not user:
                if len((password.value or "").strip()) < 6:
                    self.set_error(password, "Informe uma senha com pelo menos 6 caracteres.")
                    errors.append("Senha: informe pelo menos 6 caracteres.")
            else:
                if (password.value or "").strip() and len(password.value.strip()) < 6:
                    self.set_error(password, "A nova senha deve ter pelo menos 6 caracteres.")
                    errors.append("Senha: a nova senha deve ter pelo menos 6 caracteres.")
            if errors:
                # mostra mensagens específicas dentro do diálogo e mantém os campos
                error_message.value = "; ".join(errors)
                self.page.update()
                return
            payload = {
                "nome": name.value.strip(),
                "email": email.value.strip(),
                "senha": password.value.strip() or None,
                "telefone": phone.value.strip() or None,
                "perfil": profile.value,
                "organizacao_id": int(organization.value) if organization.value else None,
            }
            try:
                if user:
                    self.api.request("PUT", f'/usuarios/{user["id"]}', json=payload)
                    message = "Usuário atualizado."
                else:
                    self.api.request("POST", "/usuarios", json=payload)
                    message = "Usuário cadastrado."
                # sucesso: fecha diálogo e atualiza lista
                self.close_dialog(dialog)
                self.notify(message)
                self.users_view()
            except ApiError as exc:
                # não fecha o diálogo automaticamente; mostra erro detalhado dentro do diálogo
                err_msg = str(exc)
                error_message.value = f"Não foi possível salvar: {err_msg}"
                self.page.update()
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Editar usuário" if user else "Novo usuário"),
            content=ft.Column([error_message, name, email, password, phone, profile, organization], tight=True, width=380, height=420, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        self.open_dialog(dialog)

    def set_user_status(self, user_id, active):
        try:
            self.api.request("PATCH", f"/usuarios/{user_id}/status", json={"ativo": active})
            self.notify("Usuário ativado." if active else "Usuário desativado.")
            self.users_view()
        except ApiError as exc:
            self.notify(str(exc), True)

    def confirm_delete_user(self, user):
        def delete(_):
            try:
                self.api.request("DELETE", f'/usuarios/{user["id"]}')
                dialog.open = False
                self.notify("Usuário excluído.")
                self.users_view()
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir usuário"),
            content=ft.Text(f'Deseja excluir "{user["nome"]}"?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def reports_view(self, start="", end="", status=""):
        start_field = ft.TextField(label="Início", value=start, hint_text="YYYY-MM-DDTHH:MM:SS")
        end_field = ft.TextField(label="Fim", value=end, hint_text="YYYY-MM-DDTHH:MM:SS")
        status_field = ft.Dropdown(
            label="Status",
            value=status or None,
            options=[self.option(value) for value in [
                "AGUARDANDO_COLETA", "COLETADA", "EM_ROTA",
                "ENTREGUE", "NAO_ENTREGUE", "CANCELADA",
            ]],
        )

        def load_report():
            self.clear_errors(start_field, end_field)
            params = []
            if start_field.value.strip():
                try:
                    datetime.fromisoformat(start_field.value.strip())
                    params.append(f"inicio={start_field.value.strip()}")
                except ValueError:
                    self.set_error(start_field, "Use o formato YYYY-MM-DDTHH:MM:SS.")
            if end_field.value.strip():
                try:
                    datetime.fromisoformat(end_field.value.strip())
                    params.append(f"fim={end_field.value.strip()}")
                except ValueError:
                    self.set_error(end_field, "Use o formato YYYY-MM-DDTHH:MM:SS.")
            if start_field.error or end_field.error:
                self.page.update()
                messages = []
                if start_field.error:
                    messages.append(start_field.error)
                if end_field.error:
                    messages.append(end_field.error)
                self.notify("; ".join(messages), True)
                return None
            if status_field.value:
                params.append(f"status={status_field.value}")
            path = "/relatorios/entregas"
            if params:
                path += "?" + "&".join(params)
            return self.api.request("GET", path)

        try:
            report = load_report()
            if report is None:
                return
            rows = [
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.LOCAL_SHIPPING, color=STATUS_COLORS.get(item["status"])),
                    title=ft.Text(f'Entrega #{item["id"]} · Pedido #{item["pedido_id"]}'),
                    subtitle=ft.Text(
                        f'{item["status"]} · Previsto: {item["previsao_entrega"] or "não informado"}'
                    ),
                )
                for item in report["entregas"]
            ]
            self.content.controls = [
                ft.Container(self.heading("Relatórios", f'{report["total"]} entrega(s)'), padding=20),
                ft.Container(ft.Row([
                    start_field,
                    end_field,
                    status_field,
                    ft.IconButton(
                        ft.Icons.SEARCH,
                        tooltip="Filtrar",
                        on_click=lambda _: self.reports_view(
                            start_field.value, end_field.value, status_field.value or "",
                        ),
                    ),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.reports_view()),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhuma entrega encontrada.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def orders_view(self, search="", offset=0, status_filter=""):
        page_size = 10
        try:
            params = [f"limit={page_size}", f"offset={offset}"]
            if search.strip():
                params.append(f"busca={quote(search.strip())}")
            if status_filter:
                params.append(f"status={status_filter}")
            path = "/pedidos?" + "&".join(params)
            orders = self.api.request("GET", path)
            search_field = ft.TextField(
                label="Buscar pedido",
                value=search,
                prefix_icon=ft.Icons.SEARCH,
                on_submit=lambda event: self.orders_view(event.control.value),
            )
            status_dropdown = ft.Dropdown(
                label="Status",
                value=status_filter or None,
                options=[self.option(value) for value in ["ABERTO", "EM_PROCESSAMENTO", "FINALIZADO", "CANCELADO"]],
            )
            rows = [
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.RECEIPT_LONG),
                    title=ft.Text(item["numero_pedido"]),
                    subtitle=ft.Text(
                        f'Cliente #{item["cliente_id"]} · {item["status"]} · {item["prioridade"]}'
                    ),
                    trailing=ft.Row([
                        ft.Text(f'R$ {float(item["valor_total"]):.2f}'),
                        ft.IconButton(
                            ft.Icons.LIST,
                            tooltip="Itens do pedido",
                            on_click=lambda _, order=item: self.order_items_dialog(order),
                        ),
                        ft.IconButton(
                            ft.Icons.EDIT_NOTE,
                            tooltip="Editar pedido",
                            on_click=lambda _, order=item: self.order_dialog(order),
                        ),
                        ft.PopupMenuButton(
                            icon=ft.Icons.EDIT,
                            tooltip="Atualizar status",
                            items=[
                                ft.PopupMenuItem(
                                    content=ft.Text(value.replace("_", " ").title()),
                                    on_click=lambda _, order_id=item["id"], new_status=value:
                                        self.update_order_status(order_id, new_status),
                                )
                                for value in ["ABERTO", "EM_PROCESSAMENTO", "FINALIZADO", "CANCELADO"]
                            ],
                        ),
                        ft.IconButton(
                            ft.Icons.DELETE,
                            tooltip="Excluir pedido",
                            icon_color=ft.Colors.RED_700,
                            on_click=lambda _, order=item: self.confirm_delete_order(order),
                        ),
                    ], tight=True),
                ) for item in orders
            ]
            self.content.controls = [
                self.header_bar("Pedidos", f"{len(orders)} pedido(s)", [
                    ft.FilledButton("Novo pedido", icon=ft.Icons.ADD,
                                    on_click=lambda _: self.order_dialog()),
                ]),
                ft.Container(ft.Row([
                    search_field,
                    status_dropdown,
                    ft.IconButton(
                        ft.Icons.SEARCH,
                        tooltip="Buscar",
                        on_click=lambda _: self.orders_view(search_field.value, 0, status_dropdown.value or ""),
                    ),
                    ft.IconButton(ft.Icons.CLEAR, tooltip="Limpar", on_click=lambda _: self.orders_view()),
                    self.page_controls(
                        lambda _: self.orders_view(search, max(0, offset - page_size), status_filter),
                        lambda _: self.orders_view(search, offset + page_size, status_filter),
                        can_previous=offset > 0,
                        can_next=len(orders) == page_size,
                    ),
                ]), padding=20),
                ft.Container(ft.Column(rows or [ft.Text("Nenhum pedido encontrado.")]), padding=10),
            ]
            self.page.update()
        except ApiError as exc:
            self.notify(str(exc), True)

    def order_items_dialog(self, order):
        try:
            items = self.api.request("GET", f'/pedidos/{order["id"]}/itens')
            products = self.api.request("GET", "/produtos")
        except ApiError as exc:
            self.notify(str(exc), True)
            return
        product_names = {item["id"]: item["nome"] for item in products}
        rows = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.SHOPPING_CART),
                title=ft.Text(product_names.get(item["produto_id"], f'Produto #{item["produto_id"]}')),
                subtitle=ft.Text(f'{item["quantidade"]} x R$ {float(item["valor_unitario"]):.2f}'),
                trailing=ft.IconButton(
                    ft.Icons.DELETE,
                    tooltip="Remover item",
                    icon_color=ft.Colors.RED_700,
                    on_click=lambda _, order_item=item: self.delete_order_item(order, order_item, dialog),
                ),
            )
            for item in items
        ]
        dialog = ft.AlertDialog(
            title=ft.Text(f'Itens do pedido {order["numero_pedido"]}'),
            content=ft.Column(rows or [ft.Text("Nenhum item encontrado.")], tight=True, width=520),
            actions=[ft.TextButton("Fechar", on_click=lambda _: self.close_dialog(dialog))],
        )
        self.open_dialog(dialog)

    def delete_order_item(self, order, item, parent_dialog):
        try:
            self.api.request("DELETE", f'/pedidos/{order["id"]}/itens/{item["id"]}')
            self.close_dialog(parent_dialog, update=False)
            self.notify("Item removido.")
            self.order_items_dialog(order)
        except ApiError as exc:
            self.page.update()
            self.notify(str(exc), True)
            return

    def confirm_delete_order(self, order):
        def delete(_):
            try:
                self.api.request("DELETE", f'/pedidos/{order["id"]}')
                dialog.open = False
                self.notify("Pedido excluído.")
                self.orders_view()
            except ApiError as exc:
                self.page.update()
                self.notify(str(exc), True)
                return

        dialog = ft.AlertDialog(
            title=ft.Text("Excluir pedido"),
            content=ft.Text(f'Deseja excluir o pedido {order["numero_pedido"]}?'),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Excluir", icon=ft.Icons.DELETE, on_click=delete),
            ],
        )
        self.open_dialog(dialog)

    def update_order_status(self, order_id, status):
        try:
            self.api.request("PATCH", f"/pedidos/{order_id}/status", json={"status": status})
            self.notify("Status do pedido atualizado.")
            self.orders_view()
        except ApiError as exc:
            self.notify(str(exc), True)

    def order_dialog(self, order=None):
        try:
            clients = self.api.request("GET", "/clientes")
            organizations = self.api.request("GET", "/organizacoes?limit=100&offset=0")
            products = self.api.request("GET", "/produtos")
            existing_items = self.api.request("GET", f'/pedidos/{order["id"]}/itens') if order else []
        except ApiError as exc:
            self.notify(str(exc), True)
            return
        active_clients = [item for item in clients if item["ativo"]]
        active_organizations = [item for item in organizations if item.get("ativo", True)]
        active_products = [item for item in products if item["ativo"]]
        product_names = {item["id"]: item["nome"] for item in products}
        order_items = [
            {
                "produto_id": item["produto_id"],
                "nome": product_names.get(item["produto_id"], f'Produto #{item["produto_id"]}'),
                "quantidade": item["quantidade"],
                "valor_unitario": float(item["valor_unitario"]),
            }
            for item in existing_items
        ]
        addresses = []
        selected_endereco_id = str(order["endereco_entrega_id"]) if order and order.get("endereco_entrega_id") else None
        address_info = ft.Text("", color=ft.Colors.BLUE_700)

        def on_client_change():
            nonlocal selected_endereco_id
            selected_endereco_id = None
            if client.value:
                load_addresses(int(client.value))
            else:
                addresses.clear()
                refresh_address_options()
                address_info.value = ""

        def load_addresses(client_id):
            nonlocal addresses, selected_endereco_id
            try:
                addresses = self.api.request("GET", f"/clientes/{client_id}/enderecos")
            except ApiError as exc:
                self.notify(str(exc), True)
                addresses = []
            if selected_endereco_id and not any(str(item["id"]) == selected_endereco_id for item in addresses):
                selected_endereco_id = None
            refresh_address_options()
            if not addresses:
                address_info.value = "Este cliente não possui endereços cadastrados. Abra o cadastro de endereços para registrar um endereço e depois selecione-o aqui."
            else:
                address_info.value = ""
            self.page.update()

        def refresh_address_options():
            address.options = [
                self.option(item["id"], f'{item["logradouro"]}, {item["numero"]} - {item["bairro"]} ({item["cidade"]}/{item["estado"]})')
                for item in addresses
            ]
            address.value = selected_endereco_id if selected_endereco_id and any(str(item["id"]) == selected_endereco_id for item in addresses) else None
            address.disabled = len(address.options) == 0
            self.page.update()

        def open_client_addresses(_=None):
            selected_client = next((item for item in active_clients if str(item["id"]) == client.value), None)
            if not selected_client:
                self.notify("Selecione um cliente antes de gerenciar endereços.", True)
                return
            
            def on_return_from_addresses():
                """Recarrega endereços ao voltar do diálogo de endereços."""
                if client.value:
                    load_addresses(int(client.value))
            
            # Passar dialog do pedido como parent_dialog + callback de retorno
            self.addresses_dialog(selected_client, on_return=on_return_from_addresses)

        def select_product(_=None):
            selected = next((item for item in active_products if str(item["id"]) == product.value), None)
            if selected:
                price.value = str(selected["valor_declarado"])
                self.page.update()

        client = ft.Dropdown(
            label="Cliente",
            value=str(order["cliente_id"]) if order else None,
            options=[self.option(item["id"], item["nome"]) for item in active_clients],
            on_change=lambda _: on_client_change(),
        )
        organization = ft.Dropdown(
            label="Ponto de Coleta (Organização)",
            value=str(order["organizacao_id"]) if order and order.get("organizacao_id") else None,
            options=[self.option(item["id"], item["nome"]) for item in active_organizations],
        )
        address = ft.Dropdown(
            label="Endereço de entrega",
            value=selected_endereco_id,
            options=[],
            disabled=True,
        )
        open_addresses_button = ft.FilledButton(
            "Gerenciar endereços do cliente",
            on_click=open_client_addresses,
        )
        if order and client.value:
            load_addresses(int(client.value))
        product = ft.Dropdown(
            label="Produto",
            options=[self.option(item["id"], item["nome"]) for item in active_products],
            on_change=select_product,
        )
        quantity = ft.TextField(label="Quantidade", value="1", width=130)
        price = ft.TextField(label="Valor unitário", value="0", width=160)
        items_column = ft.Column(spacing=6)
        priority = ft.Dropdown(
            label="Prioridade",
            value=order["prioridade"] if order else "NORMAL",
            options=[self.option(value) for value in ["BAIXA", "NORMAL", "ALTA", "URGENTE"]],
        )
        payment = ft.TextField(label="Forma de pagamento", value=(order or {}).get("forma_pagamento") or "")
        notes = ft.TextField(label="Observações", value=(order or {}).get("observacoes") or "", multiline=True)

        def refresh_items():
            items_column.controls = [
                ft.Text("Itens adicionados", weight=ft.FontWeight.BOLD, size=12),
                *[
                    ft.ListTile(
                        dense=True,
                        leading=ft.Icon(ft.Icons.SHOPPING_CART),
                        title=ft.Text(item["nome"]),
                        subtitle=ft.Text(f'{item["quantidade"]} x R$ {item["valor_unitario"]:.2f}'),
                        trailing=ft.Row([
                            ft.TextButton("Remover", icon=ft.Icons.DELETE, on_click=lambda _, index=index: remove_item(index)),
                        ], tight=True),
                    )
                    for index, item in enumerate(order_items)
                ],
            ] if order_items else [ft.Text("Nenhum item adicionado.")]
            self.page.update()

        def remove_item(index):
            order_items.pop(index)
            refresh_items()

        def add_item(_):
            self.clear_errors(product, quantity, price)
            errors = []
            valid = True
            if not self.require_dropdown(product, "Selecione o produto."):
                errors.append("Produto: selecione um produto.")
                valid = False
            if not self.validate_positive_number(price, "Informe um valor unitário igual ou maior que zero."):
                errors.append("Valor unitário: informe um valor maior ou igual a zero.")
                valid = False
            try:
                qty = int(quantity.value or 0)
            except ValueError:
                qty = 0
            if qty < 1:
                self.set_error(quantity, "Informe uma quantidade maior que zero.")
                errors.append("Quantidade: informe uma quantidade maior que zero.")
                valid = False
            selected = next((item for item in active_products if str(item["id"]) == product.value), None)
            if not selected:
                self.set_error(product, "Selecione o produto.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            order_items.append({
                "produto_id": int(product.value),
                "nome": selected["nome"],
                "quantidade": qty,
                "valor_unitario": self.money(price.value),
            })
            product.value = None
            quantity.value = "1"
            price.value = "0"
            refresh_items()

        error_message = ft.Text("", color=ft.Colors.RED_700)

        def save(_):
            self.clear_errors(client, organization, address, priority)
            errors = []
            valid = True
            if not self.require_dropdown(client, "Selecione o cliente."):
                errors.append("Cliente: selecione um cliente.")
                valid = False
            if not self.require_dropdown(organization, "Selecione a organização."):
                errors.append("Organização: selecione a organização do ponto de coleta.")
                valid = False
            if not self.require_dropdown(address, "Selecione o endereço de entrega."):
                errors.append("Endereço de entrega: selecione um endereço.")
                valid = False
            if not self.require_dropdown(priority, "Selecione a prioridade."):
                errors.append("Prioridade: selecione a prioridade.")
                valid = False
            if not order_items:
                self.set_error(product, "Adicione pelo menos um item.")
                errors.append("Itens: adicione pelo menos um item ao pedido.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            payload = {
                "cliente_id": int(client.value),
                "organizacao_id": int(organization.value) if organization.value else None,
                "endereco_entrega_id": int(address.value),
                "prioridade": priority.value,
                "forma_pagamento": payment.value.strip() or None,
                "observacoes": notes.value.strip() or None,
                "itens": [
                    {
                        "produto_id": item["produto_id"],
                        "quantidade": item["quantidade"],
                        "valor_unitario": item["valor_unitario"],
                    }
                    for item in order_items
                ],
            }
            try:
                method = "PUT" if order else "POST"
                path = f'/pedidos/{order["id"]}' if order else "/pedidos"
                self.api.request(method, path, json=payload)
                self.close_dialog(dialog)
                self.notify("Pedido atualizado." if order else "Pedido cadastrado.")
                self.orders_view()
            except ApiError as exc:
                error_message.value = str(exc)
                self.page.update()
                return
            except ValueError as exc:
                self.notify(str(exc), True)

        dialog = ft.AlertDialog(
            title=ft.Text("Editar pedido" if order else "Novo pedido"),
            content=ft.Column([
                client,
                organization,
                ft.Row([address, open_addresses_button], spacing=10),
                ft.Row([
                    product,
                    quantity,
                    price,
                    ft.FilledButton("Adicionar item", icon=ft.Icons.ADD, on_click=add_item),
                ], wrap=True, spacing=10),
                address_info,
                items_column,
                priority,
                payment,
                notes,
            ], tight=True, width=520, height=580, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                     ft.FilledButton("Salvar", on_click=save)],
        )
        refresh_items()
        # inserir mensagem de erro no topo do diálogo
        dialog.content.controls.insert(0, error_message)
        self.open_dialog(dialog)

