import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from .api_maps import router as maps_router
from .config import settings
from .database import Base, SessionLocal, engine
from .routers import (
    auth_router,
    clientes_router,
    entregas_router,
    organizacoes_router,
    pedidos_router,
    produtos_router,
    relatorios_router,
    rotas_router,
    usuarios_router,
    veiculos_router,
)
from .seed import seed_database
from .tracking import TrackingConnection, manager
from .database import SessionLocal
from .models import Perfil
from .security import authenticate_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env in {"development", "test"}:
        Base.metadata.create_all(engine)
    if settings.seed_database and settings.app_env in {"development", "test"}:
        with SessionLocal() as db:
            seed_database(db)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router, prefix="/api")
app.include_router(usuarios_router, prefix="/api")
app.include_router(organizacoes_router, prefix="/api")
app.include_router(clientes_router, prefix="/api")
app.include_router(produtos_router, prefix="/api")
app.include_router(pedidos_router, prefix="/api")
app.include_router(entregas_router, prefix="/api")
app.include_router(veiculos_router, prefix="/api")
app.include_router(rotas_router, prefix="/api")
app.include_router(relatorios_router, prefix="/api")
app.include_router(maps_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/tracking")
async def tracking_socket(websocket: WebSocket):
    authorization = websocket.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        await websocket.close(code=1008, reason="Authorization obrigatória")
        return
    try:
        with SessionLocal() as db:
            user = authenticate_token(authorization[7:].strip(), db)
            if user.perfil == Perfil.MOTORISTA:
                await websocket.close(code=1008, reason="Perfil não autorizado")
                return
            connection = TrackingConnection(websocket, user.id, user.perfil, user.organizacao_id)
            await manager.connect(connection)
    except Exception:
        await websocket.close(code=1008, reason="Autenticação inválida")
        return
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        manager.disconnect(websocket)
