from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import (
    Cliente,
    ComprovanteEntrega,
    Endereco,
    Entrega,
    HistoricoEntrega,
    Ocorrencia,
    Pedido,
    PedidoItem,
    Perfil,
    Produto,
    StatusEntrega,
    StatusPedido,
    Usuario,
)
from .schemas import (
    AtribuirIn,
    ClienteCreate,
    ClienteOut,
    ComprovanteIn,
    ComprovanteOut,
    EnderecoCreate,
    EnderecoOut,
    EntregaCreate,
    EntregaOut,
    EntregaStatusIn,
    LoginIn,
    OcorrenciaIn,
    OcorrenciaOut,
    PedidoCreate,
    PedidoItemIn,
    PedidoItemOut,
    PedidoOut,
    PedidoStatusIn,
    ProdutoCreate,
    ProdutoOut,
    StatusIn,
    TokenOut,
    UsuarioCreate,
    UsuarioOut,
    UsuarioUpdate,
)
from .security import create_token, current_user, hash_password, require_roles, verify_password

router = APIRouter(prefix="/api")
admin = require_roles(Perfil.ADMIN)
staff = require_roles(Perfil.ADMIN, Perfil.OPERADOR)
delivery_roles = require_roles(Perfil.ADMIN, Perfil.OPERADOR, Perfil.ENTREGADOR)


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
    if driver.perfil != Perfil.ENTREGADOR or not driver.ativo:
        raise HTTPException(422, "O entregador deve possuir perfil ENTREGADOR e estar ativo")
    return driver


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
    db: Session = Depends(get_db), _: Usuario = Depends(admin)
):
    stmt = select(Usuario).order_by(Usuario.nome)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("/usuarios", response_model=UsuarioOut, status_code=201)
def create_user(data: UsuarioCreate, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    user = Usuario(
        nome=data.nome, email=data.email.lower(), senha_hash=hash_password(data.senha),
        telefone=data.telefone, perfil=data.perfil,
    )
    db.add(user)
    commit(db)
    return user


@router.patch("/usuarios/{user_id}/status", response_model=UsuarioOut)
def user_status(user_id: int, data: StatusIn, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    user = get_or_404(db, Usuario, user_id)
    user.ativo = data.ativo
    commit(db)
    return user


@router.put("/usuarios/{user_id}", response_model=UsuarioOut)
def update_user(user_id: int, data: UsuarioUpdate, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    user = get_or_404(db, Usuario, user_id)
    user.nome = data.nome
    user.email = data.email.lower()
    if data.senha:
        user.senha_hash = hash_password(data.senha)
    user.telefone = data.telefone
    user.perfil = data.perfil
    commit(db)
    return user


@router.delete("/usuarios/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), current: Usuario = Depends(admin)):
    user = get_or_404(db, Usuario, user_id)
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
    if user.perfil != Perfil.ENTREGADOR:
        raise HTTPException(403, "Endpoint exclusivo para entregadores")
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
    if user.perfil == Perfil.ENTREGADOR and delivery.entregador_id != user.id:
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
    if user.perfil == Perfil.ENTREGADOR and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    if delivery.status == StatusEntrega.CANCELADA and user.perfil != Perfil.ADMIN:
        raise HTTPException(422, "Somente administrador pode reabrir entrega cancelada")
    if delivery.status == StatusEntrega.CANCELADA and not data.observacao:
        raise HTTPException(422, "Informe a justificativa para reabrir a entrega")
    if data.status == StatusEntrega.ENTREGUE and not delivery.comprovante:
        raise HTTPException(422, "Registre o comprovante antes de concluir a entrega")
    previous = delivery.status
    delivery.status = data.status
    if data.status == StatusEntrega.COLETADA and not delivery.data_coleta:
        delivery.data_coleta = datetime.now()
    if data.status == StatusEntrega.ENTREGUE:
        delivery.data_entrega = datetime.now()
    db.add(HistoricoEntrega(
        entrega_id=delivery.id, status_anterior=previous.value,
        status_novo=data.status.value, observacao=data.observacao, alterado_por=user.id,
    ))
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
    if user.perfil == Perfil.ENTREGADOR and delivery.entregador_id != user.id:
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
    if user.perfil == Perfil.ENTREGADOR and delivery.entregador_id != user.id:
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
    if user.perfil == Perfil.ENTREGADOR and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    receipt = db.scalar(select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id))
    if not receipt:
        raise HTTPException(404, "Comprovante não encontrado")
    db.delete(receipt)
    commit(db)


@router.get("/relatorios/dashboard")
def dashboard(db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    counts = dict(db.execute(
        select(Entrega.status, func.count()).group_by(Entrega.status)
    ).all())
    terminal = [StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA]
    delayed = db.scalar(select(func.count()).select_from(Entrega).where(
        Entrega.previsao_entrega < datetime.now(), Entrega.status.not_in(terminal)
    )) or 0
    order_counts = dict(db.execute(
        select(Pedido.status, func.count()).group_by(Pedido.status)
    ).all())
    return {
        "total_entregas": sum(counts.values()),
        "aguardando_coleta": counts.get(StatusEntrega.AGUARDANDO_COLETA, 0),
        "em_rota": counts.get(StatusEntrega.EM_ROTA, 0),
        "concluidas": counts.get(StatusEntrega.ENTREGUE, 0),
        "canceladas": counts.get(StatusEntrega.CANCELADA, 0),
        "atrasadas": delayed,
        "pedidos_abertos": order_counts.get(StatusPedido.ABERTO, 0),
        "pedidos_finalizados": order_counts.get(StatusPedido.FINALIZADO, 0),
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
