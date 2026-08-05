from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import commit, get_or_404, order_has_delivery, recalculate_order_total, staff
from ..models import Cliente, Pedido, PedidoItem, Produto, StatusPedido, Usuario
from ..schemas import PedidoCreate, PedidoItemIn, PedidoItemOut, PedidoOut, PedidoStatusIn

router = APIRouter(prefix="/pedidos")


@router.get("", response_model=list[PedidoOut])
def list_orders(
    status: str | None = None,
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


@router.post("", response_model=PedidoOut, status_code=201)
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


@router.put("/{order_id}", response_model=PedidoOut)
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


@router.delete("/{order_id}", status_code=204)
def delete_order(order_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    if order_has_delivery(db, order_id):
        raise HTTPException(409, "Pedido está em uso e não pode ser excluído")
    db.delete(order)
    commit(db)


@router.get("/{order_id}/itens", response_model=list[PedidoItemOut])
def list_order_items(order_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    get_or_404(db, Pedido, order_id)
    return db.scalars(select(PedidoItem).where(PedidoItem.pedido_id == order_id)).all()


@router.post("/{order_id}/itens", response_model=PedidoItemOut, status_code=201)
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


@router.put("/{order_id}/itens/{item_id}", response_model=PedidoItemOut)
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


@router.delete("/{order_id}/itens/{item_id}", status_code=204)
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


@router.patch("/{order_id}/cancelar", response_model=PedidoOut)
def cancel_order(order_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    order.status = StatusPedido.CANCELADO
    commit(db)
    return order


@router.patch("/{order_id}/status", response_model=PedidoOut)
def order_status(order_id: int, data: PedidoStatusIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    order = get_or_404(db, Pedido, order_id)
    order.status = data.status
    commit(db)
    return order
