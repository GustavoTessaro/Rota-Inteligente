from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    admin,
    commit,
    ensure_manageable_user_payload,
    ensure_user_management_scope,
    get_or_404,
    staff,
)
from ..models import ComprovanteEntrega, Entrega, HistoricoEntrega, Ocorrencia, Pedido, Perfil, Usuario
from ..schemas import StatusIn, UsuarioCreate, UsuarioOut, UsuarioUpdate
from ..security import current_user, hash_password

router = APIRouter(prefix="/usuarios")


@router.get("", response_model=list[UsuarioOut])
def list_users(
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: Usuario = Depends(staff),
):
    stmt = select(Usuario).order_by(Usuario.nome)
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode listar usuários")
        stmt = stmt.where(Usuario.organizacao_id == user.organizacao_id)
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("", response_model=UsuarioOut, status_code=201)
def create_user(data: UsuarioCreate, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    ensure_manageable_user_payload(user, data)
    user_entity = Usuario(
        nome=data.nome,
        email=data.email.lower(),
        senha_hash=hash_password(data.senha),
        telefone=data.telefone,
        perfil=data.perfil,
        organizacao_id=data.organizacao_id,
    )
    db.add(user_entity)
    commit(db)
    return user_entity


@router.put("/{user_id}", response_model=UsuarioOut)
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


@router.patch("/{user_id}/status", response_model=UsuarioOut)
def user_status(user_id: int, data: StatusIn, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    existing_user = get_or_404(db, Usuario, user_id)
    ensure_user_management_scope(user, existing_user)
    existing_user.ativo = data.ativo
    commit(db)
    return existing_user


@router.delete("/{user_id}", status_code=204)
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
