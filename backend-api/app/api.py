from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .deps import apply_delivery_status as shared_apply_delivery_status
from .models import (
    Cliente,
    ComprovanteEntrega,
    Endereco,
    Entrega,
    HistoricoEntrega,
    Ocorrencia,
    Organizacao,
    Pedido,
    PedidoItem,
    Perfil,
    Produto,
    Rota,
    RotaEntrega,
    RotaHistorico,
    StatusEntrega,
    StatusPedido,
    StatusRota,
    TipoEventoRota,
    Usuario,
    Veiculo,
    StatusVeiculo,
)
from .schemas import (
    AtribuirIn,
    ClienteCreate,
    ClienteOut,
    ComprovanteIn,
    ComprovanteOut,
    DashboardOut,
    EnderecoCreate,
    EnderecoOut,
    EntregaCreate,
    EntregaOut,
    EntregaStatusIn,
    LoginIn,
    OrganizacaoCreate,
    OrganizacaoOut,
    OcorrenciaIn,
    OcorrenciaOut,
    PedidoCreate,
    PedidoItemIn,
    PedidoItemOut,
    PedidoOut,
    PedidoStatusIn,
    ProdutoCreate,
    ProdutoOut,
    RotaCreate,
    RotaHistoricoOut,
    RotaOut,
    RotaStatusIn,
    StatusIn,
    TokenOut,
    UsuarioCreate,
    UsuarioOut,
    UsuarioUpdate,
    VeiculoCreate,
    VeiculoOut,
    VeiculoUpdate,
)
from .security import create_token, current_user, hash_password, require_roles, verify_password

router = APIRouter(prefix="/api")
admin = require_roles(Perfil.ADMIN)
staff = require_roles(Perfil.ADMIN, Perfil.GESTOR)
delivery_roles = require_roles(Perfil.ADMIN, Perfil.GESTOR, Perfil.MOTORISTA)


def get_or_404(db: Session, model, item_id: int):
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(404, "Registro não encontrado")
    return item


def commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Registro duplicado ou relacionamento inválido")


def validate_driver(db: Session, driver_id: int) -> Usuario:
    driver = get_or_404(db, Usuario, driver_id)
    if driver.perfil != Perfil.MOTORISTA or not driver.ativo:
        raise HTTPException(422, "O motorista deve possuir perfil MOTORISTA e estar ativo")
    return driver


def validate_organization(db: Session, organization_id: int) -> Organizacao:
    organization = get_or_404(db, Organizacao, organization_id)
    if not organization.ativo:
        raise HTTPException(422, "Organização inativa não pode receber veículos")
    return organization


def ensure_vehicle_access_scope(user: Usuario, vehicle: Veiculo):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None or vehicle.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Acesso negado ao veículo de outra organização")
        return
    if user.perfil == Perfil.MOTORISTA:
        if vehicle.motorista_id != user.id:
            raise HTTPException(403, "Acesso negado ao veículo de outro motorista")
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def ensure_vehicle_payload_scope(user: Usuario, data: VeiculoCreate):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode gerir veículos")
        if data.organizacao_id is not None and data.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Gestor só pode gerir veículos de sua organização")
        data.organizacao_id = user.organizacao_id
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def ensure_manageable_user_payload(current: Usuario, data):
    if current.perfil == Perfil.ADMIN:
        return
    if current.perfil != Perfil.GESTOR:
        raise HTTPException(403, "Perfil sem permissão para esta operação")
    if data.perfil == Perfil.ADMIN:
        raise HTTPException(403, "Gestor não pode criar ou alterar usuários com perfil ADMIN")
    if current.organizacao_id is None:
        raise HTTPException(403, "Gestor sem organização não pode gerir usuários")
    if data.organizacao_id is not None and data.organizacao_id != current.organizacao_id:
        raise HTTPException(403, "Gestor só pode gerir usuários de sua organização")
    data.organizacao_id = current.organizacao_id


def ensure_user_management_scope(current: Usuario, target: Usuario):
    if current.perfil == Perfil.ADMIN:
        return
    if current.perfil != Perfil.GESTOR:
        raise HTTPException(403, "Perfil sem permissão para esta operação")
    if current.organizacao_id is None:
        raise HTTPException(403, "Gestor sem organização não pode gerir usuários")
    if target.perfil == Perfil.ADMIN:
        raise HTTPException(403, "Gestor não pode criar ou alterar usuários com perfil ADMIN")
    if target.organizacao_id is not None and target.organizacao_id != current.organizacao_id:
        raise HTTPException(403, "Gestor só pode gerir usuários de sua organização")
    if target.organizacao_id is None:
        target.organizacao_id = current.organizacao_id


def order_has_delivery(db: Session, order_id: int) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Entrega).where(Entrega.pedido_id == order_id)))


def recalculate_order_total(order: Pedido):
    order.valor_total = sum((item.valor_unitario * item.quantidade for item in order.itens), Decimal("0"))


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(Usuario).where(Usuario.email == data.email.lower()))
    if not user or not user.ativo or not verify_password(data.senha, user.senha_hash):
        raise HTTPException(401, "E-mail ou senha inválidos")
    return {"token": create_token(user), "usuario": user}


@router.get("/auth/me", response_model=UsuarioOut)
def me(user: Usuario = Depends(current_user)):
    return user


@router.post("/auth/logout")
def logout(_: Usuario = Depends(current_user)):
    return {"mensagem": "Sessão encerrada. Remova o token armazenado no aplicativo."}


@router.get("/usuarios", response_model=list[UsuarioOut])
def list_users(
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), user: Usuario = Depends(staff)
):
    stmt = select(Usuario).order_by(Usuario.nome)
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode listar usuários")
        stmt = stmt.where(Usuario.organizacao_id == user.organizacao_id)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("/usuarios", response_model=UsuarioOut, status_code=201)
def create_user(data: UsuarioCreate, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    ensure_manageable_user_payload(user, data)
    user_entity = Usuario(
        nome=data.nome, email=data.email.lower(), senha_hash=hash_password(data.senha),
        telefone=data.telefone, perfil=data.perfil, organizacao_id=data.organizacao_id,
    )
    db.add(user_entity)
    commit(db)
    return user_entity


@router.put("/usuarios/{user_id}", response_model=UsuarioOut)
def update_user(user_id: int, data: UsuarioUpdate, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    existing_user = get_or_404(db, Usuario, user_id)
    ensure_user_management_scope(user, existing_user)
    ensure_manageable_user_payload(user, data)
    existing_user.nome = data.nome
    existing_user.email = data.email.lower()
    if data.senha:
        existing_user.senha_hash = hash_password(data.senha)
    existing_user.telefone = data.telefone
    existing_user.perfil = data.perfil
    existing_user.organizacao_id = data.organizacao_id
    commit(db)
    return existing_user


@router.patch("/usuarios/{user_id}/status", response_model=UsuarioOut)
def user_status(user_id: int, data: StatusIn, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    existing_user = get_or_404(db, Usuario, user_id)
    ensure_user_management_scope(user, existing_user)
    existing_user.ativo = data.ativo
    commit(db)
    return existing_user


@router.delete("/usuarios/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), current: Usuario = Depends(staff)):
    user = get_or_404(db, Usuario, user_id)
    ensure_user_management_scope(current, user)
    if user.id == current.id:
        raise HTTPException(422, "O usuário logado não pode ser excluído")
    linked_counts = [
        db.scalar(select(func.count()).select_from(Entrega).where(Entrega.entregador_id == user_id)),
        db.scalar(select(func.count()).select_from(Pedido).where(Pedido.criado_por == user_id)),
        db.scalar(select(func.count()).select_from(HistoricoEntrega).where(HistoricoEntrega.alterado_por == user_id)),
        db.scalar(select(func.count()).select_from(Ocorrencia).where(Ocorrencia.registrado_por == user_id)),
        db.scalar(select(func.count()).select_from(ComprovanteEntrega).where(ComprovanteEntrega.criado_por == user_id)),
    ]
    if any(linked_counts):
        raise HTTPException(409, "Usuário está em uso e não pode ser excluído")
    db.delete(user)
    commit(db)


@router.get("/veiculos", response_model=list[VeiculoOut])
def list_vehicles(
    busca: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: Usuario = Depends(delivery_roles),
):
    stmt = select(Veiculo).order_by(Veiculo.placa)
    if busca:
        stmt = stmt.where(
            (Veiculo.placa.ilike(f"%{busca}%")) |
            (Veiculo.modelo.ilike(f"%{busca}%")) |
            (Veiculo.marca.ilike(f"%{busca}%")) |
            (Veiculo.cor.ilike(f"%{busca}%"))
        )
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode listar veículos")
        stmt = stmt.where(Veiculo.organizacao_id == user.organizacao_id)
    if user.perfil == Perfil.MOTORISTA:
        stmt = stmt.where(Veiculo.motorista_id == user.id)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("/veiculos", response_model=VeiculoOut, status_code=201)
def create_vehicle(data: VeiculoCreate, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    ensure_vehicle_payload_scope(user, data)
    if data.organizacao_id is None:
        raise HTTPException(422, "Veículo deve pertencer a uma organização")
    validate_organization(db, data.organizacao_id)
    if data.motorista_id is not None:
        validate_driver(db, data.motorista_id)
    vehicle = Veiculo(**data.model_dump())
    db.add(vehicle)
    commit(db)
    return vehicle


@router.get("/veiculos/{vehicle_id}", response_model=VeiculoOut)
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    vehicle = get_or_404(db, Veiculo, vehicle_id)
    ensure_vehicle_access_scope(user, vehicle)
    return vehicle


@router.put("/veiculos/{vehicle_id}", response_model=VeiculoOut)
def update_vehicle(vehicle_id: int, data: VeiculoUpdate, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    vehicle = get_or_404(db, Veiculo, vehicle_id)
    ensure_vehicle_access_scope(user, vehicle)
    ensure_vehicle_payload_scope(user, data)
    if data.organizacao_id is None:
        raise HTTPException(422, "Veículo deve pertencer a uma organização")
    validate_organization(db, data.organizacao_id)
    if data.motorista_id is not None:
        validate_driver(db, data.motorista_id)
    for key, value in data.model_dump().items():
        setattr(vehicle, key, value)
    commit(db)
    return vehicle


@router.delete("/veiculos/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    vehicle = get_or_404(db, Veiculo, vehicle_id)
    ensure_vehicle_access_scope(user, vehicle)
    db.delete(vehicle)
    commit(db)


@router.get("/organizacoes", response_model=list[OrganizacaoOut])
def list_organizacoes(
    busca: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), _: Usuario = Depends(admin)
):
    stmt = select(Organizacao).order_by(Organizacao.nome)
    if busca:
        stmt = stmt.where(Organizacao.nome.ilike(f"%{busca}%"))
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("/organizacoes", response_model=OrganizacaoOut, status_code=201)
def create_organizacao(data: OrganizacaoCreate, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    # If endereco_id provided, ensure it exists and keep legacy endereco text for compatibility
    if data.endereco_id is not None:
        get_or_404(db, Endereco, data.endereco_id)
    organizacao = Organizacao(**data.model_dump(exclude={"endereco_id"}))
    if data.endereco_id is not None:
        organizacao.endereco_id = data.endereco_id
    db.add(organizacao)
    commit(db)
    return organizacao


@router.put("/organizacoes/{org_id}", response_model=OrganizacaoOut)
def update_organizacao(org_id: int, data: OrganizacaoCreate, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    organizacao = get_or_404(db, Organizacao, org_id)
    payload = data.model_dump()
    endereco_id = payload.pop("endereco_id", None)
    for key, value in payload.items():
        setattr(organizacao, key, value)
    if endereco_id is not None:
        get_or_404(db, Endereco, endereco_id)
        organizacao.endereco_id = endereco_id
    commit(db)
    return organizacao


@router.delete("/organizacoes/{org_id}", status_code=204)
def delete_organizacao(org_id: int, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    organizacao = get_or_404(db, Organizacao, org_id)
    linked_users = db.scalar(select(func.count()).select_from(Usuario).where(Usuario.organizacao_id == org_id))
    if linked_users:
        raise HTTPException(409, "Organização está em uso e não pode ser excluída")
    db.delete(organizacao)
    commit(db)


@router.get("/clientes", response_model=list[ClienteOut])
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


@router.post("/clientes", response_model=ClienteOut, status_code=201)
def create_client(data: ClienteCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    client = Cliente(**data.model_dump())
    db.add(client)
    commit(db)
    return client


@router.put("/clientes/{client_id}", response_model=ClienteOut)
def update_client(
    client_id: int, data: ClienteCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    client = get_or_404(db, Cliente, client_id)
    for key, value in data.model_dump().items():
        setattr(client, key, value)
    commit(db)
    return client


@router.patch("/clientes/{client_id}/status", response_model=ClienteOut)
def client_status(
    client_id: int, data: StatusIn, db: Session = Depends(get_db), _: Usuario = Depends(admin)
):
    client = get_or_404(db, Cliente, client_id)
    client.ativo = data.ativo
    commit(db)
    return client


@router.delete("/clientes/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    client = get_or_404(db, Cliente, client_id)
    has_orders = db.scalar(select(func.count()).select_from(Pedido).where(Pedido.cliente_id == client_id))
    if has_orders:
        raise HTTPException(409, "Cliente está em uso e não pode ser excluído")
    db.delete(client)
    commit(db)


@router.get("/clientes/{client_id}/enderecos", response_model=list[EnderecoOut])
def list_addresses(client_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    get_or_404(db, Cliente, client_id)
    return db.scalars(select(Endereco).where(Endereco.cliente_id == client_id)).all()


@router.post("/clientes/{client_id}/enderecos", response_model=EnderecoOut, status_code=201)
def create_address(
    client_id: int, data: EnderecoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    get_or_404(db, Cliente, client_id)
    address = Endereco(cliente_id=client_id, **data.model_dump())
    db.add(address)
    commit(db)
    return address


@router.put("/clientes/{client_id}/enderecos/{address_id}", response_model=EnderecoOut)
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


@router.delete("/clientes/{client_id}/enderecos/{address_id}", status_code=204)
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


@router.get("/produtos", response_model=list[ProdutoOut])
def list_products(
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    stmt = select(Produto).order_by(Produto.nome)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("/produtos", response_model=ProdutoOut, status_code=201)
def create_product(data: ProdutoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = Produto(**data.model_dump())
    db.add(product)
    commit(db)
    return product


@router.put("/produtos/{product_id}", response_model=ProdutoOut)
def update_product(product_id: int, data: ProdutoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = get_or_404(db, Produto, product_id)
    for key, value in data.model_dump().items():
        setattr(product, key, value)
    commit(db)
    return product


@router.patch("/produtos/{product_id}/status", response_model=ProdutoOut)
def product_status(product_id: int, data: StatusIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = get_or_404(db, Produto, product_id)
    product.ativo = data.ativo
    commit(db)
    return product


@router.delete("/produtos/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = get_or_404(db, Produto, product_id)
    used = db.scalar(select(func.count()).select_from(PedidoItem).where(PedidoItem.produto_id == product_id))
    if used:
        raise HTTPException(409, "Produto está em uso e não pode ser excluído")
    db.delete(product)
    commit(db)


@router.get("/pedidos", response_model=list[PedidoOut])
def list_orders(
    status: StatusPedido | None = None,
    busca: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Usuario = Depends(staff),
):
    stmt = select(Pedido).order_by(Pedido.criado_em.desc())
    if status:
        stmt = stmt.where(Pedido.status == status)
    if busca:
        stmt = stmt.where(Pedido.numero_pedido.ilike(f"%{busca}%"))
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("/pedidos", response_model=PedidoOut, status_code=201)
def create_order(
    data: PedidoCreate, db: Session = Depends(get_db), user: Usuario = Depends(staff)
):
    client = get_or_404(db, Cliente, data.cliente_id)
    if not client.ativo:
        raise HTTPException(422, "Cliente inativo não pode receber novo pedido")
    product_ids = [item.produto_id for item in data.itens]
    products = db.scalars(select(Produto).where(Produto.id.in_(product_ids), Produto.ativo.is_(True))).all()
    if len(set(product_ids)) != len(products):
        raise HTTPException(422, "Um ou mais produtos não existem ou estão inativos")
    total = sum((item.valor_unitario * item.quantidade for item in data.itens), Decimal("0"))
    order = Pedido(
        cliente_id=data.cliente_id,
        numero_pedido=f"PED-{datetime.now():%Y%m%d}-{uuid4().hex[:6].upper()}",
        prioridade=data.prioridade,
        forma_pagamento=data.forma_pagamento,
        observacoes=data.observacoes,
        valor_total=total,
        criado_por=user.id,
    )
    order.itens = [PedidoItem(**item.model_dump()) for item in data.itens]
    db.add(order)
    commit(db)
    return order


@router.put("/pedidos/{order_id}", response_model=PedidoOut)
def update_order(order_id: int, data: PedidoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    if order_has_delivery(db, order_id):
        raise HTTPException(409, "Pedido está em uso e não pode ser editado")
    client = get_or_404(db, Cliente, data.cliente_id)
    if not client.ativo:
        raise HTTPException(422, "Cliente inativo não pode receber pedido")
    product_ids = [item.produto_id for item in data.itens]
    products = db.scalars(select(Produto).where(Produto.id.in_(product_ids), Produto.ativo.is_(True))).all()
    if len(set(product_ids)) != len(products):
        raise HTTPException(422, "Um ou mais produtos não existem ou estão inativos")
    order.cliente_id = data.cliente_id
    order.prioridade = data.prioridade
    order.forma_pagamento = data.forma_pagamento
    order.observacoes = data.observacoes
    order.itens = [PedidoItem(**item.model_dump()) for item in data.itens]
    recalculate_order_total(order)
    commit(db)
    return order


@router.delete("/pedidos/{order_id}", status_code=204)
def delete_order(order_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    if order_has_delivery(db, order_id):
        raise HTTPException(409, "Pedido está em uso e não pode ser excluído")
    db.delete(order)
    commit(db)


@router.get("/pedidos/{order_id}/itens", response_model=list[PedidoItemOut])
def list_order_items(order_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    get_or_404(db, Pedido, order_id)
    return db.scalars(select(PedidoItem).where(PedidoItem.pedido_id == order_id)).all()


@router.post("/pedidos/{order_id}/itens", response_model=PedidoItemOut, status_code=201)
def create_order_item(
    order_id: int, data: PedidoItemIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    order = get_or_404(db, Pedido, order_id)
    if order_has_delivery(db, order_id):
        raise HTTPException(409, "Pedido está em uso e não pode ser editado")
    product = get_or_404(db, Produto, data.produto_id)
    if not product.ativo:
        raise HTTPException(422, "Produto inativo não pode ser adicionado ao pedido")
    item = PedidoItem(pedido_id=order_id, **data.model_dump())
    db.add(item)
    db.flush()
    order.valor_total += data.valor_unitario * data.quantidade
    commit(db)
    return item


@router.put("/pedidos/{order_id}/itens/{item_id}", response_model=PedidoItemOut)
def update_order_item(
    order_id: int, item_id: int, data: PedidoItemIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    order = get_or_404(db, Pedido, order_id)
    if order_has_delivery(db, order_id):
        raise HTTPException(409, "Pedido está em uso e não pode ser editado")
    item = get_or_404(db, PedidoItem, item_id)
    if item.pedido_id != order_id:
        raise HTTPException(404, "Registro não encontrado")
    product = get_or_404(db, Produto, data.produto_id)
    if not product.ativo:
        raise HTTPException(422, "Produto inativo não pode ser adicionado ao pedido")
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    recalculate_order_total(order)
    commit(db)
    return item


@router.delete("/pedidos/{order_id}/itens/{item_id}", status_code=204)
def delete_order_item(order_id: int, item_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    if order_has_delivery(db, order_id):
        raise HTTPException(409, "Pedido está em uso e não pode ser editado")
    item = get_or_404(db, PedidoItem, item_id)
    if item.pedido_id != order_id:
        raise HTTPException(404, "Registro não encontrado")
    if len(order.itens) <= 1:
        raise HTTPException(422, "Pedido deve possuir pelo menos um item")
    db.delete(item)
    db.flush()
    order.itens = [existing for existing in order.itens if existing.id != item_id]
    recalculate_order_total(order)
    commit(db)


@router.patch("/pedidos/{order_id}/cancelar", response_model=PedidoOut)
def cancel_order(order_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    order.status = StatusPedido.CANCELADO
    commit(db)
    return order


@router.patch("/pedidos/{order_id}/status", response_model=PedidoOut)
def order_status(order_id: int, data: PedidoStatusIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    order.status = data.status
    commit(db)
    return order


@router.get("/entregas", response_model=list[EntregaOut])
def list_deliveries(
    status: StatusEntrega | None = None,
    entregador_id: int | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Usuario = Depends(staff),
):
    stmt = select(Entrega).order_by(Entrega.criado_em.desc())
    if status:
        stmt = stmt.where(Entrega.status == status)
    if entregador_id:
        stmt = stmt.where(Entrega.entregador_id == entregador_id)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.get("/entregas/minhas", response_model=list[EntregaOut])
def my_deliveries(db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    if user.perfil != Perfil.MOTORISTA:
        raise HTTPException(403, "Endpoint exclusivo para motoristas")
    return db.scalars(
        select(Entrega).where(Entrega.entregador_id == user.id).order_by(Entrega.previsao_entrega)
    ).all()


@router.post("/entregas", response_model=EntregaOut, status_code=201)
def create_delivery(
    data: EntregaCreate, db: Session = Depends(get_db), user: Usuario = Depends(staff)
):
    get_or_404(db, Pedido, data.pedido_id)
    get_or_404(db, Endereco, data.endereco_origem_id)
    get_or_404(db, Endereco, data.endereco_destino_id)
    if data.entregador_id:
        validate_driver(db, data.entregador_id)
    delivery = Entrega(**data.model_dump())
    db.add(delivery)
    db.flush()
    db.add(HistoricoEntrega(
        entrega_id=delivery.id, status_anterior=None,
        status_novo=StatusEntrega.AGUARDANDO_COLETA.value,
        observacao="Entrega criada", alterado_por=user.id,
    ))
    commit(db)
    return delivery


@router.get("/entregas/{delivery_id}", response_model=EntregaOut)
def get_delivery(
    delivery_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)
):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    return delivery


@router.put("/entregas/{delivery_id}", response_model=EntregaOut)
def update_delivery(
    delivery_id: int, data: EntregaCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    delivery = get_or_404(db, Entrega, delivery_id)
    get_or_404(db, Pedido, data.pedido_id)
    get_or_404(db, Endereco, data.endereco_origem_id)
    get_or_404(db, Endereco, data.endereco_destino_id)
    if data.entregador_id:
        validate_driver(db, data.entregador_id)
    for key, value in data.model_dump().items():
        setattr(delivery, key, value)
    commit(db)
    return delivery


@router.delete("/entregas/{delivery_id}", status_code=204)
def delete_delivery(delivery_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    delivery = get_or_404(db, Entrega, delivery_id)
    linked_counts = [
        db.scalar(select(func.count()).select_from(HistoricoEntrega).where(HistoricoEntrega.entrega_id == delivery_id)),
        db.scalar(select(func.count()).select_from(Ocorrencia).where(Ocorrencia.entrega_id == delivery_id)),
        db.scalar(select(func.count()).select_from(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id)),
    ]
    if any(linked_counts):
        raise HTTPException(409, "Entrega está em uso e não pode ser excluída")
    db.delete(delivery)
    commit(db)


@router.patch("/entregas/{delivery_id}/atribuir", response_model=EntregaOut)
def assign_delivery(
    delivery_id: int, data: AtribuirIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    delivery = get_or_404(db, Entrega, delivery_id)
    validate_driver(db, data.entregador_id)
    delivery.entregador_id = data.entregador_id
    commit(db)
    return delivery


@router.patch("/entregas/{delivery_id}/status", response_model=EntregaOut)
def update_delivery_status(
    delivery_id: int,
    data: EntregaStatusIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(delivery_roles),
):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    if delivery.status == StatusEntrega.CANCELADA and user.perfil != Perfil.ADMIN:
        raise HTTPException(422, "Somente administrador pode reabrir entrega cancelada")
    if delivery.status == StatusEntrega.CANCELADA and not data.observacao:
        raise HTTPException(422, "Informe a justificativa para reabrir a entrega")
    if data.status == StatusEntrega.ENTREGUE and not delivery.comprovante:
        raise HTTPException(422, "Registre o comprovante antes de concluir a entrega")
    shared_apply_delivery_status(db, delivery, data.status, data.observacao, user.id)
    commit(db)
    return delivery


@router.get("/entregas/{delivery_id}/historico")
def delivery_history(
    delivery_id: int, db: Session = Depends(get_db), _: Usuario = Depends(current_user)
):
    get_or_404(db, Entrega, delivery_id)
    return db.scalars(
        select(HistoricoEntrega).where(HistoricoEntrega.entrega_id == delivery_id)
        .order_by(HistoricoEntrega.criado_em)
    ).all()


@router.post("/entregas/{delivery_id}/ocorrencias", response_model=OcorrenciaOut, status_code=201)
def create_incident(
    delivery_id: int, data: OcorrenciaIn, db: Session = Depends(get_db),
    user: Usuario = Depends(delivery_roles),
):
    get_or_404(db, Entrega, delivery_id)
    incident = Ocorrencia(entrega_id=delivery_id, registrado_por=user.id, **data.model_dump())
    db.add(incident)
    commit(db)
    return incident


@router.get("/entregas/{delivery_id}/ocorrencias", response_model=list[OcorrenciaOut])
def list_incidents(
    delivery_id: int, db: Session = Depends(get_db), _: Usuario = Depends(current_user)
):
    get_or_404(db, Entrega, delivery_id)
    return db.scalars(select(Ocorrencia).where(Ocorrencia.entrega_id == delivery_id)).all()


@router.put("/entregas/{delivery_id}/ocorrencias/{incident_id}", response_model=OcorrenciaOut)
def update_incident(
    delivery_id: int, incident_id: int, data: OcorrenciaIn,
    db: Session = Depends(get_db), _: Usuario = Depends(delivery_roles)
):
    incident = get_or_404(db, Ocorrencia, incident_id)
    if incident.entrega_id != delivery_id:
        raise HTTPException(404, "Registro não encontrado")
    incident.tipo = data.tipo
    incident.descricao = data.descricao
    commit(db)
    return incident


@router.delete("/entregas/{delivery_id}/ocorrencias/{incident_id}", status_code=204)
def delete_incident(
    delivery_id: int, incident_id: int, db: Session = Depends(get_db), _: Usuario = Depends(delivery_roles)
):
    incident = get_or_404(db, Ocorrencia, incident_id)
    if incident.entrega_id != delivery_id:
        raise HTTPException(404, "Registro não encontrado")
    db.delete(incident)
    commit(db)


@router.post("/entregas/{delivery_id}/comprovante", response_model=ComprovanteOut, status_code=201)
def create_receipt(
    delivery_id: int, data: ComprovanteIn, db: Session = Depends(get_db),
    user: Usuario = Depends(delivery_roles),
):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    if delivery.comprovante:
        raise HTTPException(409, "A entrega já possui comprovante")
    receipt = ComprovanteEntrega(entrega_id=delivery_id, criado_por=user.id, **data.model_dump())
    db.add(receipt)
    commit(db)
    return receipt


@router.get("/entregas/{delivery_id}/comprovante", response_model=ComprovanteOut)
def get_receipt(
    delivery_id: int, db: Session = Depends(get_db), _: Usuario = Depends(current_user)
):
    receipt = db.scalar(select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id))
    if not receipt:
        raise HTTPException(404, "Comprovante não encontrado")
    return receipt


@router.put("/entregas/{delivery_id}/comprovante", response_model=ComprovanteOut)
def update_receipt(
    delivery_id: int, data: ComprovanteIn, db: Session = Depends(get_db), user: Usuario = Depends(delivery_roles)
):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    receipt = db.scalar(select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id))
    if not receipt:
        raise HTTPException(404, "Comprovante não encontrado")
    for key, value in data.model_dump().items():
        setattr(receipt, key, value)
    commit(db)
    return receipt


@router.delete("/entregas/{delivery_id}/comprovante", status_code=204)
def delete_receipt(delivery_id: int, db: Session = Depends(get_db), user: Usuario = Depends(delivery_roles)):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    receipt = db.scalar(select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id))
    if not receipt:
        raise HTTPException(404, "Comprovante não encontrado")
    db.delete(receipt)
    commit(db)


def ensure_route_access_scope(user: Usuario, rota: Rota):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None or rota.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Acesso negado à rota de outra organização")
        return
    if user.perfil == Perfil.MOTORISTA:
        if rota.motorista_id != user.id:
            raise HTTPException(403, "Acesso negado à rota de outro motorista")
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def ensure_route_payload_scope(user: Usuario, data: RotaCreate):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode gerir rotas")
        if data.organizacao_id is not None and data.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Gestor só pode gerir rotas de sua organização")
        data.organizacao_id = user.organizacao_id
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def validate_route_delivery_entries(db: Session, route_data: RotaCreate):
    entrega_ids = set()
    for entry in route_data.entregas:
        if entry.entrega_id in entrega_ids:
            raise HTTPException(422, "Uma entrega só pode ser adicionada uma vez à rota")
        entrega_ids.add(entry.entrega_id)
        entrega = get_or_404(db, Entrega, entry.entrega_id)
        if entrega.status == StatusEntrega.CANCELADA:
            raise HTTPException(422, "Entrega cancelada não pode fazer parte da rota")


@router.get("/rotas", response_model=list[RotaOut])
def list_routes(
    status: StatusRota | None = None,
    motorista_id: int | None = None,
    veiculo_id: int | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    stmt = select(Rota).order_by(Rota.criado_em.desc())
    if status:
        stmt = stmt.where(Rota.status == status)
    if motorista_id:
        stmt = stmt.where(Rota.motorista_id == motorista_id)
    if veiculo_id:
        stmt = stmt.where(Rota.veiculo_id == veiculo_id)
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode listar rotas")
        stmt = stmt.where(Rota.organizacao_id == user.organizacao_id)
    if user.perfil == Perfil.MOTORISTA:
        stmt = stmt.where(Rota.motorista_id == user.id)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.get("/rotas/{rota_id}", response_model=RotaOut)
def get_route(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    return rota


@router.put("/rotas/{rota_id}", response_model=RotaOut)
def update_route(rota_id: int, data: RotaCreate, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    ensure_route_payload_scope(user, data)
    validate_organization(db, data.organizacao_id)
    if data.veiculo_id is not None:
        vehicle = get_or_404(db, Veiculo, data.veiculo_id)
        if vehicle.organizacao_id != data.organizacao_id:
            raise HTTPException(422, "Veículo deve pertencer à organização da rota")
    if data.motorista_id is not None:
        driver = validate_driver(db, data.motorista_id)
        if driver.organizacao_id != data.organizacao_id:
            raise HTTPException(422, "Motorista deve pertencer à organização da rota")
    if data.origem_endereco_id is not None:
        get_or_404(db, Endereco, data.origem_endereco_id)
    if data.destino_endereco_id is not None:
        get_or_404(db, Endereco, data.destino_endereco_id)
    validate_route_delivery_entries(db, data)
    for key, value in data.model_dump(exclude={"entregas"}).items():
        setattr(rota, key, value)
    rota.entregas = [RotaEntrega(**entry.model_dump()) for entry in data.entregas]
    commit(db)
    return rota


@router.delete("/rotas/{rota_id}", status_code=204)
def delete_route(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    db.delete(rota)
    commit(db)


@router.patch("/rotas/{rota_id}/status", response_model=RotaOut)
def update_route_status(
    rota_id: int,
    data: RotaStatusIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(staff),
):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    if rota.status == StatusRota.CANCELADA and user.perfil != Perfil.ADMIN:
        raise HTTPException(422, "Somente administrador pode reabrir rota cancelada")
    if data.status == StatusRota.CANCELADA and rota.status == StatusRota.FINALIZADA:
        raise HTTPException(422, "Rota finalizada não pode ser cancelada")
    previous_status = rota.status
    if data.distancia_real is not None:
        rota.distancia_real = data.distancia_real
    if data.duracao_real is not None:
        rota.duracao_real = data.duracao_real
    if data.progresso_percentual is not None:
        rota.progresso_percentual = data.progresso_percentual
    if data.quilometragem_final is not None:
        rota.quilometragem_final = data.quilometragem_final
    if data.combustivel_final is not None:
        rota.combustivel_final = data.combustivel_final
    rota.status = data.status
    if data.evento is not None or data.observacao is not None or data.entrega_id is not None:
        rota.historico.append(RotaHistorico(
            evento=data.evento or TipoEventoRota.PARTIDA,
            status_anterior=previous_status.value if previous_status else None,
            status_novo=data.status.value,
            observacao=data.observacao,
            entrega_id=data.entrega_id,
            alterado_por=user.id,
        ))
    commit(db)
    return rota


@router.get("/rotas/{rota_id}/historico", response_model=list[RotaHistoricoOut])
def get_route_history(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    return db.scalars(
        select(RotaHistorico).where(RotaHistorico.rota_id == rota_id).order_by(RotaHistorico.criado_em)
    ).all()


@router.get("/relatorios/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    now = datetime.now()
    counts = dict(db.execute(
        select(Entrega.status, func.count()).group_by(Entrega.status)
    ).all())
    terminal = [StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA]
    delayed = db.scalar(select(func.count()).select_from(Entrega).where(
        Entrega.previsao_entrega < now,
        Entrega.status.not_in(terminal),
    )) or 0
    routes_in_execution = db.scalar(select(func.count()).select_from(Rota).where(Rota.status == StatusRota.EM_EXECUCAO)) or 0
    vehicles_available = db.scalar(select(func.count()).select_from(Veiculo).where(
        Veiculo.status == StatusVeiculo.DISPONIVEL,
        Veiculo.ativo.is_(True),
    )) or 0
    active_drivers = db.scalar(select(func.count()).select_from(Usuario).where(
        Usuario.perfil == Perfil.MOTORISTA,
        Usuario.ativo.is_(True),
    )) or 0
    total_deliveries_today = db.scalar(select(func.count()).select_from(Entrega).where(
        func.date(Entrega.criado_em) == now.date()
    )) or 0
    deliveries_by_status = [
        {"status": status, "quantidade": counts.get(status, 0)}
        for status in StatusEntrega
    ]
    deliveries_by_driver = [
        {"nome": nome, "quantidade": quantidade}
        for _, nome, quantidade in db.execute(
            select(Usuario.id, Usuario.nome, func.count(Entrega.id))
            .outerjoin(Entrega, Entrega.entregador_id == Usuario.id)
            .where(Usuario.perfil == Perfil.MOTORISTA, Usuario.ativo.is_(True))
            .group_by(Usuario.id, Usuario.nome)
            .order_by(func.count(Entrega.id).desc())
        ).all()
    ]
    deliveries_by_vehicle = [
        {"nome": placa, "quantidade": quantidade}
        for _, placa, quantidade in db.execute(
            select(Veiculo.id, Veiculo.placa, func.count(RotaEntrega.id))
            .join(Rota, Rota.veiculo_id == Veiculo.id)
            .join(RotaEntrega, RotaEntrega.rota_id == Rota.id)
            .group_by(Veiculo.id, Veiculo.placa)
            .order_by(func.count(RotaEntrega.id).desc())
        ).all()
    ]
    last_week = now.date() - timedelta(days=6)
    evolution_rows = {str(date_key): count for date_key, count in db.execute(
        select(func.date(Entrega.criado_em), func.count())
        .where(Entrega.criado_em >= last_week)
        .group_by(func.date(Entrega.criado_em))
        .order_by(func.date(Entrega.criado_em))
    ).all()}
    evolucao_diaria_entregas = [
        {"data": (last_week + timedelta(days=i)), "quantidade": evolution_rows.get(str(last_week + timedelta(days=i)), 0)}
        for i in range(7)
    ]
    latest_deliveries = db.scalars(
        select(Entrega)
        .where(Entrega.status == StatusEntrega.ENTREGUE)
        .order_by(Entrega.data_entrega.desc())
        .limit(5)
    ).all()
    if not latest_deliveries:
        latest_deliveries = db.scalars(
            select(Entrega)
            .order_by(Entrega.criado_em.desc())
            .limit(5)
        ).all()
    next_routes = db.scalars(
        select(Rota)
        .where(
            Rota.status.in_(
                [
                    StatusRota.PLANEJADA,
                    StatusRota.AGUARDANDO_MOTORISTA,
                    StatusRota.AGUARDANDO_VEICULO,
                    StatusRota.PRONTA,
                ]
            ),
            Rota.data_planejada.is_not(None),
        )
        .order_by(Rota.data_planejada.asc())
        .limit(5)
    ).all()
    return {
        "total_entregas": sum(counts.values()),
        "entregas_hoje": total_deliveries_today,
        "entregas_concluidas": counts.get(StatusEntrega.ENTREGUE, 0),
        "entregas_andamento": counts.get(StatusEntrega.EM_ROTA, 0),
        "entregas_atrasadas": delayed,
        "rotas_em_execucao": routes_in_execution,
        "veiculos_disponiveis": vehicles_available,
        "motoristas_ativos": active_drivers,
        "entregas_por_status": deliveries_by_status,
        "entregas_por_motorista": deliveries_by_driver,
        "entregas_por_veiculo": deliveries_by_vehicle,
        "evolucao_diaria_entregas": evolucao_diaria_entregas,
        "ultimas_entregas": latest_deliveries,
        "proximas_rotas": next_routes,
    }


@router.get("/relatorios/entregas")
def delivery_report(
    inicio: datetime | None = Query(None),
    fim: datetime | None = Query(None),
    status: StatusEntrega | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(staff),
):
    stmt = select(Entrega)
    if inicio:
        stmt = stmt.where(Entrega.criado_em >= inicio)
    if fim:
        stmt = stmt.where(Entrega.criado_em <= fim)
    if status:
        stmt = stmt.where(Entrega.status == status)
    rows = db.scalars(stmt.order_by(Entrega.criado_em.desc())).all()
    return {"total": len(rows), "entregas": rows}
