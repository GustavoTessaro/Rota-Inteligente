from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import commit, get_or_404, staff
from ..models import PedidoItem, Produto, Usuario
from ..schemas import ProdutoCreate, ProdutoOut, StatusIn

router = APIRouter(prefix="/produtos")


@router.get("", response_model=list[ProdutoOut])
def list_products(
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Usuario = Depends(staff),
):
    stmt = select(Produto).order_by(Produto.nome)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("", response_model=ProdutoOut, status_code=201)
def create_product(data: ProdutoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = Produto(**data.model_dump())
    db.add(product)
    commit(db)
    return product


@router.put("/{product_id}", response_model=ProdutoOut)
def update_product(product_id: int, data: ProdutoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = get_or_404(db, Produto, product_id)
    for key, value in data.model_dump().items():
        setattr(product, key, value)
    commit(db)
    return product


@router.patch("/{product_id}/status", response_model=ProdutoOut)
def product_status(product_id: int, data: StatusIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = get_or_404(db, Produto, product_id)
    product.ativo = data.ativo
    commit(db)
    return product


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    product = get_or_404(db, Produto, product_id)
    used = db.scalar(select(func.count()).select_from(PedidoItem).where(PedidoItem.produto_id == product_id))
    if used:
        raise HTTPException(409, "Produto está em uso e não pode ser excluído")
    db.delete(product)
    commit(db)
