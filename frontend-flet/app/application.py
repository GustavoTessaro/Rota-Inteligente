from datetime import datetime, timezone
from urllib.parse import quote
import math

import asyncio
import json
import threading
import time

import flet as ft
import flet_map as fmap

try:
    import websockets
except Exception:  # pragma: no cover - optional dependency during import
    websockets = None

from .api_client import ApiClient, ApiError
from .config import API_BASE_URL, MAPTILER_API_KEY, build_tracking_ws_url
from .dashboard_utils import DASHBOARD_INDICATORS, DashboardRefreshController, get_dashboard_indicator_values
from .driver_location_tracking import DriverLocationTracking
from .geolocation_provider import GeolocationPermissionDenied, GeolocationProvider, GeolocationServiceUnavailable
from .map_view import MapView
from .tracking_client import build_marker, update_vehicle_state


TRACKING_STALE_AFTER_SECONDS = 45


STATUS_COLORS = {
    "AGUARDANDO_COLETA": ft.Colors.ORANGE,
    "COLETADA": ft.Colors.BLUE,
    "EM_ROTA": ft.Colors.PURPLE,
    "ENTREGUE": ft.Colors.GREEN,
    "NAO_ENTREGUE": ft.Colors.RED,
    "CANCELADA": ft.Colors.GREY,
}
TERMINAL_DELIVERY_STATUSES = {"ENTREGUE", "NAO_ENTREGUE", "CANCELADA"}


class DeliveryApp:
    @staticmethod
    def _generated_route_name():
        return f"Rota gerada {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    def __init__(self, page: ft.Page):
        self.page = page
        self.api = ApiClient()
        self.geolocation_provider = GeolocationProvider()
        self.driver_location_tracking = DriverLocationTracking(
            self.geolocation_provider.get_position,
            self.api.publish_route_position,
            interval=15.0,
            on_error=self._handle_driver_tracking_error,
        )
        self.gps_tracking_state = "inativo"
        self.user = None
        self.websocket_client = None
        self._tracking_thread = None
        self._tracking_loop = None
        self._tracking_stop_event = None
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
        self.dashboard_map_view = None
        self.dashboard_initialized = False
        self.dashboard_screen_visible = False
        self.dashboard_metric_texts = []
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
        if self._remove_stale_vehicle_states():
            self._refresh_map_markers()
        if self.user is None or self.user.get("perfil") == "MOTORISTA":
            return
        try:
            data = self.api.request("GET", "/relatorios/dashboard")
            self.dashboard_data = data
            if (
                self.content.controls
                and getattr(self, "dashboard_active", False)
                and getattr(self, "dashboard_screen_visible", False)
                and getattr(self, "dashboard_initialized", False)
            ):
                self._update_dashboard_controls(data)
        except Exception:
            pass

    def _remove_stale_vehicle_states(self, now=None):
        current_time = now or datetime.now(timezone.utc)
        active_states = {}
        removed = False
        for vehicle_id, state in getattr(self, "vehicle_states", {}).items():
            timestamp = state.get("timestamp")
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                is_stale = (current_time - parsed).total_seconds() > TRACKING_STALE_AFTER_SECONDS
            except (AttributeError, TypeError, ValueError, OverflowError):
                is_stale = False
            if is_stale:
                removed = True
                continue
            active_states[vehicle_id] = state
        if removed:
            self.vehicle_states = active_states
        return removed

    def _start_dashboard_refresh_loop(self):
        if not getattr(self, "dashboard_active", False):
            return
        self.dashboard_refresh_controller.start()

    def _set_connection_state(self, state: str):
        self.websocket_state = state
        if getattr(self, "user", None) is not None and self.user.get("perfil") == "MOTORISTA":
            return
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

    def _connection_indicator_text(self):
        if getattr(self, "user", None) is not None and self.user.get("perfil") == "MOTORISTA":
            return ft.Text(
                self._gps_status_label(self.gps_tracking_state),
                color=ft.Colors.GREEN if self.gps_tracking_state == "gps_ativo" else ft.Colors.RED,
            )
        return ft.Text("● Desconectado", color=ft.Colors.RED)

    def _refresh_map_markers(self):
        if not getattr(self, "map_control", None):
            return
        markers = [build_marker(state) for state in self.vehicle_states.values() if state.get("latitude") is not None and state.get("longitude") is not None]
        try:
            if hasattr(self.map_control, "set_markers"):
                self.map_control.set_markers(markers)
        except Exception:
            pass

    def _ensure_dashboard_map(self, markers):
        if self.dashboard_map_view is None:
            self.dashboard_map_view = MapView(
                markers=markers,
                height=320,
                width=760,
                on_marker_click=self._select_route_marker,
                selected_marker_id=getattr(self, "selected_marker_id", None),
                title="Motoristas em atividade",
            )
            self.map_control = self.dashboard_map_view.build()
        else:
            self.dashboard_map_view.set_markers(markers)
        return self.map_control

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
        tracking_available = self._tracking_connection_available()
        websockets_available = websockets is not None
        user_present = bool(self.user)
        profile = self.user.get("perfil") if self.user else None
        token_present = bool(self.api.token)
        print(
            f"[ADMIN_WS] PRECHECK tracking_available={tracking_available} "
            f"websockets_available={websockets_available} user_present={user_present} "
            f"perfil={profile} token_present={token_present}"
        )
        ws_url = build_tracking_ws_url()
        print(
            f"[ADMIN_WS] CONNECT_REQUESTED perfil={profile} "
            f"API_BASE_URL={API_BASE_URL} URL={ws_url} token_present={token_present}"
        )
        if (
            not tracking_available
            or websockets is None
            or not self.user
            or profile == "MOTORISTA"
            or not token_present
        ):
            return

        def runner():
            print("[ADMIN_WS] THREAD_STARTED")
            self._set_connection_state("reconectando")
            while self.user is not None:
                try:
                    print(f"[ADMIN_WS] CONNECT_ATTEMPT URL={ws_url}")
                    async def _listen():
                        try:
                            async with websockets.connect(
                                ws_url,
                                additional_headers={"Authorization": f"Bearer {self.api.token}"},
                            ) as ws:
                                self.websocket_client = ws
                                self._tracking_loop = asyncio.get_running_loop()
                                self._tracking_stop_event = asyncio.Event()
                                print("[ADMIN_WS] CONNECTED")
                                self._set_connection_state("conectado")
                                async def consume_messages():
                                    async for raw_message in ws:
                                        if not raw_message:
                                            break
                                        try:
                                            data = json.loads(raw_message)
                                        except Exception:
                                            print("[TRACKING_ADMIN] mensagem ignorada motivo=json inválido")
                                            continue
                                        message_type = data.get("type") if isinstance(data, dict) else None
                                        print(
                                            f"[ADMIN_WS] MESSAGE_RECEIVED tamanho={len(raw_message)} "
                                            f"type={message_type}"
                                        )
                                        print("[ADMIN_WS] DISPATCH_TO_TRACKING_CLIENT")
                                        self.vehicle_states = update_vehicle_state(self.vehicle_states, data)
                                        self._refresh_map_markers()

                                consume_task = asyncio.create_task(consume_messages())
                                stop_task = asyncio.create_task(self._tracking_stop_event.wait())
                                done, pending = await asyncio.wait(
                                    {consume_task, stop_task},
                                    return_when=asyncio.FIRST_COMPLETED,
                                )
                                for task in pending:
                                    task.cancel()
                                await asyncio.gather(*pending, return_exceptions=True)
                                for task in done:
                                    if task is consume_task:
                                        task.result()
                                self._tracking_stop_event = None
                                self._tracking_loop = None
                                self.websocket_client = None
                        finally:
                            print("[ADMIN_WS] CONNECTION_CLOSED")

                    asyncio.run(_listen())
                except Exception as exc:
                    print(
                        f"[ADMIN_WS] CONNECT_FAILED exception_type={type(exc).__name__} "
                        f"exception_message={exc}"
                    )
                    self.websocket_client = None
                    self._tracking_loop = None
                    self._tracking_stop_event = None
                    if self.user is not None:
                        self._set_connection_state("reconectando")
                        print("[ADMIN_WS] RETRY delay=3")
                        time.sleep(3)
                    else:
                        break
            self.websocket_client = None
            if self.user is None:
                self._set_connection_state("desconectado")

        thread = threading.Thread(target=runner, daemon=True)
        self._tracking_thread = thread
        thread.start()

    def _tracking_connection_available(self):
        return self._tracking_thread is None or not self._tracking_thread.is_alive()

    def _disconnect_tracking_socket(self):
        self.user = None
        if self._tracking_stop_event is not None and self._tracking_loop is not None:
            self._tracking_loop.call_soon_threadsafe(self._tracking_stop_event.set)
        self._set_connection_state("desconectado")

    def _sync_driver_tracking(self, route):
        if not self.user or self.user.get("perfil") != "MOTORISTA":
            return
        if not route or route.get("status") != "EM_EXECUCAO":
            self.driver_location_tracking.stop()
            self._set_gps_tracking_state("inativo")
            return
        vehicle = route.get("veiculo") or {}
        vehicle_id = route.get("veiculo_id") or vehicle.get("id")
        try:
            self.driver_location_tracking.start(route.get("id"), route.get("status"), vehicle_id)
            self._set_gps_tracking_state("gps_ativo")
        except GeolocationPermissionDenied:
            self._set_gps_tracking_state("aguardando_permissao")
        except GeolocationServiceUnavailable:
            self._set_gps_tracking_state("localizacao_indisponivel")
        except ValueError:
            self._set_gps_tracking_state("inativo")

    def _stop_driver_tracking(self):
        if getattr(self, "driver_location_tracking", None) is not None:
            self.driver_location_tracking.stop()
        self._set_gps_tracking_state("inativo")

    def _handle_driver_tracking_error(self, error):
        if isinstance(error, GeolocationPermissionDenied):
            self._set_gps_tracking_state("aguardando_permissao")
        elif isinstance(error, GeolocationServiceUnavailable):
            self._set_gps_tracking_state("localizacao_indisponivel")
        else:
            self._set_gps_tracking_state("erro_temporario")

    def _set_gps_tracking_state(self, state):
        self.gps_tracking_state = state
        if (
            getattr(self, "user", None) is not None
            and self.user.get("perfil") == "MOTORISTA"
            and getattr(self, "connection_indicator", None) is not None
        ):
            self.connection_indicator.content = self._connection_indicator_text()
        status_text = getattr(self, "gps_status_text", None)
        if status_text is not None:
            status_text.value = self._gps_status_label(state)
            try:
                status_text.update()
            except AssertionError:
                pass

    @staticmethod
    def _gps_status_label(state):
        return {
            "gps_ativo": "GPS ativo",
            "aguardando_permissao": "Aguardando permissão de localização",
            "localizacao_indisponivel": "Localização indisponível",
            "erro_temporario": "Erro temporário no envio da localização",
            "inativo": "GPS inativo",
        }.get(state, "GPS inativo")

    def notify(self, message: str, error=False):
        color = ft.Colors.RED_700 if error else ft.Colors.GREEN_700

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
        
        # Sidebar diferenciada por perfil
        if driver:
            # MOTORISTA: Dashboard, Minhas Rotas, Perfil
            destinations = [
                ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD, label="Dashboard"),
                ft.NavigationRailDestination(icon=ft.Icons.TRIP_ORIGIN, label="Minhas Rotas"),
                ft.NavigationRailDestination(icon=ft.Icons.PERSON, label="Perfil"),
            ]
        else:
            # ADMIN/GESTOR: Dashboard, Gestão de Entregas, Rotas, Pedidos, Clientes, etc
            destinations = [
                ft.NavigationRailDestination(icon=ft.Icons.DASHBOARD, label="Dashboard"),
                ft.NavigationRailDestination(icon=ft.Icons.LOCAL_SHIPPING, label="Gestão de Entregas"),
                ft.NavigationRailDestination(icon=ft.Icons.TRIP_ORIGIN, label="Rotas"),
            ]
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

            # Ações diferenciadas por perfil
            if driver:
                # MOTORISTA: Dashboard, Minhas Rotas, Perfil
                actions = [self.dashboard_view, self.minhas_rotas_view, self.profile_view]
            else:
                # ADMIN/GESTOR
                actions = [self.dashboard_view, self.delivery_management_view, self.routes_view]
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
                self.dashboard_screen_visible = selected_index == 0
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
            content=self._connection_indicator_text(),
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
        if driver and self.geolocation_provider.control not in self.page.overlay:
            self.page.overlay.append(self.geolocation_provider.control)
        self.page.on_disconnect = lambda _: self._stop_driver_tracking()
        self.page.add(ft.Row([rail, ft.VerticalDivider(width=1), self.content], expand=True))
        self.dashboard_active = True
        self.dashboard_screen_visible = True
        self._start_dashboard_refresh_loop()
        self.dashboard_view()

    def logout(self):
        self._stop_driver_tracking()
        self.api.token = None
        self.user = None
        self.dashboard_active = False
        self.dashboard_screen_visible = False
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

    def _update_dashboard_controls(self, data):
        values = get_dashboard_indicator_values(data)
        for key, control in getattr(self, "dashboard_metric_texts", []):
            control.value = str(values.get(key, 0))
        self._refresh_map_markers()
        self.page.update()

    def dashboard_view(self):
        if self.user["perfil"] == "MOTORISTA":
            self.driver_dashboard_view()
            return
        try:
            data = self.dashboard_data or self.api.request("GET", "/relatorios/dashboard")
            self.dashboard_data = data
            indicator_values = get_dashboard_indicator_values(data)
            cards = []
            self.dashboard_metric_texts = []
            for (label, key), icon in zip(DASHBOARD_INDICATORS, [
                ft.Icons.CALENDAR_TODAY,
                ft.Icons.CHECK_CIRCLE,
                ft.Icons.ROUTE,
                ft.Icons.WARNING,
                ft.Icons.DIRECTIONS_RUN,
                ft.Icons.DIRECTIONS_CAR,
                ft.Icons.PERSON,
            ]):
                metric_text = ft.Text(str(indicator_values.get(key, 0)), size=28, weight=ft.FontWeight.BOLD)
                self.dashboard_metric_texts.append((key, metric_text))
                cards.append(ft.Container(
                    ft.Column([
                        ft.Icon(icon, color=ft.Colors.INDIGO),
                        metric_text,
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
            map_control = self._ensure_dashboard_map(dashboard_markers)
            graph_panel = lambda chart: ft.Container(
                chart,
                width=360,
                height=180,
                padding=12,
                border_radius=14,
                bgcolor=ft.Colors.WHITE,
                shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
            )

            self.content.controls = [
                self.header_bar("Dashboard", "Indicadores e monitoramento operacional"),
                ft.Container(ft.Row(cards, wrap=True, spacing=12), padding=20),
                ft.Container(ft.Row([
                    graph_panel(status_chart),
                    graph_panel(driver_chart),
                ], wrap=True, spacing=12), padding=20),
                ft.Container(ft.Row([
                    graph_panel(vehicle_chart),
                    graph_panel(evolution_chart),
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
                    ft.Container(ft.Column([ft.Text("Últimas entregas", weight=ft.FontWeight.BOLD)] + (latest_deliveries or [ft.Text("Nenhuma entrega encontrada.")]), tight=True), width=360, height=180, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                    ft.Container(ft.Column([ft.Text("Próximas rotas", weight=ft.FontWeight.BOLD)] + (next_routes or [ft.Text("Nenhuma rota agendada.")]), tight=True), width=360, height=180, padding=12, border_radius=14, bgcolor=ft.Colors.WHITE, shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12)),
                ], wrap=True, spacing=12), padding=20),
            ]
            self.dashboard_initialized = True
            self.page.update()
            self.dashboard_screen_visible = True
        except ApiError as exc:
            self.notify(str(exc), True)

    # ===================================================================
    # Phase 2: Driver Dashboard
    # ===================================================================

    def driver_dashboard_view(self):
        """
        Dashboard exclusivo para motoristas.
        Exibe saudação, veículo, indicadores e próxima missão.
        
        Suporta estado vazio quando motorista não tem rota atribuída (404).
        """
        try:
            daily_summary = self.api.request("GET", "/rotas/motorista/resumo-diario")
            current_route = None
            if daily_summary.get("rota_atual"):
                current_route = self.api.request("GET", "/rotas/motorista/atual")

            greeting_card = self._build_driver_greeting()
            vehicle_card = self._build_driver_vehicle_card(current_route, daily_summary)
            indicator_cards = self._build_driver_indicators(current_route, daily_summary)
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
            # Erro real (não 404)
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

    def _build_driver_vehicle_card(self, current_route, daily_summary=None) -> ft.Container:
        """
        Card com informações do veículo vinculado à rota ativa.
        Se não há rota ativa, mostra placeholder.
        """
        vehicle_info = "--"
        vehicle = current_route.get("veiculo") if current_route else None
        if not vehicle and daily_summary:
            vehicle = daily_summary.get("veiculo_atual")
        if vehicle:
            placa = vehicle.get("placa", "--")
            modelo = vehicle.get("modelo", "--")
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

    @staticmethod
    def _format_dashboard_distance(value):
        if value is None or float(value) == 0:
            return "0 km"
        return f"{float(value):.1f}".replace(".", ",") + " km"

    @staticmethod
    def _format_dashboard_duration(value):
        total_minutes = int(value or 0)
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"{hours}h {minutes}min"
        return f"{minutes} min"

    def _build_driver_indicators(self, current_route, daily_summary=None) -> list:
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

        if daily_summary is not None:
            indicators[0]["value"] = str(daily_summary.get("entregas_concluidas_hoje", 0))
            indicators[1]["value"] = str(daily_summary.get("entregas_pendentes", 0))
            indicators[2]["value"] = self._format_dashboard_distance(daily_summary.get("distancia_hoje_km", 0))
            indicators[3]["value"] = self._format_dashboard_duration(daily_summary.get("tempo_em_rota_hoje_minutos", 0))
        elif current_route:
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
            if not current_route:
                self.notify("Nenhuma rota ativa para iniciar.", True)
                return
            try:
                self.driver_route_view(current_route.get("id"))
            except Exception as exc:
                self.notify("Não foi possível abrir a rota ativa.", True)

        if not current_route:
            # Rota não disponível - estado vazio
            mission_content = ft.Column([
                ft.Icon(ft.Icons.TRIP_ORIGIN, size=48, color=ft.Colors.GREY_400),
                ft.Text("Nenhuma rota atribuída no momento", size=16, weight=ft.FontWeight.BOLD),
                ft.Text("Sua rota será preparada em breve.", color=ft.Colors.GREY_700),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)
        else:
            # Rota ativa disponível
            mission_label = "Iniciar Rota" if current_route.get("status") == "PRONTA" else "Continuar Rota"
            route_id = current_route.get("id", "--")
            route_name = current_route.get("nome", "--")
            status = current_route.get("status", "--").replace("_", " ")

            organization = current_route.get("organizacao") or current_route.get("origem") or {}
            org_name = organization.get("nome") if isinstance(organization, dict) else "Operação não informada"
            if not org_name:
                org_name = "Operação não informada"

            entregas = current_route.get("entregas", [])
            num_entregas = len(entregas)

            proxima_entrega_text = "Nenhuma entrega pendente"
            next_stop = None
            for entrega in entregas:
                if entrega.get("status") not in TERMINAL_DELIVERY_STATUSES:
                    next_stop = entrega
                    break

            if next_stop:
                destino = next_stop.get("destino") or {}
                next_address = (
                    destino.get("endereco_formatado")
                    or next_stop.get("endereco_destino_formatado")
                    or destino.get("logradouro")
                    or "Endereço não informado"
                )
                proxima_entrega_text = next_address
            
            # Distância e duração (previstos do backend)
            # Backend retorna: distancia_prevista (float em km), duracao_prevista (float em horas)
            distance = current_route.get("distancia_prevista", "--")
            duration = current_route.get("duracao_prevista", "--")
            if duration != "--":
                # Converter de horas (float) para formato "X h Y m"
                total_minutes = int(float(duration) * 60)
                hours = total_minutes // 60
                minutes = total_minutes % 60
                duration = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
            else:
                duration = "--"
            
            # Formatar distância
            if distance != "--":
                distance = f"{float(distance):.2f}"
            else:
                distance = "--"

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
                    ft.Text("Próxima parada", size=12, color=ft.Colors.GREY_700),
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
                        mission_label,
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
    # Phase 3: Driver Route View
    # ===================================================================
    def driver_route_view(self, route_id: int | None = None, loading_confirmed: bool = False):
        """
        Tela da rota ativa para o motorista.
        Exibe a rota, o mapa, próxima parada real e sequência de entregas com dados reais de cliente e endereço.
        """
        try:
            # Motorista deve sempre seguir o payload enriquecido da rota ativa do próprio motorista.
            # O endpoint /rotas/{id} não traz os dados completos da rota do motorista em forma de payload
            # compatível com a tela de Rota Ativa (route_geometry + entregas detalhadas + cliente/endereço).
            if self.user.get("perfil") == "MOTORISTA":
                route = self.api.request("GET", "/rotas/motorista/atual")
                route_id = route.get("id")
            elif route_id is None:
                route = self.api.request("GET", "/rotas/motorista/atual")
                route_id = route.get("id")
            else:
                route = self.api.request("GET", f"/rotas/{route_id}")

            if not route:
                self._stop_driver_tracking()
                self.notify("Nenhuma rota ativa encontrada.", True)
                return

            loading_confirmed = bool(route.get("carga_confirmada", False))

            # Obter dados reais de cliente e endereço para cada parada
            stops = self._driver_route_snapshot(route)
            next_stop = self._next_driver_stop(route)
            route_status = route.get("status", "PRONTA")
            self._sync_driver_tracking(route)

            cliente_nome = None
            endereco = None

            if next_stop:
                cliente = next_stop.get("cliente")
                if cliente:
                    cliente_nome = cliente.get("nome")

            if not cliente_nome and next_stop:
                cliente_nome = self._resolve_cliente_nome(next_stop)

            if not cliente_nome and next_stop:
                cliente_nome = f"Pedido #{next_stop.get('pedido_id')}"

            if not cliente_nome:
                cliente_nome = "Cliente não informado"

            if next_stop:
                endereco = next_stop.get("destino") or next_stop.get("address") or {}
            if not endereco:
                for stop in stops:
                    if stop.get("delivery", {}).get("status") not in TERMINAL_DELIVERY_STATUSES:
                        endereco = stop.get("address") or stop.get("destino") or {}
                        break

            # Mapa real com tiles OSM, marcadores do payload e route_geometry.
            operation_name = (route.get("organizacao") or {}).get("nome") or "Operação não informada"
            route_map = self._render_driver_map_native(route, stops, next_stop)

            # Cards de paradas com dados reais de cliente e endereço
            stop_cards = []
            for index, stop in enumerate(stops, start=1):
                delivery = stop.get("delivery", {})
                cliente = stop.get("cliente", {})
                address = stop.get("address", {})
                is_next = next_stop and stop["delivery"]["id"] == next_stop["delivery"]["id"]
                delivery_status = delivery.get("status", "AGUARDANDO_COLETA")

                client_name = self._driver_stop_label(stop)
                formatted_address = self._driver_stop_address(stop)

                stop_cards.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Container(
                                content=ft.Text(str(index), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                width=38,
                                height=38,
                                alignment=ft.alignment.center,
                                border_radius=19,
                                bgcolor=ft.Colors.INDIGO if is_next else ft.Colors.GREY_400,
                            ),
                            ft.Column([
                                ft.Text(f"Parada {index}: {client_name}", size=12, weight=ft.FontWeight.BOLD),
                                ft.Text(formatted_address, size=11, color=ft.Colors.GREY_700),
                                ft.Text(f"Status: {delivery_status.replace('_', ' ')} • Pedido: #{delivery.get('pedido_id', '--')}", size=10, color=ft.Colors.GREY_600),
                            ], spacing=2, expand=True),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        padding=14,
                        border_radius=12,
                        bgcolor=ft.Colors.INDIGO_50 if is_next else ft.Colors.WHITE,
                        border=ft.border.all(1, ft.Colors.INDIGO if is_next else ft.Colors.GREY_300),
                        margin=ft.margin.only(bottom=8),
                    )
                )

            # Botões contextuais por status
            action_buttons = []
            if route_status in {"PRONTA", "PLANEJADA", "AGUARDANDO_MOTORISTA", "AGUARDANDO_VEICULO"}:
                def verify_load_click(_):
                    self.loading_order_dialog(route, stops)

                if not loading_confirmed:
                    action_buttons.append(
                        ft.FilledButton(
                            "Verificar carga",
                            icon=ft.Icons.CHECKLIST,
                            expand=True,
                            on_click=verify_load_click,
                        )
                    )
                
                start_button = ft.FilledButton(
                    "Iniciar viagem",
                    icon=ft.Icons.PLAY_ARROW,
                    expand=True,
                    disabled=not loading_confirmed,
                    on_click=lambda _: self._start_route_execution(route),
                )
                action_buttons.append(start_button)
                
                if loading_confirmed:
                    action_buttons.append(
                        ft.OutlinedButton(
                            "Revisar carga",
                            icon=ft.Icons.EDIT,
                            expand=True,
                            on_click=lambda _: self.loading_order_dialog(route, stops, review_only=True),
                        )
                    )
            elif route_status == "EM_EXECUCAO":
                action_buttons.append(
                    ft.FilledButton(
                        "Pausar rota",
                        icon=ft.Icons.PAUSE,
                        expand=True,
                        on_click=lambda _: self.change_route_status(route, "PAUSADA", event="PAUSA", observation="Pausada pelo motorista", stay_in_view=True),
                    )
                )
                if next_stop:
                    action_buttons.append(
                        ft.OutlinedButton(
                            "Entregue",
                            icon=ft.Icons.DONE,
                            expand=True,
                            on_click=lambda _: self.receipt_dialog(next_stop.get("delivery", {}).get("id"), route.get("id")),
                        )
                    )
                    action_buttons.append(
                        ft.OutlinedButton(
                            "Não entregue",
                            icon=ft.Icons.CANCEL,
                            expand=True,
                            on_click=lambda _: self._mark_delivery_as_not_delivered(route, next_stop),
                        )
                    )
                    action_buttons.append(
                        ft.OutlinedButton(
                            "Registrar ocorrência",
                            icon=ft.Icons.REPORT_PROBLEM,
                            expand=True,
                            on_click=lambda _: self.incident_dialog({"id": next_stop.get("delivery", {}).get("id")}),
                        )
                    )
            elif route_status == "PAUSADA":
                action_buttons.append(
                    ft.FilledButton(
                        "Retomar rota",
                        icon=ft.Icons.PLAY_ARROW,
                        expand=True,
                        on_click=lambda _: self.change_route_status(route, "EM_EXECUCAO", event="RETOMADA", observation="Retomada pelo motorista", stay_in_view=True),
                    )
                )
            elif route_status not in {"FINALIZADA", "CANCELADA"}:
                action_buttons.append(
                    ft.OutlinedButton(
                        "Finalizar rota",
                        icon=ft.Icons.FLAG,
                        expand=True,
                        on_click=lambda _: self.change_route_status(route, "FINALIZADA", event="FINALIZADA", observation="Finalizada pelo motorista", stay_in_view=True),
                    )
                )

            # Próxima parada real
            next_stop_text = "Nenhuma entrega pendente"
            next_stop_address = "-"
            if next_stop:
                next_stop_text = cliente_nome or self._driver_stop_label(next_stop)
                next_stop_address = self._format_driver_address(endereco) if endereco else self._driver_stop_address(next_stop)

            origin = route.get("origem") or {}
            origin_text = self._format_driver_address(origin) if origin else "Origem não informada"
            if not origin_text or origin_text == "Endereço não informado":
                origin_text = "Origem não informada"

            current_destination = self._format_driver_address(endereco) if endereco else "Destino não informado"
            self.gps_status_text = ft.Text(
                self._gps_status_label(self.gps_tracking_state),
                size=12,
                color=ft.Colors.GREY_700,
            )

            self.content.controls = [
                self.header_bar("Rota Ativa", f"#{route.get('id')} · {route.get('nome', 'Rota')}", actions=[
                    ft.TextButton("Voltar", icon=ft.Icons.ARROW_BACK, on_click=lambda _: self.dashboard_view()),
                ]),
                ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Column([
                                ft.Text("Operação", size=12, color=ft.Colors.GREY_700),
                                ft.Text(operation_name, size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO),
                            ]),
                            ft.Column([
                                ft.Text("Status", size=12, color=ft.Colors.GREY_700),
                                ft.Text(route_status.replace("_", " "), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO),
                            ]),
                        ], spacing=24),
                        self.gps_status_text,
                        ft.Text(f"Origem: {origin_text}", size=11, color=ft.Colors.GREY_700, selectable=True),
                        ft.Text(f"Destino atual: {current_destination}", size=11, color=ft.Colors.GREY_700, selectable=True),
                        ft.Divider(height=12),
                        ft.Row([
                            ft.Column([
                                ft.Text("Próxima parada", size=12, color=ft.Colors.GREY_700),
                                ft.Text(next_stop_text, size=14, weight=ft.FontWeight.BOLD),
                            ], expand=True),
                        ], spacing=24),
                        ft.Text(next_stop_address, size=11, color=ft.Colors.GREY_600, selectable=True),
                        ft.Divider(height=16),
                        route_map,
                        *([ft.Divider(height=10)] if action_buttons else []),
                        *([ft.Column(action_buttons, spacing=12)] if action_buttons else []),
                    ], spacing=12),
                    padding=20,
                    border_radius=14,
                    bgcolor=ft.Colors.WHITE,
                    shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
                ),
                ft.Container(
                    content=ft.Column([
                        ft.Text("Sequência de entregas", size=18, weight=ft.FontWeight.BOLD),
                        *(stop_cards if stop_cards else [ft.Text("Nenhuma entrega nesta rota.", color=ft.Colors.GREY_600)]),
                    ], tight=True),
                    padding=20,
                    margin=ft.margin.only(top=10),
                    border_radius=14,
                    bgcolor=ft.Colors.WHITE,
                    shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
                ),
            ]
            self.page.update()
        except ApiError as exc:
            if route_id is not None and self._is_expected_route_completion_error(str(exc)):
                try:
                    completed_route = self._load_completed_route(route_id)
                    if completed_route.get("status") in {"FINALIZADA", "CONCLUIDA"}:
                        self._render_completed_route_view(completed_route)
                        return
                except ApiError:
                    pass
            self.notify(str(exc), True)

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

    def minhas_rotas_view(self):
        """
        View exclusiva para MOTORISTA.
        Mostra rota atual (PRONTA, EM_EXECUCAO, PAUSADA) e histórico (FINALIZADA, CANCELADA).
        """
        try:
            routes = self.api.request("GET", "/rotas?limit=100&offset=0")
        except ApiError as exc:
            self.notify(str(exc), True)
            return

        # Separar rotas por categoria
        current_route_statuses = {"PRONTA", "EM_EXECUCAO", "PAUSADA"}
        current_routes = [r for r in routes if r["status"] in current_route_statuses]
        history_statuses = {"FINALIZADA", "CANCELADA"}
        history_routes = [r for r in routes if r["status"] in history_statuses]

        content_items = []

        # =====================================================================
        # SEÇÃO 1: ROTA ATUAL
        # =====================================================================
        if current_routes:
            # Usar primeira rota atual (motorista deve ter apenas uma)
            current_route = current_routes[0]
            
            def handle_open_route(_):
                self.driver_route_view(current_route.get("id"))

            def handle_change_status(new_status):
                def _handler(_):
                    self.change_route_status(current_route, new_status, stay_in_view=True)
                return _handler

            # Determinar botão principal conforme status
            primary_button = None
            if current_route["status"] in {"PRONTA", "PLANEJADA", "AGUARDANDO_MOTORISTA"}:
                primary_button = ft.FilledButton(
                    "Abrir rota",
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=handle_open_route,
                )
            elif current_route["status"] in {"EM_EXECUCAO", "PAUSADA"}:
                primary_button = ft.FilledButton(
                    "Continuar rota",
                    icon=ft.Icons.PLAY_ARROW,
                    on_click=handle_open_route,
                )

            # Card de rota atual
            entregas_list = current_route.get("entregas", [])
            num_entregas = len(entregas_list)
            concluidas = sum(1 for e in entregas_list if e.get("status") == "ENTREGUE")
            progresso = int(current_route.get("progresso_percentual") or 0)
            distancia_fmt = self._route_distance_display(current_route)
            duracao_fmt = self._route_duration_display(current_route)

            current_section = ft.Container(
                content=ft.Column([
                    ft.Text("ROTA ATUAL", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO),
                    ft.Divider(),
                    ft.Row([
                        ft.Column([
                            ft.Text("Nome", size=12, color=ft.Colors.GREY_700),
                            ft.Text(current_route.get("nome", "--"), size=14, weight=ft.FontWeight.BOLD),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("Status", size=12, color=ft.Colors.GREY_700),
                            ft.Text(current_route.get("status", "--").replace("_", " ").title(), size=14, weight=ft.FontWeight.BOLD),
                        ], spacing=2),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, expand=True, spacing=20),
                    ft.Row([
                        ft.Column([
                            ft.Text("Veículo", size=12, color=ft.Colors.GREY_700),
                            ft.Text(str(current_route.get("veiculo_id") or "--"), size=14),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("Entregas", size=12, color=ft.Colors.GREY_700),
                            ft.Text(f"{concluidas}/{num_entregas}", size=14),
                        ], spacing=2),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, expand=True, spacing=20),
                    ft.Row([
                        ft.Column([
                            ft.Text("Progresso", size=12, color=ft.Colors.GREY_700),
                            ft.Text(f"{progresso}%", size=14),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("Distância", size=12, color=ft.Colors.GREY_700),
                            ft.Text(distancia_fmt, size=14),
                        ], spacing=2),
                        ft.Column([
                            ft.Text("Duração", size=12, color=ft.Colors.GREY_700),
                            ft.Text(duracao_fmt, size=14),
                        ], spacing=2),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, expand=True, spacing=20),
                    ft.ProgressBar(value=min(max(progresso / 100, 0), 1), bar_height=8),
                    ft.Row([
                        primary_button,
                        ft.IconButton(
                            ft.Icons.PAUSE,
                            tooltip="Pausar" if current_route["status"] == "EM_EXECUCAO" else "Retomar",
                            visible=current_route["status"] in {"EM_EXECUCAO", "PAUSADA"},
                            on_click=handle_change_status("PAUSADA" if current_route["status"] == "EM_EXECUCAO" else "EM_EXECUCAO"),
                        ),
                    ], spacing=12),
                ], spacing=12),
                padding=20,
                border_radius=16,
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(2, ft.Colors.INDIGO_200),
                shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
            )
            content_items.append(current_section)
        else:
            # Sem rota atual
            no_route_section = ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.TRIP_ORIGIN, size=48, color=ft.Colors.GREY_400),
                    ft.Text("Sem rota ativa no momento", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text("Sua próxima rota será atribuída em breve.", color=ft.Colors.GREY_700),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
                padding=40,
                border_radius=16,
                bgcolor=ft.Colors.GREY_100,
            )
            content_items.append(no_route_section)

        # =====================================================================
        # SEÇÃO 2: HISTÓRICO
        # =====================================================================
        if history_routes:
            content_items.append(ft.Text("HISTÓRICO", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO))
            content_items.append(ft.Divider())

            for route in history_routes:
                entregas = route.get("entregas", [])
                num_entregas = len(entregas)
                progresso = int(route.get("progresso_percentual") or 0)
                distancia = self._route_distance_display(route)
                duracao = self._route_duration_display(route)

                def handle_view_details(route_obj):
                    def _handler(_):
                        self.route_details_dialog(route_obj)
                    return _handler

                history_item = ft.ListTile(
                    leading=ft.Icon(
                        ft.Icons.DONE if route["status"] == "FINALIZADA" else ft.Icons.CANCEL,
                        color=ft.Colors.GREEN if route["status"] == "FINALIZADA" else ft.Colors.RED,
                    ),
                    title=ft.Text(f"{route.get('nome', '--')} · {route.get('status', '--').replace('_', ' ').title()}"),
                    subtitle=ft.Text(
                        f"Data: {self._format_iso_datetime(route.get('data_planejada'))} | "
                        f"Entregas: {num_entregas} | Progresso: {progresso}% | "
                        f"Distância: {distancia} | Duração: {duracao}"
                    ),
                    trailing=ft.IconButton(
                        ft.Icons.INFO,
                        tooltip="Ver detalhes",
                        on_click=handle_view_details(route),
                    ),
                )
                content_items.append(history_item)

        self.content.controls = [
            self.header_bar("Minhas Rotas", "Sua operação de entregas"),
        ] + content_items

        self.page.update()

    def route_status_options(self):
        return [
            "PLANEJADA", "AGUARDANDO_MOTORISTA", "AGUARDANDO_VEICULO",
            "PRONTA", "EM_EXECUCAO", "PAUSADA", "FINALIZADA", "CANCELADA",
        ]

    @staticmethod
    def _format_iso_datetime(value):
        if value is None or value == "":
            return "--"
        if not isinstance(value, str):
            return str(value)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _route_distance_display(route):
        value = route.get("distancia_real")
        if value is None or float(value or 0) <= 0:
            value = route.get("distancia_prevista")
        if value is None or float(value or 0) <= 0:
            return "--"
        return f"{float(value):.2f}".replace(".", ",") + " km"

    @staticmethod
    def _route_duration_display(route):
        value = route.get("duracao_real")
        if value is None or float(value or 0) <= 0:
            value = route.get("duracao_prevista")
        if value is None or float(value or 0) <= 0:
            return "--"
        total_minutes = round(float(value) * 60)
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"{hours} h {minutes} min"
        return f"{minutes} min"

    def profile_view(self):
        """
        View exclusiva para MOTORISTA.
        Mostra dados pessoais do usuário logado.
        """
        user = self.user or {}
        
        profile_fields = [
            ("Nome", user.get("nome", "--")),
            ("Email", user.get("email", "--")),
            ("Telefone", user.get("telefone") or "--"),
            ("Perfil", user.get("perfil", "--")),
            ("Organização", (user.get("organizacao") or {}).get("nome") or "--"),
            ("Ativo", "Sim" if user.get("ativo") else "Não"),
        ]

        profile_items = []
        for label, value in profile_fields:
            profile_items.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(label, size=12, color=ft.Colors.GREY_700, weight=ft.FontWeight.BOLD),
                        ft.Text(value, size=14, selectable=True),
                    ], spacing=4),
                    padding=16,
                    border_radius=12,
                    bgcolor=ft.Colors.GREY_100,
                )
            )

        self.content.controls = [
            self.header_bar("Perfil", "Informações pessoais"),
            ft.Container(
                content=ft.Column(
                    [
                        ft.Container(
                            content=ft.Column([
                                ft.Icon(ft.Icons.PERSON, size=48, color=ft.Colors.INDIGO),
                                ft.Text(user.get("nome", "Motorista"), size=24, weight=ft.FontWeight.BOLD),
                            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                            padding=20,
                            border_radius=16,
                            bgcolor=ft.Colors.INDIGO_50,
                        ),
                        ft.Text("Dados Pessoais", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.INDIGO),
                        ft.Column(profile_items, spacing=12),
                        ft.Divider(),
                        ft.FilledButton(
                            "Sair",
                            icon=ft.Icons.LOGOUT,
                            on_click=lambda _: self.logout(),
                            bgcolor=ft.Colors.RED_700,
                        ),
                    ],
                    spacing=16,
                ),
                padding=20,
            ),
        ]
        self.page.update()

    def _sorted_route_entries(self, route):
        entries = list(route.get("entregas") or [])
        return sorted(entries, key=lambda item: (
            int(item.get("sequencia_otimizada") or item.get("ordem_visita") or 0),
            int(item.get("entrega_id") or item.get("id") or 0),
        ))

    @staticmethod
    def _generic_pedido_name(value):
        if not isinstance(value, str):
            return False
        return value.startswith("Pedido #")

    def _resolve_cliente_payload_from_pedido(self, pedido_id):
        if pedido_id is None:
            return None
        try:
            pedido = self.api.request("GET", f"/pedidos/{pedido_id}")
            cliente_id = pedido.get("cliente_id")
            return {"id": cliente_id, "nome": f"Pedido #{pedido_id}"} if cliente_id is not None else None
        except ApiError:
            return None

    def _load_client_lookup(self, orders):
        clients = self.api.request("GET", "/clientes")
        clients_by_id = {client["id"]: client for client in clients}
        addresses_by_client = {}
        for order in orders:
            client_id = order.get("cliente_id")
            if client_id is None or client_id in addresses_by_client:
                continue
            addresses_by_client[client_id] = self.api.request("GET", f"/clientes/{client_id}/enderecos")
        return clients_by_id, addresses_by_client

    @staticmethod
    def _driver_route_payload_snapshot(route):
        snapshot = []
        entries = list(route.get("entregas") or [])
        if not entries and route.get("proxima_entrega"):
            entries = [route.get("proxima_entrega")]

        for entry in sorted(entries, key=lambda item: (
            int(item.get("sequencia_otimizada") or item.get("ordem_visita") or 0),
            int(item.get("entrega_id") or item.get("id") or 0),
        )):
            delivery_id = entry.get("entrega_id") or entry.get("id")
            if delivery_id is None:
                continue

            delivery = {
                "id": delivery_id,
                "pedido_id": entry.get("pedido_id"),
                "status": entry.get("status") or "AGUARDANDO_COLETA",
            }
            address = entry.get("destino") or entry.get("address") or {}
            cliente = entry.get("cliente") or {}
            nome = cliente.get("nome") if isinstance(cliente, dict) else None
            if not cliente or DeliveryApp._generic_pedido_name(nome):
                pedido_id = entry.get("pedido_id")
                if pedido_id is not None:
                    cliente = {"nome": f"Pedido #{pedido_id}"}
                else:
                    cliente = {"nome": f"Entrega #{delivery_id}"}
            snapshot.append({
                "entry": entry,
                "delivery": delivery,
                "cliente": cliente,
                "address": address,
                "order": int(entry.get("sequencia_otimizada") or entry.get("ordem_visita") or 0),
            })
        return snapshot

    def _driver_route_snapshot(self, route):
        payload_snapshot = self._driver_route_payload_snapshot(route)
        if payload_snapshot:
            return payload_snapshot

        snapshot = []
        entries = list(route.get("entregas") or [])
        if not entries:
            try:
                entries = self.api.request("GET", f"/rotas/{route['id']}/sequencia-carregamento")
            except ApiError:
                return []

        for entry in self._sorted_route_entries({"entregas": entries}):
            delivery_id = entry.get("entrega_id") or entry.get("id")
            if delivery_id is None:
                continue
            try:
                delivery = self.api.request("GET", f"/entregas/{delivery_id}")
                pedido = self.api.request("GET", f"/pedidos/{delivery['pedido_id']}")
                cliente = self.api.request("GET", f"/clientes/{pedido['cliente_id']}")
                addresses = self.api.request("GET", f"/clientes/{pedido['cliente_id']}/enderecos")
                address = None
                if delivery.get("endereco_destino_id") is not None:
                    address = next((item for item in addresses if item["id"] == delivery.get("endereco_destino_id")), None)
                if address is None and pedido.get("endereco_entrega_id") is not None:
                    address = next((item for item in addresses if item["id"] == pedido.get("endereco_entrega_id")), None)
                if address is None:
                    address = next(iter(addresses), None)
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

    @staticmethod
    def _next_driver_stop_from_payload(route):
        if route.get("entregas"):
            for stop in DeliveryApp._driver_route_payload_snapshot(route):
                if stop["delivery"]["status"] not in TERMINAL_DELIVERY_STATUSES:
                    return stop
            return None

        payload = route.get("proxima_entrega")
        if payload and payload.get("status") not in TERMINAL_DELIVERY_STATUSES:
            delivery_id = payload.get("entrega_id") or payload.get("id")
            if delivery_id is not None:
                address = payload.get("destino") or payload.get("address") or {}
                delivery = {
                    "id": delivery_id,
                    "pedido_id": payload.get("pedido_id"),
                    "status": payload.get("status") or "AGUARDANDO_COLETA",
                }
                cliente = payload.get("cliente") or {}
                nome = cliente.get("nome") if isinstance(cliente, dict) else None
                if not cliente or DeliveryApp._generic_pedido_name(nome):
                    pedido_id = payload.get("pedido_id")
                    cliente = {"nome": f"Pedido #{pedido_id}" if pedido_id is not None else f"Entrega #{delivery_id}"}
                return {
                    "entry": payload,
                    "delivery": delivery,
                    "cliente": cliente,
                    "address": address,
                    "order": int(payload.get("sequencia_otimizada") or payload.get("ordem_visita") or 0),
                }

        for stop in DeliveryApp._driver_route_payload_snapshot(route):
            if stop["delivery"]["status"] not in TERMINAL_DELIVERY_STATUSES:
                return stop
        return None

    def _next_driver_stop(self, route):
        payload_next = self._next_driver_stop_from_payload(route)
        if payload_next is not None:
            return payload_next
        for stop in self._driver_route_snapshot(route):
            if stop["delivery"]["status"] not in TERMINAL_DELIVERY_STATUSES:
                return stop
        return None

    def _resolve_cliente_nome(self, next_stop):
        if not next_stop:
            return None
        cliente = next_stop.get("cliente") or {}
        nome = cliente.get("nome") or cliente.get("razao_social") or cliente.get("fantasia")
        if nome and not self._generic_pedido_name(str(nome)):
            return str(nome)
        pedido_id = next_stop.get("pedido_id") or next_stop.get("entrega_id")
        return f"Pedido #{pedido_id}" if pedido_id is not None else "Cliente não informado"

    @staticmethod
    def _driver_stop_label(stop: dict | None):
        if not stop:
            return "Cliente não informado"
        cliente = stop.get("cliente") or {}
        nome = cliente.get("nome") or cliente.get("razao_social") or cliente.get("fantasia")
        if nome:
            return str(nome)
        delivery = stop.get("delivery") or {}
        pedido_id = delivery.get("pedido_id")
        if pedido_id is not None:
            return f"Pedido #{pedido_id}"
        return "Cliente não informado"

    @staticmethod
    def _driver_stop_address(stop: dict | None):
        if not stop:
            return "Endereço não informado"
        address = stop.get("address") or {}
        if not address:
            base = stop.get("destino") or {}
            address = base
        return DeliveryApp._format_driver_address(address)

    @staticmethod
    def _format_driver_address(address: dict | None):
        if not address:
            return "Endereço não informado"
        parts = []
        logradouro = address.get("logradouro") or ""
        numero = address.get("numero") or ""
        if logradouro or numero:
            parts.append(f"{logradouro}, {numero}".strip(", "))
        complemento = address.get("complemento")
        if complemento:
            parts.append(complemento)
        bairro = address.get("bairro")
        cidade = address.get("cidade") or ""
        estado = address.get("estado") or ""
        if bairro or cidade or estado:
            bairro_city = f"{bairro} – {cidade}/{estado}" if bairro and cidade and estado else ", ".join(filter(None, [bairro, cidade, estado]))
            parts.append(bairro_city)
        return "\n".join(part for part in parts if part)

    def _resolve_driver_route_details(self, route, next_stop=None):
        operation_name = (route.get("organizacao") or {}).get("nome") or "Operação não informada"

        if next_stop is None:
            next_stop = route.get("proxima_entrega")

        endereco = None
        if next_stop:
            endereco = next_stop.get("destino") or next_stop.get("address") or {}
        if not endereco:
            for stop in route.get("entregas") or []:
                if stop.get("status") not in {"ENTREGUE", "CANCELADA"}:
                    endereco = stop.get("destino") or stop.get("address") or {}
                    break

        cliente_nome = None
        if next_stop:
            cliente_nome = ((next_stop.get("cliente") or {}).get("nome") or (next_stop.get("cliente") or {}).get("razao_social"))
        if not cliente_nome and next_stop:
            pedido_id = next_stop.get("pedido_id") or next_stop.get("entrega_id")
            if pedido_id is not None:
                cliente_nome = f"Pedido #{pedido_id}"

        if not cliente_nome:
            cliente_nome = "Cliente não informado"

        if not endereco and next_stop and next_stop.get("destino"):
            endereco = next_stop.get("destino")

        return {
            "operation_name": operation_name,
            "cliente_nome": cliente_nome,
            "endereco": endereco,
            "next_stop": next_stop,
        }

    @staticmethod
    def _map_current_delivery_id(next_stop):
        if not next_stop:
            return None
        return (next_stop.get("delivery") or {}).get("id")

    @staticmethod
    def _route_completion_summary(route):
        statuses = [item.get("status") for item in route.get("entregas") or []]
        return {
            "entregues": statuses.count("ENTREGUE"),
            "nao_entregues": statuses.count("NAO_ENTREGUE"),
            "canceladas": statuses.count("CANCELADA"),
            "total": len(statuses),
            "progresso": int(route.get("progresso_percentual") or 0),
        }

    @staticmethod
    def _is_expected_route_completion_error(message):
        return message == "Nenhuma rota ativa para este motorista"

    def _load_completed_route(self, route_id):
        return self.api.request("GET", f"/rotas/{route_id}")

    def _render_completed_route_view(self, route):
        summary = self._route_completion_summary(route)
        stops = self._driver_route_snapshot(route)
        route_map = self._render_driver_map_native(route, stops, None)
        self.content.controls = [
            self.header_bar("Rota concluída", f"#{route.get('id')} · {route.get('nome', 'Rota')}", actions=[
                ft.TextButton("Voltar ao Dashboard", icon=ft.Icons.ARROW_BACK, on_click=lambda _: self.dashboard_view()),
            ]),
            ft.Container(
                content=ft.Column([
                    ft.Text("Rota concluída", size=22, weight=ft.FontWeight.BOLD),
                    ft.Text("✓ Todas as paradas foram processadas", size=14),
                    ft.Text(f"Progresso: {summary['progresso']}%"),
                    ft.Text(f"Entregues: {summary['entregues']}"),
                    ft.Text(f"Não entregues: {summary['nao_entregues']}"),
                    ft.Text(f"Canceladas: {summary['canceladas']}"),
                    ft.Text(f"Total de paradas: {summary['total']}"),
                    ft.Text(f"Distância prevista: {route.get('distancia_prevista', 0)} km"),
                    ft.Text(f"Duração prevista: {route.get('duracao_prevista', 0)} h"),
                    route_map,
                    ft.FilledButton(
                        "Voltar ao Dashboard",
                        icon=ft.Icons.DASHBOARD,
                        on_click=lambda _: self.dashboard_view(),
                    ),
                ], spacing=10),
                padding=20,
            ),
        ]
        self.page.update()

    def _render_driver_map_native(self, route, stops, next_stop=None):
        origin = route.get("origem") or {}
        origin_point = None
        if origin.get("latitude") is not None and origin.get("longitude") is not None:
            origin_point = fmap.MapLatitudeLongitude(
                float(origin["latitude"]), float(origin["longitude"])
            )

        route_points = [
            fmap.MapLatitudeLongitude(lat, lng)
            for lat, lng in MapView._decode_polyline(
                route.get("route_geometry") or route.get("routeGeometry") or ""
            )
        ]
        marker_points = [
            (origin_point, "🏢", "Origem", self._format_driver_address(origin), "origin")
        ] if origin_point else []

        next_delivery_id = self._map_current_delivery_id(next_stop)
        for stop in stops:
            address = stop.get("address") or stop.get("destino") or {}
            if address.get("latitude") is None or address.get("longitude") is None:
                continue
            coordinates = fmap.MapLatitudeLongitude(
                float(address["latitude"]), float(address["longitude"])
            )
            delivery_id = stop.get("delivery", {}).get("id")
            is_current = delivery_id == next_delivery_id
            customer = stop.get("cliente") or {}
            customer_name = customer.get("nome") or customer.get("razao_social") or "Cliente não informado"
            marker_points.append((
                coordinates,
                "📍" if is_current else str(stop.get("order") or len(marker_points)),
                customer_name,
                self._format_driver_address(address),
                "current" if is_current else "stop",
            ))

        all_points = [(point.latitude, point.longitude) for point in route_points]
        all_points.extend((point.latitude, point.longitude) for point, *_ in marker_points)
        if not all_points:
            all_points = [(-27.816, -50.325)]
        center_lat = sum(point[0] for point in all_points) / len(all_points)
        center_lng = sum(point[1] for point in all_points) / len(all_points)
        latitude_span = max(max(point[0] for point in all_points) - min(point[0] for point in all_points), 0.001)
        longitude_span = max(max(point[1] for point in all_points) - min(point[1] for point in all_points), 0.001)
        zoom = max(3, min(18, int(min(math.log2(360 / longitude_span), math.log2(170 / latitude_span)) - 1)))

        markers = []
        for coordinates, label, title, address, marker_kind in marker_points:
            color = ft.Colors.GREEN_700 if marker_kind == "origin" else ft.Colors.RED_600 if marker_kind == "current" else ft.Colors.INDIGO
            markers.append(
                fmap.Marker(
                    content=ft.Container(
                        content=ft.Text(label, size=18, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER),
                        width=34 if marker_kind == "current" else 30,
                        height=34 if marker_kind == "current" else 30,
                        alignment=ft.alignment.center,
                        bgcolor=color,
                        border_radius=20,
                        tooltip=f"{title}\n{address}",
                    ),
                    coordinates=coordinates,
                )
            )

        layers = [
            fmap.TileLayer(
                url_template=(
                    "https://api.maptiler.com/maps/streets-v4/"
                    "{z}/{x}/{y}.png?key=" + MAPTILER_API_KEY
                )
            ),
            fmap.SimpleAttribution(text="© MapTiler © OpenStreetMap contributors"),
        ]
        if len(route_points) >= 2:
            layers.append(
                fmap.PolylineLayer(
                    polylines=[fmap.PolylineMarker(
                        coordinates=route_points,
                        color=ft.Colors.BLUE_700,
                        stroke_width=5,
                    )]
                )
            )
        layers.append(fmap.MarkerLayer(markers=markers))

        return fmap.Map(
            layers=layers,
            initial_center=fmap.MapLatitudeLongitude(center_lat, center_lng),
            initial_zoom=zoom,
            width=920,
            height=280,
            expand=True,
        )

    def _build_route_leaflet_map(self, route, stops):
        origin = route.get("origem") or {}
        fallback_points = []
        markers = []
        if origin.get("latitude") is not None and origin.get("longitude") is not None:
            origin_point = [float(origin["latitude"]), float(origin["longitude"])]
            fallback_points.append(origin_point)
            markers.append({
                "lat": origin_point[0],
                "lng": origin_point[1],
                "kind": "origin",
                "label": "🏢",
                "popup": self._format_driver_address(origin),
            })
        for stop in stops:
            address = stop.get("address") or stop.get("destino") or {}
            lat = address.get("latitude")
            lng = address.get("longitude")
            if lat is not None and lng is not None:
                delivery_id = stop.get("delivery", {}).get("id")
                next_delivery_id = (route.get("proxima_entrega") or {}).get("entrega_id")
                is_current = delivery_id == next_delivery_id
                customer = stop.get("cliente") or {}
                customer_name = customer.get("nome") or customer.get("razao_social") or "Cliente não informado"
                address_text = self._format_driver_address(address).replace("\n", "<br>")
                markers.append({
                    "lat": float(lat),
                    "lng": float(lng),
                    "kind": "current" if is_current else "stop",
                    "label": "📍" if is_current else str(stop.get("order") or len(markers)),
                    "popup": f"{customer_name}<br>{address_text}",
                })

        points_json = json.dumps(fallback_points)
        markers_json = json.dumps(markers, ensure_ascii=False)
        geometry_json = json.dumps(route.get("route_geometry") or route.get("routeGeometry"))
        html = f"""
        <!doctype html>
        <html>
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1.0" />
          <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
          <style>
            html, body {{ height: 100%; margin: 0; padding: 0; }}
            #map {{ height: 100%; width: 100%; min-height: 300px; border-radius: 14px; }}
            .route-marker {{ background: #2563eb; color: white; border: 2px solid white; border-radius: 50%; width: 30px; height: 30px; line-height: 26px; text-align: center; font-size: 16px; font-weight: 700; box-shadow: 0 1px 5px rgba(0,0,0,.45); }}
            .route-marker.origin {{ background: #15803d; }}
            .route-marker.current {{ background: #dc2626; width: 36px; height: 36px; line-height: 32px; font-size: 20px; }}
          </style>
        </head>
        <body>
          <div id="map"></div>
          <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
          <script>
                        const fallbackPoints = {points_json};
                        const markers = {markers_json};
                        const encodedGeometry = {geometry_json};
                        function decodePolyline(encoded) {{
                            if (!encoded) return [];
                            const points = []; let index = 0; let lat = 0; let lng = 0;
                            while (index < encoded.length) {{
                                const values = [];
                                for (let coordinate = 0; coordinate < 2; coordinate++) {{
                                    let result = 0; let shift = 0; let byte;
                                    do {{ byte = encoded.charCodeAt(index++) - 63; result |= (byte & 0x1f) << shift; shift += 5; }} while (byte >= 0x20);
                                    values.push((result & 1) ? ~(result >> 1) : (result >> 1));
                                }}
                                lat += values[0]; lng += values[1]; points.push([lat / 100000, lng / 100000]);
                            }}
                            return points;
                        }}
                        const routePoints = decodePolyline(encodedGeometry);
                        const visiblePoints = routePoints.length ? routePoints : fallbackPoints;
                        const map = L.map('map').setView(visiblePoints[0] || [-27.816, -50.325], 13);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
              attribution: '&copy; OpenStreetMap contributors'
            }}).addTo(map);

                        const bounds = L.latLngBounds([]);
                        if (routePoints.length) L.polyline(routePoints, {{ color: '#1d4ed8', weight: 5, opacity: 0.9 }}).addTo(map);
                        markers.forEach(item => {{
                            const icon = L.divIcon({{ className: '', html: `<div class="route-marker ${{item.kind}}">${{item.label}}</div>`, iconSize: [36, 36], iconAnchor: [18, 18] }});
                            const marker = L.marker([item.lat, item.lng], {{ icon }}).addTo(map);
                            marker.bindPopup(item.popup, {{ closeButton: true }});
                            bounds.extend([item.lat, item.lng]);
                        }});
                        routePoints.forEach(point => bounds.extend(point));
                        if (!bounds.isEmpty()) map.fitBounds(bounds.pad(0.12));
          </script>
        </body>
        </html>
        """
        return "data:text/html;charset=utf-8," + quote(html)

    def _render_driver_map(self, route, stops):
        html_url = self._build_route_leaflet_map(route, stops)
        return ft.WebView(
            html_url,
            javascript_enabled=True,
            enable_javascript=True,
            width=920,
            height=280,
            expand=True,
        )

    @staticmethod
    def _driver_loading_action_labels(route):
        if route.get("carga_confirmada"):
            return ["Revisar carga", "Iniciar viagem"]
        return ["Verificar carga", "Iniciar viagem"]

    @staticmethod
    def _loading_dialog_action_labels(review_only=False):
        return ["Fechar"] if review_only else ["Cancelar", "Confirmar carga"]

    def loading_order_dialog(self, route, stops, review_only=False):
        """
        Tela de ordem de carregamento.
        Mostra os pedidos em ordem inversa (último a ser entregue primeiro a ser carregado)
        e exige confirmação antes de permitir iniciar a viagem.
        """
        try:
            dlg = ft.AlertDialog(title=ft.Text("Ordem de carregamento"), scrollable=True)
            content_list = []

            content_list.append(
                ft.Container(
                    content=ft.Text(
                        "Confirme que os pedidos estão na ordem correta no veículo.\n"
                        "Último pedido (embaixo) primeiro a ser carregado.",
                        size=12,
                        color=ft.Colors.GREY_700,
                    ),
                    padding=16,
                    bgcolor=ft.Colors.AMBER_50,
                    border_radius=12,
                )
            )

            # Mostrar paradas em ordem inversa
            for stop in reversed(stops):
                delivery = stop.get("delivery", {})
                address = stop.get("address", {})
                order = stop.get("order", 0)

                client_name = self._driver_stop_label(stop)
                formatted_address = self._driver_stop_address(stop)

                content_list.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text(f"Parada {order}: {client_name}", size=12, weight=ft.FontWeight.BOLD),
                            ft.Text(formatted_address, size=10, color=ft.Colors.GREY_700),
                            ft.Text(f"Pedido #{delivery.get('pedido_id', '--')}", size=10, color=ft.Colors.GREY_600),
                        ], spacing=4),
                        padding=12,
                        margin=ft.margin.only(bottom=8),
                        border_radius=8,
                        bgcolor=ft.Colors.BLUE_50,
                        border=ft.border.all(1, ft.Colors.BLUE_200),
                    )
                )

            dlg.content = ft.Column(
                content_list,
                scroll=ft.ScrollMode.AUTO,
            )

            def confirm_and_close(_):
                try:
                    self.api.request("PATCH", f"/rotas/{route['id']}/confirmar-carga")
                    dlg.open = False
                    self.page.update()
                    self.driver_route_view(route.get("id"))
                except ApiError as exc:
                    self.notify(str(exc), True)

            if review_only:
                dlg.actions = [ft.TextButton("Fechar", on_click=lambda _: self.close_dialog(dlg))]
            else:
                dlg.actions = [
                    ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dlg)),
                    ft.FilledButton("Confirmar carga", on_click=confirm_and_close),
                ]
            self.open_dialog(dlg)
        except Exception:
            raise

    def _start_route_execution(self, route):
        """
        Inicia a execução da rota.
        """
        self.change_route_status(route, "EM_EXECUCAO", event="PARTIDA", observation="Viagem iniciada pelo motorista", progress=5, stay_in_view=True)

    @staticmethod
    def _driver_execution_action_labels(route):
        route_status = (route or {}).get("status")
        if route_status == "EM_EXECUCAO":
            return ["Entregue", "Não entregue", "Registrar ocorrência"]
        return []

    def _mark_delivery_as_not_delivered(self, route, next_stop):
        delivery = next_stop.get("delivery") if next_stop else {}
        delivery_id = delivery.get("id")
        if delivery_id is None:
            self.notify("Entrega não identificada.", True)
            return

        dialog = ft.AlertDialog(
            title=ft.Text("Não entregue"),
            content=ft.Column([
                ft.Text("Informe o motivo da não entrega."),
                ft.TextField(label="Motivo / observação", multiline=True, min_lines=3),
            ], tight=True, width=420),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: self.close_dialog(dialog)),
                ft.FilledButton("Confirmar não entrega", on_click=lambda _: self._confirm_not_delivered(dialog, delivery_id)),
            ],
        )
        self.open_dialog(dialog)

    def _confirm_not_delivered(self, dialog, delivery_id):
        try:
            text_field = dialog.content.controls[1]
            observation = (text_field.value or "").strip()
            if not observation:
                self.notify("Informe o motivo da não entrega.", True)
                return
            self.api.request("PATCH", f"/entregas/{delivery_id}/status", json={"status": "NAO_ENTREGUE", "observacao": observation})
            self.close_dialog(dialog)
            self.notify("Entrega marcada como não entregue.")
            self.driver_route_view()
        except ApiError as exc:
            self.notify(str(exc), True)

    def _complete_next_delivery(self, route, next_stop):
        """
        Marca a próxima entrega como concluída.
        """
        if not next_stop:
            self.notify("Nenhuma entrega pendente para concluir.", True)
            return

        delivery_id = next_stop.get("delivery", {}).get("id")
        if not delivery_id:
            self.notify("Erro ao identificar entrega.", True)
            return

        try:
            cliente = next_stop.get("cliente", {})
            self.api.request(
                "POST",
                f"/entregas/{delivery_id}/comprovante",
                json={
                    "nome_recebedor": cliente.get("nome", "Recebedor"),
                    "documento_recebedor": f"DOC-{delivery_id}",
                    "observacao": "Entrega confirmada na execução da rota",
                },
            )
            self.api.request(
                "PATCH",
                f"/entregas/{delivery_id}/status",
                json={"status": "ENTREGUE", "observacao": "Entrega concluída pela execução da rota"},
            )

            # Recarrega rota atualizada
            try:
                updated_route = self.api.request("GET", f"/rotas/{route['id']}")
                snapshot = self._driver_route_snapshot(updated_route)
                completed = sum(1 for stop in snapshot if stop["delivery"]["status"] == "ENTREGUE")
                total = len(snapshot) or 1
                new_progress = min(100, int((completed / total) * 100))

                if completed >= total:
                    self.change_route_status(updated_route, "FINALIZADA", progress=100, event="FINALIZADA", observation="Todas as entregas concluídas", stay_in_view=True)
                else:
                    self.change_route_status(updated_route, "EM_EXECUCAO", progress=new_progress, event="ENTREGA_REALIZADA", observation=f"Entrega {delivery_id} concluída", stay_in_view=True)
            except ApiError:
                # Fallback: tenta com rota original se falhar
                snapshot = self._driver_route_snapshot(route)
                completed = sum(1 for stop in snapshot if stop["delivery"]["status"] == "ENTREGUE")
                total = len(snapshot) or 1
                new_progress = min(100, int((completed / total) * 100))
                self.driver_route_view(route.get("id"), loading_confirmed=False)
                
            self.notify("Entrega concluída!")
        except ApiError as exc:
            self.notify(str(exc), True)

    def _close_dialog(self, dlg):
        """
        Fecha um diálogo.
        """
        dlg.open = False
        self.page.update()

    def _driver_route_panel(self, route):
        route_progress = int(route.get("progresso_percentual") or 0)
        next_stop = self._next_driver_stop(route)
        stops = self._driver_route_snapshot(route)
        has_pending = any(stop["delivery"]["status"] not in {"ENTREGUE", "CANCELADA"} for stop in stops)
        next_stop_text = "-"
        next_stop_address = "-"
        if next_stop:
            next_stop_text = next_stop['cliente'].get('nome') or "Cliente não informado"
            next_stop_address = self._format_driver_address(next_stop.get('address'))

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
                    title=ft.Text(f"{stop['order']}. {stop['cliente'].get('nome') or 'Cliente'}"),
                    subtitle=ft.Text(f"{self._format_driver_address(stop.get('address'))} · {delivery['status'].replace('_', ' ').title()}"),
                    trailing=ft.Text(f"#{delivery['id']}"),
                )
            )

        return ft.Container(
            content=ft.Column(
                [
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
                    ft.Text(next_stop_address, color=ft.Colors.GREY_700, selectable=True),
                ],
                spacing=10,
            ),
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.WHITE,
            shadow=ft.BoxShadow(blur_radius=12, color=ft.Colors.BLACK12),
        )

    def change_route_status(self, route, new_status, progress=None, event=None, observation=None, stay_in_view=False):
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
            if self.user.get("perfil") == "MOTORISTA":
                if new_status == "EM_EXECUCAO":
                    self._sync_driver_tracking({**route, "status": new_status})
                else:
                    self._sync_driver_tracking({**route, "status": new_status})
            # Se called from driver_route_view, recarrega a tela; caso contrário, volta para rotas_view
            if stay_in_view:
                self.driver_route_view(route.get("id"), loading_confirmed=False)
            else:
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

        clients_by_id, addresses_by_client = {}, {}
        try:
            clients_by_id, addresses_by_client = self._load_client_lookup(available_orders)
        except Exception:
            pass

        order_checkboxes = []
        for order in available_orders:
            address_label = "Endereço não cadastrado"
            cliente_nome = "Cliente"
            client_id = order.get("cliente_id")
            if client_id is not None and client_id in clients_by_id:
                client = clients_by_id[client_id]
                cliente_nome = client.get("nome") or "Cliente"
                addresses = addresses_by_client.get(client_id, [])
                address = next((item for item in addresses if item["id"] == order.get("endereco_entrega_id")), None)
                if address:
                    address_label = f"{address.get('logradouro', '')}, {address.get('numero', '')} - {address.get('bairro', '')}, {address.get('cidade', '')}"
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
                "nome": self._generated_route_name(),
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
        organization = route.get("organizacao") or {}
        driver = route.get("motorista") or {}
        vehicle = route.get("veiculo") or {}
        vehicle_label = "--"
        if vehicle:
            vehicle_label = " · ".join(filter(None, [
                f"{vehicle.get('marca', '')} {vehicle.get('modelo', '')}".strip(),
                vehicle.get("placa"),
            ])) or "--"
        content = ft.Column([
            ft.Text(f'Nome: {route["nome"]}'),
            ft.Text(f'Descrição: {route.get("descricao") or "-"}'),
            ft.Text(f'Status: {route["status"].replace("_", " ")}'),
            ft.Text(f'Veículo: {vehicle_label if vehicle else route.get("veiculo_id") or "--"}'),
            ft.Text(f'Motorista: {driver.get("nome") if driver else route.get("motorista_id") or "--"}'),
            ft.Text(f'Organização: {organization.get("nome") if organization else route.get("organizacao_id") or "--"}'),
            ft.Text(f'Entregas: {len(route.get("entregas") or [])}'),
            ft.Text(f'Data planejada: {self._format_iso_datetime(route.get("data_planejada"))}'),
            ft.Text(f'Data de início: {self._format_iso_datetime(route.get("data_inicio"))}'),
            ft.Text(f'Data de conclusão: {self._format_iso_datetime(route.get("data_conclusao"))}'),
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

    def receipt_dialog(self, delivery_id, return_route_id=None):
        receipt = None
        active_route_flow = return_route_id is not None
        if not active_route_flow:
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
            if document.value and not self.require_text(document, "Informe pelo menos 3 caracteres.", 3):
                errors.append("Documento: informe pelo menos 3 caracteres.")
                valid = False
            if not valid:
                error_message.value = "; ".join(errors) if errors else "Corrija os campos destacados."
                self.page.update()
                return
            try:
                payload = {
                    "nome_recebedor": name.value,
                    "documento_recebedor": (document.value or "").strip() or None,
                    "observacao": (note.value or "").strip() or None,
                }
                if active_route_flow:
                    self.api.request("POST", f"/entregas/{delivery_id}/concluir", json=payload)
                    message = "Entrega concluída com comprovante."
                elif receipt:
                    self.api.request("PUT", f"/entregas/{delivery_id}/comprovante", json=payload)
                    message = "Comprovante atualizado."
                else:
                    self.api.request("POST", f"/entregas/{delivery_id}/comprovante", json=payload)
                    self.api.request("PATCH", f"/entregas/{delivery_id}/status",
                                     json={"status": "ENTREGUE", "observacao": "Entrega confirmada"})
                    message = "Entrega concluída com comprovante."
                self.close_dialog(dialog)
                self.notify(message)
                self._refresh_after_delivery_action(return_route_id)
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
                self._refresh_after_delivery_action(return_route_id)
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

    def _refresh_after_delivery_action(self, return_route_id=None):
        if return_route_id is not None:
            self.driver_route_view(return_route_id)
        else:
            self.deliveries_view()

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

