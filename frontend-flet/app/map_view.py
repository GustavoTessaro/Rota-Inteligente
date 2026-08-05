import os
import json
import urllib.parse

import flet as ft


class MapView(ft.UserControl):
    def __init__(self, markers=None, api_key=None, height=400):
        super().__init__()
        self.markers = markers or []
        self.api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY", "")
        self.height = height

    def build(self):
        tmpl_path = os.path.join(os.path.dirname(__file__), "maps_static", "map_page.html")
        try:
            with open(tmpl_path, "r", encoding="utf-8") as f:
                html = f.read()
        except Exception as exc:
            return ft.Text(f"Erro ao carregar mapa: {exc}")

        html = html.replace("REPLACE_KEY", self.api_key)
        markers_json = json.dumps(self.markers)
        inject = f"<script>window.INITIAL_MARKERS = {markers_json};</script>"
        # insert after <head>
        injected_html = html.replace("<head>", "<head>" + inject, 1)
        data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(injected_html)

        web = ft.WebView(src=data_url, expand=True, height=self.height)
        return web
