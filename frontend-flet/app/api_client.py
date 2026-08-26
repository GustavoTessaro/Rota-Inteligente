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
            print(f"API ERROR -> {method} {path}")
            print(f"STATUS -> {'sem resposta'}")
            print(f"BODY -> {exc}")
            raise ApiError("Não foi possível conectar à API.") from exc
        if response.status_code >= 400:
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
        return response.json() if response.content else None

    def login(self, email: str, password: str):
        data = self.request("POST", "/auth/login", json={"email": email, "senha": password})
        self.token = data["token"]
        return data["usuario"]

    def publish_route_position(self, route_id: int, payload: dict):
        return self.request("POST", f"/rotas/{route_id}/posicoes", json=payload)
