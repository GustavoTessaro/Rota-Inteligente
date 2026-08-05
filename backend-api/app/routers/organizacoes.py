from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import admin, commit, get_or_404
from ..models import Endereco, Organizacao, Usuario
from ..schemas import OrganizacaoCreate, OrganizacaoOut

router = APIRouter(prefix="/organizacoes")


@router.get("", response_model=list[OrganizacaoOut])
def list_organizacoes(
    busca: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: Usuario = Depends(admin),
):
    stmt = select(Organizacao).order_by(Organizacao.nome)
    if busca:
        stmt = stmt.where(Organizacao.nome.ilike(f"%{busca}%"))
    if limit:
        stmt = stmt.offset(offset).limit(limit)
    return db.scalars(stmt).all()


@router.post("", response_model=OrganizacaoOut, status_code=201)
def create_organizacao(data: OrganizacaoCreate, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    if data.endereco_id is not None:
        get_or_404(db, Endereco, data.endereco_id)
    organizacao = Organizacao(**data.model_dump(exclude={"endereco_id"}))
    if data.endereco_id is not None:
        organizacao.endereco_id = data.endereco_id
    db.add(organizacao)
    commit(db)
    return organizacao


@router.put("/{org_id}", response_model=OrganizacaoOut)
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


@router.delete("/{org_id}", status_code=204)
def delete_organizacao(org_id: int, db: Session = Depends(get_db), _: Usuario = Depends(admin)):
    organizacao = get_or_404(db, Organizacao, org_id)
    linked_users = db.scalar(select(func.count()).select_from(Usuario).where(Usuario.organizacao_id == org_id))
    if linked_users:
        raise HTTPException(409, "Organização está em uso e não pode ser excluída")
    db.delete(organizacao)
    commit(db)
