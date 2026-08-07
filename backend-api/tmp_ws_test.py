from fastapi.testclient import TestClient
from app.main import app

print('starting test')
with TestClient(app) as client:
    try:
        with client.websocket_connect('/ws/tracking') as websocket:
            print('connected inside context')
            websocket.send_json({'type': 'hello'})
            print('sent hello')
    except Exception as exc:
        print('caught exception', type(exc), exc)
print('done')
