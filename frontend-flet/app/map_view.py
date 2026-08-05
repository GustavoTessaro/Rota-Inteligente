import os
import json
import urllib.parse

import flet as ft


class MapView(ft.UserControl):
    def __init__(self, markers=None, api_key=None, height=400):
        super().__init__()
        self.markers = markers or []
        # prefer explicit api_key param; if not provided, frontend will fetch key from backend
        self.api_key = api_key
        self.height = height

    def build(self):
        tmpl_path = os.path.join(os.path.dirname(__file__), "maps_static", "map_page.html")
        try:
            with open(tmpl_path, "r", encoding="utf-8") as f:
                html = f.read()
        except Exception as exc:
            return ft.Text(f"Erro ao carregar mapa: {exc}")

        # don't hardcode keys in HTML; inject markers and let the frontend request the key
        markers_json = json.dumps(self.markers)
        inject = f"<script>window.INITIAL_MARKERS = {markers_json};</script>"
        injected_html = html.replace("<head>", "<head>" + inject, 1)
        data_url = "data:text/html;charset=utf-8," + urllib.parse.quote(injected_html)

        web = ft.WebView(src=data_url, expand=True, height=self.height)

        # after the WebView is created, fetch restricted key from backend and post it to the WebView
        def _on_ready(e=None):
            try:
                # call backend to get restricted key
                import httpx
                from .config import API_BASE_URL
                client = httpx.Client(base_url=API_BASE_URL, timeout=5)
                cfg = client.get('/maps/config').json()
                key = cfg.get('google_maps_key')
            except Exception:
                key = None
            # send key to WebView to load Maps JS
            # prefer eval_js to postMessage inside the WebView context
            try:
                web.eval_js(f"window.postMessage({json.dumps({'action':'loadKey','key':key})}, '*');")
            except Exception:
                try:
                    web.page.window_post_message(web, json.dumps({"action": "loadKey", "key": key}))
                except Exception:
                    pass

        # schedule on next tick
        self.page = ft.session.get('page') if hasattr(ft, 'session') else None
        # attach callback when the WebView page is loaded (some flet versions support on_page_load)
        try:
            web.on_page_load = _on_ready
        except Exception:
            # fallback: call after small delay using page.schedule_frame if available
            try:
                from time import sleep
                sleep(0.01)
                _on_ready()
            except Exception:
                pass

        # expose helper methods for dynamic updates
        def _post(payload: dict):
            try:
                web.eval_js(f"window.postMessage({json.dumps(payload)}, '*');")
            except Exception:
                try:
                    web.page.window_post_message(web, json.dumps(payload))
                except Exception:
                    pass

        # public methods
        def set_markers(markers: list):
            _post({"action": "clear"})
            _post({"action": "markers", "markers": markers})

        def add_marker(marker: dict):
            _post({"action": "markers", "markers": [marker]})

        def draw_polyline(encoded: str):
            _post({"action": "polyline", "encoded": encoded})

        def center_on(lat: float, lng: float, zoom: int | None = None):
            payload = {"action": "center", "lat": lat, "lng": lng}
            if zoom:
                payload["zoom"] = zoom
            _post(payload)

        # attach to web object for external use
        web.set_markers = set_markers
        web.add_marker = add_marker
        web.draw_polyline = draw_polyline
        web.center_on = center_on

        return web
