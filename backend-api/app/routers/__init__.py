from .auth import router as auth_router
from .clientes import router as clientes_router
from .entregas import router as entregas_router
from .organizacoes import router as organizacoes_router
from .pedidos import router as pedidos_router
from .produtos import router as produtos_router
from .rotas import router as rotas_router
from .usuarios import router as usuarios_router
from .veiculos import router as veiculos_router
from .relatorios import router as relatorios_router

__all__ = [
    "auth_router",
    "clientes_router",
    "entregas_router",
    "organizacoes_router",
    "pedidos_router",
    "produtos_router",
    "rotas_router",
    "usuarios_router",
    "veiculos_router",
    "relatorios_router",
]
