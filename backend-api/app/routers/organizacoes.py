from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import admin, commit, geocode_address, get_or_404, staff
from ..models import Endereco, Organizacao, Usuario
from ..schemas import EnderecoCreate, EnderecoOut, GeocodeResultIn, OrganizacaoCreate, OrganizacaoOut
from ..services.cep_service import get_cep_service

router = APIRouter(prefix="/organizacoes")


class CEPLookupResponse(BaseModel):
    success: bool
    logradouro: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    estado: str | None = None
    complemento: str | None = None
    error: str | None = None


class GeocodeAddressRequest(BaseModel):
    logradouro: str
    numero: str
    complemento: str | None = None
    bairro: str
    cidade: str
    estado: str
    cep: str


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
    payload = data.model_dump(exclude={"endereco_id"})
    payload["endereco"] = payload.get("endereco") or ""
    organizacao = Organizacao(**payload)
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
    payload["endereco"] = payload.get("endereco") or ""
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


@router.get("/{org_id}/enderecos", response_model=list[EnderecoOut])
def list_organization_addresses(org_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    get_or_404(db, Organizacao, org_id)
    return db.scalars(select(Endereco).where(Endereco.organizacao_id == org_id)).all()


@router.post("/{org_id}/enderecos", response_model=EnderecoOut, status_code=201)
def create_organization_address(
    org_id: int, data: EnderecoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    org = get_or_404(db, Organizacao, org_id)
    address = Endereco(organizacao_id=org_id, **data.model_dump(exclude={"cliente_id", "organizacao_id"}))
    result = geocode_address(db, address)
    if not result["success"]:
        raise HTTPException(422, f"Falha ao geocodificar: {result.get('error', 'Erro desconhecido')}")
    
    # If this address is marked as principal, unmark all others and update org reference
    if address.principal:
        db.query(Endereco).filter(
            Endereco.organizacao_id == org_id,
            Endereco.id != address.id
        ).update({Endereco.principal: False})
    
    db.add(address)
    commit(db)
    
    # Update organization's endereco_id if this is the principal address
    if address.principal:
        org.endereco_id = address.id
        commit(db)
    
    return address


@router.put("/{org_id}/enderecos/{address_id}", response_model=EnderecoOut)
def update_organization_address(
    org_id: int, address_id: int, data: EnderecoCreate, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    org = get_or_404(db, Organizacao, org_id)
    address = get_or_404(db, Endereco, address_id)
    if address.organizacao_id != org_id:
        raise HTTPException(404, "Registro não encontrado")
    
    payload = data.model_dump(exclude={"cliente_id", "organizacao_id"})
    for key, value in payload.items():
        setattr(address, key, value)

    result = geocode_address(db, address)
    if not result["success"]:
        raise HTTPException(422, f"Falha ao geocodificar: {result.get('error', 'Erro desconhecido')}")

    # If this address is marked as principal, unmark all others and update org reference
    if address.principal:
        db.query(Endereco).filter(
            Endereco.organizacao_id == org_id,
            Endereco.id != address.id
        ).update({Endereco.principal: False})
        org.endereco_id = address.id

    commit(db)
    return address


@router.delete("/{org_id}/enderecos/{address_id}", status_code=204)
def delete_organization_address(org_id: int, address_id: int, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    org = get_or_404(db, Organizacao, org_id)
    address = get_or_404(db, Endereco, address_id)
    if address.organizacao_id != org_id:
        raise HTTPException(404, "Registro não encontrado")

    # If deleting the principal address, mark the next one as principal
    if address.principal or address.id == org.endereco_id:
        remaining = db.query(Endereco).filter(
            Endereco.organizacao_id == org_id,
            Endereco.id != address.id
        ).first()
        if remaining:
            remaining.principal = True
            org.endereco_id = remaining.id
        else:
            org.endereco_id = None

    db.delete(address)
    commit(db)


@router.get("/{org_id}/enderecos/lookup-cep/{cep}", response_model=CEPLookupResponse)
def lookup_organization_cep(org_id: int, cep: str, db: Session = Depends(get_db), _: Usuario = Depends(staff)):
    get_or_404(db, Organizacao, org_id)
    service = get_cep_service()
    return service.lookup(cep)


@router.post("/{org_id}/enderecos/geocodificar", response_model=GeocodeResultIn)
def geocodify_organization_address(
    org_id: int, data: GeocodeAddressRequest, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    get_or_404(db, Organizacao, org_id)
    temp_endereco = Endereco(
        organizacao_id=org_id,
        logradouro=data.logradouro,
        numero=data.numero,
        complemento=data.complemento,
        bairro=data.bairro,
        cidade=data.cidade,
        estado=data.estado.upper(),
        cep=data.cep,
    )
    return geocode_address(db, temp_endereco)
