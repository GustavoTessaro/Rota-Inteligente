import flet as ft

from app.application import DeliveryApp


def main(page: ft.Page):
    DeliveryApp(page).start()


ft.run(main)
