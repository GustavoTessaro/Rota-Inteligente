from sqlalchemy import or_
from app.database import SessionLocal
from app.models import (
    Organizacao,
    Usuario,
    Veiculo,
    Cliente,
    Endereco,
    Pedido,
    Rota,
    Entrega,
    PedidoItem,
    RotaEntrega,
)

LIKE_PATTERNS = [
    "%HOMOLOGACAO_GOOGLE%",
    "%homologacaogoogle%",
    "%HOMOLOGACAO_GOOGLE_FASE5%",
    "%HOMOLOGACAO_GOOGLE_REAL%",
]
from sqlalchemy import text

from app.database import SessionLocal
from app.models import Endereco, Organizacao, Usuario, Veiculo

EXPECTED_ORGANIZACAO_ID = 4
EXPECTED_USUARIO_ID = 7
EXPECTED_ENDERECO_ID = 19
EXPECTED_VEICULO_ID = 4
TEST_NAME_PREFIX = "HOMOLOGACAO_GOOGLE_FASE5"


def validate_cluster(db):
    organizacao = db.get(Organizacao, EXPECTED_ORGANIZACAO_ID)
    usuario = db.get(Usuario, EXPECTED_USUARIO_ID)
    endereco = db.get(Endereco, EXPECTED_ENDERECO_ID)
    veiculo = db.get(Veiculo, EXPECTED_VEICULO_ID)

    if not organizacao or not organizacao.nome.startswith(TEST_NAME_PREFIX):
        raise RuntimeError("Organização residual não corresponde à identidade esperada")
    if organizacao.endereco_id != EXPECTED_ENDERECO_ID:
        raise RuntimeError("Organização residual não aponta exatamente para o endereço esperado")
    if (
        not usuario
        or usuario.organizacao_id != EXPECTED_ORGANIZACAO_ID
        or not usuario.nome.startswith(TEST_NAME_PREFIX)
    ):
        raise RuntimeError("Usuário residual não corresponde à identidade esperada")
    if not endereco or endereco.organizacao_id != EXPECTED_ORGANIZACAO_ID:
        raise RuntimeError("Endereço residual não corresponde à identidade esperada")
    if not veiculo or veiculo.organizacao_id != EXPECTED_ORGANIZACAO_ID:
        raise RuntimeError("Veículo residual não corresponde à identidade esperada")

    unexpected = {
        "rotas": db.execute(
            text("SELECT id FROM rotas WHERE organizacao_id = :org_id"),
            {"org_id": EXPECTED_ORGANIZACAO_ID},
        ).scalars().all(),
        "pedidos": db.execute(
            text("SELECT id FROM pedidos WHERE organizacao_id = :org_id"),
            {"org_id": EXPECTED_ORGANIZACAO_ID},
        ).scalars().all(),
        "entregas": db.execute(
            text(
                "SELECT e.id FROM entregas e JOIN pedidos p ON p.id = e.pedido_id "
                "WHERE p.organizacao_id = :org_id"
            ),
            {"org_id": EXPECTED_ORGANIZACAO_ID},
        ).scalars().all(),
        "alternativas": db.execute(
            text(
                "SELECT ra.id FROM rota_alternativas ra JOIN rotas r ON r.id = ra.rota_id "
                "WHERE r.organizacao_id = :org_id"
            ),
            {"org_id": EXPECTED_ORGANIZACAO_ID},
        ).scalars().all(),
    }
    unexpected = {table: ids for table, ids in unexpected.items() if ids}
    if unexpected:
        raise RuntimeError(f"Relacionamentos não previstos encontrados: {unexpected}")


def main():
    with SessionLocal() as db:
        with db.begin():
            validate_cluster(db)
            organizacao = db.get(Organizacao, EXPECTED_ORGANIZACAO_ID)
            organizacao.endereco_id = None
            db.flush()
            db.delete(db.get(Veiculo, EXPECTED_VEICULO_ID))
            db.delete(db.get(Endereco, EXPECTED_ENDERECO_ID))
            db.delete(db.get(Usuario, EXPECTED_USUARIO_ID))
            db.delete(db.get(Organizacao, EXPECTED_ORGANIZACAO_ID))

    with SessionLocal() as db:
        remaining = {
            "organizacao": db.get(Organizacao, EXPECTED_ORGANIZACAO_ID),
            "usuario": db.get(Usuario, EXPECTED_USUARIO_ID),
            "endereco": db.get(Endereco, EXPECTED_ENDERECO_ID),
            "veiculo": db.get(Veiculo, EXPECTED_VEICULO_ID),
        }
        remaining = [name for name, record in remaining.items() if record is not None]
        if remaining:
            raise RuntimeError(f"Registros residuais após o commit: {remaining}")

    print("CLEANUP_SUCCESS=True")
    print("REMOVED_IDS=organizacao:4,usuario:7,endereco:19,veiculo:4")


if __name__ == "__main__":
    main()
