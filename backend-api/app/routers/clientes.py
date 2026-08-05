from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import admin, commit, get_or_404, staff
from ..models import Cliente, Endereco, Entrega, Pedido, Usuario
from ..schemas import ClienteCreate, ClienteOut, EnderecoCreate, EnderecoOut, StatusIn

router = APIRouter(prefix="/clientes")


@router.get("", response_model=list[ClienteOut])
def list_clients(
    busca: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Usuario = Depends(staff),
):
    stmt = select(Cliente).order_by(Cliente.nome)
    if busca:
        stmt = stmt.where(Cliente.nome.ilike(f"%{busca}%"))
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("", response_model=ClienteOut, status_code=201)
def create_client(data: ClienteCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    client = Cliente(**data.model_dump())
    db.add(client)
    commit(db)
    return client


@router.put("/{client_id}", response_model=ClienteOut)
def update_client(
    client_id: int, data: ClienteCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    client = get_or_404(db, Cliente, client_id)
    for key, value in data.model_dump().items():
        setattr(client, key, value)
    commit(db)
    return client


@router.patch("/{client_id}/status", response_model=ClienteOut)
def client_status(
    client_id: int, data: StatusIn, db: Session = Depends(get_db), _: Usuario = Depends(admin)
):
    client = get_or_404(db, Cliente, client_id)
    client.ativo = data.ativo
    commit(db)
    return client


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    client = get_or_404(db, Cliente, client_id)
    has_orders = db.scalar(select(func.count()).select_from(Pedido).where(Pedido.cliente_id == client_id))
    if has_orders:
        raise HTTPException(409, "Cliente está em uso e não pode ser excluído")
    db.delete(client)
    commit(db)


@router.get("/{client_id}/enderecos", response_model=list[EnderecoOut])
def list_addresses(client_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    get_or_404(db, Cliente, client_id)
    return db.scalars(select(Endereco).where(Endereco.cliente_id == client_id)).all()


@router.post("/{client_id}/enderecos", response_model=EnderecoOut, status_code=201)
def create_address(
    client_id: int, data: EnderecoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    get_or_404(db, Cliente, client_id)
    address = Endereco(cliente_id=client_id, **data.model_dump())
    db.add(address)
    commit(db)
    return address


@router.put("/{client_id}/enderecos/{address_id}", response_model=EnderecoOut)
def update_address(
    client_id: int, address_id: int, data: EnderecoCreate,
    db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    address = get_or_404(db, Endereco, address_id)
    if address.cliente_id != client_id:
        raise HTTPException(404, "Registro não encontrado")
    for key, value in data.model_dump().items():
        setattr(address, key, value)
    commit(db)
    return address


@router.delete("/{client_id}/enderecos/{address_id}", status_code=204)
def delete_address(
    client_id: int, address_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    address = get_or_404(db, Endereco, address_id)
    if address.cliente_id != client_id:
        raise HTTPException(404, "Registro não encontrado")
    used = db.scalar(
        select(func.count()).select_from(Entrega).where(
            (Entrega.endereco_origem_id == address_id) | (Entrega.endereco_destino_id == address_id)
        )
    )
    if used:
        raise HTTPException(409, "Endereço está em uso e não pode ser excluído")
    db.delete(address)
    commit(db)
