import math

import flet as ft
import flet_map as fmap


class MapView:
    DEFAULT_CENTER = (-27.816, -50.325)

    def __init__(self, markers=None, height=320, width=680, on_marker_click=None, selected_marker_id=None, title=None):
        self.markers = markers or []
        self.height = height
        self.width = width
        self.on_marker_click = on_marker_click
        self.selected_marker_id = selected_marker_id
        self.title = title or "Mapa de monitoramento"
        self.polyline = None
        self._control = None
        self._marker_layer = None

    def build(self):
        self._marker_layer = fmap.MarkerLayer(markers=self._build_markers())
        layers = [
            fmap.TileLayer(
                url_template="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                subdomains=["a", "b", "c"],
            ),
            fmap.SimpleAttribution(text="© OpenStreetMap contributors"),
            self._marker_layer,
        ]
        self._control = fmap.Map(
            layers=layers,
            initial_center=fmap.MapLatitudeLongitude(*self._center()),
            initial_zoom=self._zoom(),
            width=self.width,
            height=self.height,
        )
        self._control.set_markers = self.set_markers
        self._control.add_marker = self.add_marker
        self._control.clear = self.clear
        self._control.draw_polyline = self.draw_polyline
        self._control.center_on = self.center_on
        return self._control

    def _valid_markers(self):
        valid = []
        for marker in self.markers:
            try:
                latitude = float(marker.get("lat"))
                longitude = float(marker.get("lng"))
            except (AttributeError, TypeError, ValueError):
                continue
            if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                valid.append((marker, latitude, longitude))
        return valid

    def _center(self):
        points = [(latitude, longitude) for _, latitude, longitude in self._valid_markers()]
        if not points:
            return self.DEFAULT_CENTER
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def _zoom(self):
        points = [(latitude, longitude) for _, latitude, longitude in self._valid_markers()]
        if len(points) < 2:
            return 14
        latitude_span = max(max(point[0] for point in points) - min(point[0] for point in points), 0.001)
        longitude_span = max(max(point[1] for point in points) - min(point[1] for point in points), 0.001)
        return max(3, min(18, int(min(math.log2(360 / longitude_span), math.log2(170 / latitude_span)) - 1)))

    def _build_markers(self):
        result = []
        for marker, latitude, longitude in self._valid_markers():
            vehicle_id = marker.get("vehicle_id") or marker.get("id") or "?"
            title = marker.get("title") or marker.get("label") or f"Veículo {vehicle_id}"
            content = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(str(title), size=11, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                        ft.Text(f"{latitude:.5f}, {longitude:.5f}", size=9, color=ft.Colors.WHITE),
                    ],
                    tight=True,
                    spacing=1,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=118,
                height=38,
                padding=4,
                alignment=ft.alignment.center,
                bgcolor=ft.Colors.RED_600 if marker.get("is_current") else ft.Colors.INDIGO,
                border_radius=8,
                tooltip=f"{title} - {latitude:.5f}, {longitude:.5f}",
                on_click=lambda event, marker=marker: self._on_marker_click(marker),
            )
            result.append(
                fmap.Marker(
                    content=content,
                    coordinates=fmap.MapLatitudeLongitude(latitude, longitude),
                    data={**marker, "vehicle_id": vehicle_id},
                )
            )
        return result

    def _on_marker_click(self, marker):
        if callable(self.on_marker_click):
            self.on_marker_click(marker)

    def set_markers(self, markers):
        self.markers = markers or []
        if self._marker_layer is None:
            return
        self._marker_layer.markers = self._build_markers()
        try:
            self._control.update()
        except AssertionError:
            pass

    def add_marker(self, marker):
        vehicle_id = marker.get("vehicle_id") or marker.get("id")
        self.markers = [item for item in self.markers if (item.get("vehicle_id") or item.get("id")) != vehicle_id]
        self.markers.append(marker)
        self.set_markers(self.markers)

    def clear(self):
        self.set_markers([])

    def draw_polyline(self, encoded):
        self.polyline = encoded

    def center_on(self, lat, lng, zoom=None):
        if self._control is not None:
            self._control.initial_center = fmap.MapLatitudeLongitude(lat, lng)
            if zoom is not None:
                self._control.initial_zoom = zoom
            try:
                self._control.update()
            except AssertionError:
                pass

    @staticmethod
    def _decode_polyline(encoded):
        if not encoded:
            return []
        points = []
        index = lat = lng = 0
        while index < len(encoded):
            result, shift = 0, 0
            while True:
                if index >= len(encoded):
                    return points
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            lat += ~(result >> 1) if result & 1 else result >> 1
            result, shift = 0, 0
            while True:
                if index >= len(encoded):
                    return points
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            lng += ~(result >> 1) if result & 1 else result >> 1
            points.append((lat / 1e5, lng / 1e5))
        return points