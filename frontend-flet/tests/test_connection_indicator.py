from app.application import DeliveryApp


def make_app(profile, gps_state="inativo"):
    app = DeliveryApp.__new__(DeliveryApp)
    app.user = {"perfil": profile}
    app.gps_tracking_state = gps_state
    app.connection_indicator = None
    app.websocket_state = "desconectado"
    return app


def indicator_text(app):
    return app._connection_indicator_text().value


def test_admin_indicator_uses_websocket_state():
    app = make_app("ADMIN")
    app.connection_indicator = type("Indicator", (), {"content": None})()

    app._set_connection_state("conectado")

    assert app.websocket_state == "conectado"
    assert app.connection_indicator.content.value == "● Conectado"


def test_gestor_indicator_uses_websocket_state():
    app = make_app("GESTOR")
    app.connection_indicator = type("Indicator", (), {"content": None})()

    app._set_connection_state("desconectado")

    assert app.connection_indicator.content.value == "● Desconectado"


def test_motorista_indicator_uses_gps_state_instead_of_websocket_state():
    app = make_app("MOTORISTA", "gps_ativo")

    app._set_connection_state("desconectado")

    assert indicator_text(app) == "GPS ativo"


def test_motorista_indicator_updates_for_permission_state():
    app = make_app("MOTORISTA")
    app.connection_indicator = type("Indicator", (), {"content": None})()

    app._set_gps_tracking_state("aguardando_permissao")

    assert app.connection_indicator.content.value == "Aguardando permissão de localização"


def test_motorista_indicator_updates_for_error_state():
    app = make_app("MOTORISTA")
    app.connection_indicator = type("Indicator", (), {"content": None})()

    app._set_gps_tracking_state("erro_temporario")

    assert app.connection_indicator.content.value == "Erro temporário no envio da localização"