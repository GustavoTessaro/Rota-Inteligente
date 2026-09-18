from pathlib import Path

import flet as ft

from app.application import DeliveryApp


def main(page: ft.Page):
    page.title = "Rota Inteligente"
    page.window.icon = str(Path(__file__).resolve().parent / "imagens" / "Logo-ROTA-INTELIGENTE-o-R-icone.ico")
    DeliveryApp(page).start()


if __name__ == "__main__":
    ft.app(main)
