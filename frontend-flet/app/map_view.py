import flet as ft


class MapView:
    def __init__(self, markers=None, height=320, width=680, on_marker_click=None, selected_marker_id=None, title=None):
        self.markers = markers or []
        self.height = height
        self.width = width
        self.on_marker_click = on_marker_click
        self.selected_marker_id = selected_marker_id
        self.title = title or "Mapa de monitoramento"
        self.polyline = None
        self._control = None

    def build(self):
        self._control = ft.Container(
            content=self._build_body(),
            width=self.width,
            height=self.height,
            padding=12,
            border_radius=18,
            bgcolor=ft.Colors.BLUE_GREY_50,
            border=ft.border.all(1, ft.Colors.GREY_300),
        )
        self._control.set_markers = self.set_markers
        self._control.add_marker = self.add_marker
        self._control.clear = self.clear
        self._control.draw_polyline = self.draw_polyline
        self._control.center_on = self.center_on
        return self._control

    def _build_body(self):
        if not self.markers and not self.polyline:
            return ft.Column(
                [
                    ft.Text(self.title, weight=ft.FontWeight.BOLD, size=16),
                    ft.Container(height=16),
                    ft.Icon(ft.Icons.LOCAL_SHIPPING, size=44, color=ft.Colors.GREY_500),
                    ft.Text("Não há motoristas em atividade no momento.", color=ft.Colors.GREY_700),
                    ft.Container(height=16),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )

        route_points = self._decode_polyline(self.polyline) if self.polyline else []
        if self.markers:
            latitudes = [float(marker.get("lat")) for marker in self.markers if marker.get("lat") is not None]
            longitudes = [float(marker.get("lng")) for marker in self.markers if marker.get("lng") is not None]
        else:
            latitudes = [p[0] for p in route_points]
            longitudes = [p[1] for p in route_points]

        if not latitudes or not longitudes:
            return ft.Column(
                [
                    ft.Text(self.title, weight=ft.FontWeight.BOLD, size=16),
                    ft.Container(height=16),
                    ft.Icon(ft.Icons.LOCAL_SHIPPING, size=44, color=ft.Colors.GREY_500),
                    ft.Text("Não há motoristas em atividade no momento.", color=ft.Colors.GREY_700),
                    ft.Container(height=16),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            )

        min_lat, max_lat = min(latitudes), max(latitudes)
        min_lng, max_lng = min(longitudes), max(longitudes)
        if min_lat == max_lat:
            min_lat -= 0.01
            max_lat += 0.01
        if min_lng == max_lng:
            min_lng -= 0.01
            max_lng += 0.01

        map_width = max(400, self.width - 24)
        map_height = max(220, self.height - 24)
        padding = 16
        available_width = map_width - padding * 2
        available_height = map_height - padding * 2

        stack_children = [
            ft.Container(
                expand=True,
                bgcolor=ft.Colors.WHITE,
                border_radius=14,
                border=ft.border.all(1, ft.Colors.GREY_200),
            )
        ]

        if self.polyline:
            route_points = self._decode_polyline(self.polyline)
            if route_points:
                route_segments = self._build_polyline_segments(route_points, map_width, map_height, padding)
                stack_children.extend(route_segments)

        for marker in self.markers:
            try:
                lat = float(marker.get("lat"))
                lng = float(marker.get("lng"))
            except (TypeError, ValueError):
                continue
            x = padding + int((lng - min_lng) / (max_lng - min_lng) * available_width)
            y = padding + int((max_lat - lat) / (max_lat - min_lat) * available_height)
            selected = str(marker.get("id")) == str(self.selected_marker_id)
            marker_bg = ft.Colors.RED_600 if selected else ft.Colors.INDIGO
            label = marker.get("title") or marker.get("label") or "Motorista"
            marker_box = ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.LOCAL_SHIPPING, size=18, color=ft.Colors.WHITE),
                        ft.Text(label, size=10, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER),
                    ],
                    tight=True,
                    spacing=2,
                ),
                width=110,
                height=52,
                padding=8,
                border_radius=12,
                bgcolor=marker_bg,
                alignment=ft.alignment.center,
                on_click=lambda e, marker=marker: self._on_marker_click(marker),
                opacity=0.95,
            )
            stack_children.append(
                ft.Container(
                    left=x,
                    top=y,
                    width=110,
                    height=52,
                    content=marker_box,
                )
            )

        content = ft.Stack(stack_children)
        return ft.Column(
            [
                ft.Text(self.title, weight=ft.FontWeight.BOLD, size=16),
                ft.Divider(height=10),
                ft.Container(content=content, width=map_width, height=map_height),
            ],
            tight=True,
        )

    def _on_marker_click(self, marker: dict):
        if callable(self.on_marker_click):
            self.on_marker_click(marker)

    def set_markers(self, markers: list):
        self.markers = markers or []
        self._refresh()

    def add_marker(self, marker: dict):
        self.markers.append(marker)
        self._refresh()

    def clear(self):
        self.markers = []
        self._refresh()

    def draw_polyline(self, encoded: str):
        self.polyline = encoded
        self._refresh()

    def center_on(self, lat: float, lng: float, zoom: int | None = None):
        pass

    @staticmethod
    def _decode_polyline(encoded: str):
        if not encoded:
            return []
        points = []
        index = 0
        lat = 0
        lng = 0
        while index < len(encoded):
            b = 0
            shift = 0
            result = 0
            while True:
                if index >= len(encoded):
                    return points
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                b = byte >> 5
                if b == 0:
                    break
            lat += (result & 1 and -(result >> 1) or (result >> 1))
            result = 0
            shift = 0
            while True:
                if index >= len(encoded):
                    return points
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                b = byte >> 5
                if b == 0:
                    break
            lng += (result & 1 and -(result >> 1) or (result >> 1))
            points.append((lat / 1e5, lng / 1e5))
        return points

    def _refresh(self):
        if self._control is None:
            return
        self._control.content = self._build_body()
        try:
            self._control.update()
        except Exception:
            pass

    def _build_polyline_segments(self, route_points, map_width, map_height, padding=16):
        if not route_points:
            return []
        latitudes = [p[0] for p in route_points]
        longitudes = [p[1] for p in route_points]
        min_lat, max_lat = min(latitudes), max(latitudes)
        min_lng, max_lng = min(longitudes), max(longitudes)
        if min_lat == max_lat:
            min_lat -= 0.01
            max_lat += 0.01
        if min_lng == max_lng:
            min_lng -= 0.01
            max_lng += 0.01

        pixels = []
        for lat, lng in route_points:
            x = padding + int((lng - min_lng) / (max_lng - min_lng) * (map_width - padding * 2))
            y = padding + int((max_lat - lat) / (max_lat - min_lat) * (map_height - padding * 2))
            pixels.append((x, y))

        segment_children = []
        for (x1, y1), (x2, y2) in zip(pixels, pixels[1:]):
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            if dx == 0 and dy == 0:
                continue
            width = max(6, dx + 8)
            height = max(4, dy + 8)
            left = min(x1, x2)
            top = min(y1, y2)
            segment_children.append(
                ft.Container(
                    left=left,
                    top=top,
                    width=width,
                    height=height,
                    content=ft.Container(
                        bgcolor=ft.Colors.BLUE_600,
                        border_radius=10,
                        width=width,
                        height=height,
                        opacity=0.9,
                    ),
                )
            )
        return segment_children
