import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_CONFIG = PROJECT_ROOT / "frontend-flet" / "app" / "generated_config.py"


def validate_api_base_url(value: str) -> str:
    if any(char.isspace() or ord(char) < 32 for char in value):
        raise ValueError("API_BASE_URL nao pode conter espacos ou caracteres de controle")
    if "[" in value or "](" in value or ")" in value:
        raise ValueError("API_BASE_URL nao pode usar sintaxe Markdown")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API_BASE_URL deve usar http/https e conter um host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("API_BASE_URL nao pode conter credenciais, query ou fragmento")
    if parsed.path != "/api":
        raise ValueError("API_BASE_URL deve terminar exatamente em /api")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("API_BASE_URL contem uma porta invalida") from exc
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gera configuracao local para build Android")
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--maptiler-api-key", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        api_base_url = validate_api_base_url(args.api_base_url)
    except ValueError as exc:
        print(f"Erro: {exc}")
        return 2

    maptiler_api_key = args.maptiler_api_key or os.getenv("MAPTILER_API_KEY", "")
    if not maptiler_api_key:
        print("Aviso: MAPTILER_API_KEY ausente; os tiles do mapa nao funcionarao.")

    output = GENERATED_CONFIG
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# Arquivo local gerado; nao versionar.\n"
        f"BUILD_API_BASE_URL = {api_base_url!r}\n"
        f"BUILD_MAPTILER_API_KEY = {maptiler_api_key!r}\n",
        encoding="utf-8",
    )
    print(f"Configuracao gerada: {output}")
    print(f"API_BASE_URL configurada: {api_base_url}")
    print(f"MAPTILER_API_KEY configurada: {bool(maptiler_api_key)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
