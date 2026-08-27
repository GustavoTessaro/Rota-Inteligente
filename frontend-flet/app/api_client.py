import httpx

from .config import API_BASE_URL


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self):
        self.token: str | None = None
        self.client = httpx.Client(base_url=API_BASE_URL, timeout=15)

    def request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.client.request(method, path, headers=headers, **kwargs)
        except httpx.RequestError as exc:
            if method == "POST" and "/posicoes" in path:
                print(f"[TRACKING_HTTP] HTTP_REQUEST_FAILED status=sem resposta body={exc!r}")
            print(f"API ERROR -> {method} {path}")
            print(f"STATUS -> {'sem resposta'}")
            print(f"BODY -> {exc}")
            raise ApiError("Não foi possível conectar à API.") from exc
        if response.status_code >= 400:
            if method == "POST" and "/posicoes" in path:
                print(f"[TRACKING_HTTP] HTTP_REQUEST_FAILED status={response.status_code} body={response.text}")
            print(f"API ERROR -> {method} {path}")
            print(f"STATUS -> {response.status_code}")
            print(f"BODY -> {response.text}")
            try:
                detail = response.json().get("detail", "Erro ao processar solicitação")
            except ValueError:
                detail = "Erro ao processar solicitação"
            if isinstance(detail, list):
                messages = []
                for item in detail:
                    field = item.get("loc", [""])[-1]
                    message = item.get("msg", "valor inválido")
                    messages.append(f"{field}: {message}" if field else message)
                detail = "; ".join(messages)
            raise ApiError(str(detail))
        if method == "POST" and "/posicoes" in path:
            print(f"[TRACKING_HTTP] HTTP_REQUEST_SUCCESS status={response.status_code}")
        return response.json() if response.content else None

    def login(self, email: str, password: str):
        data = self.request("POST", "/auth/login", json={"email": email, "senha": password})
        self.token = data["token"]
        return data["usuario"]

    def publish_route_position(self, route_id: int, payload: dict):
        print(f"[TRACKING_HTTP] HTTP_REQUEST_STARTED POST /api/rotas/{route_id}/posicoes")
        try:
            result = self.request("POST", f"/rotas/{route_id}/posicoes", json=payload)
            return result
        except ApiError as exc:
            raise

    def recommend_route_alternative(self, route_id: int, criterion: str):
        return self.request("PATCH", f"/rotas/{route_id}/recomendacao", json={"criterio": criterion})

    def select_route_alternative(self, route_id: int, alternative_id: int):
        return self.request("POST", f"/rotas/{route_id}/selecionar-alternativa", json={"alternativa_id": alternative_id})
