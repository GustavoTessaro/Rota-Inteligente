import flet as ft

from app.application import DeliveryApp


def main(page: ft.Page):
    DeliveryApp(page).start()


if __name__ == "__main__":
    ft.app(main)
