from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    commit,
    ensure_vehicle_access_scope,
    ensure_vehicle_payload_scope,
    staff,
    validate_driver,
    validate_organization,
    get_or_404,
)
from ..models import Perfil, Usuario, Veiculo
from ..schemas import VeiculoCreate, VeiculoOut, VeiculoUpdate
from ..security import current_user

router = APIRouter(prefix="/veiculos")


@router.get("", response_model=list[VeiculoOut])
def list_vehicles(
    busca: str | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
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


@router.post("", response_model=VeiculoOut, status_code=201)
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


@router.get("/{vehicle_id}", response_model=VeiculoOut)
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    vehicle = get_or_404(db, Veiculo, vehicle_id)
    ensure_vehicle_access_scope(user, vehicle)
    return vehicle


@router.put("/{vehicle_id}", response_model=VeiculoOut)
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


@router.delete("/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    vehicle = get_or_404(db, Veiculo, vehicle_id)
    ensure_vehicle_access_scope(user, vehicle)
    db.delete(vehicle)
    commit(db)
