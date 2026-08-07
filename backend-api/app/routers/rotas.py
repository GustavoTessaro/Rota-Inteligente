from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    commit,
    ensure_route_access_scope,
    ensure_route_payload_scope,
    get_or_404,
    staff,
    validate_driver,
    validate_organization,
    validate_route_delivery_entries,
)
from ..models import (
    Endereco,
    Perfil,
    Produto,
    Rota,
    RotaEntrega,
    RotaHistorico,
    RotaPosicao,
    TipoEventoRota,
    Usuario,
    Veiculo,
)
from ..schemas import (
    RotaCreate,
    RotaHistoricoOut,
    RotaOut,
    RotaPosicaoCreate,
    RotaPosicaoOut,
    RotaStatusIn,
    StatusRota,
)
from ..security import current_user
from ..tracking import manager

router = APIRouter(prefix="/rotas")


@router.get("", response_model=list[RotaOut])
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


@router.post("", response_model=RotaOut, status_code=201)
def create_route(data: RotaCreate, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
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
    rota = Rota(**data.model_dump(exclude={"entregas"}))
    rota.entregas = [RotaEntrega(**entry.model_dump()) for entry in data.entregas]
    db.add(rota)
    commit(db)
    return rota


@router.get("/{rota_id}", response_model=RotaOut)
def get_route(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    return rota


@router.put("/{rota_id}", response_model=RotaOut)
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


@router.delete("/{rota_id}", status_code=204)
def delete_route(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    db.delete(rota)
    commit(db)


@router.patch("/{rota_id}/status", response_model=RotaOut)
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
    if data.status == StatusRota.EM_EXECUCAO:
        if rota.veiculo_id is None:
            raise HTTPException(422, "Rota precisa de um veículo associado para iniciar")
        if rota.motorista_id is None:
            raise HTTPException(422, "Rota precisa de um motorista associado para iniciar")
        vehicle = get_or_404(db, Veiculo, rota.veiculo_id)
        driver = get_or_404(db, Usuario, rota.motorista_id)
        if vehicle.organizacao_id != rota.organizacao_id:
            raise HTTPException(422, "Veículo associado não pertence à organização da rota")
        if driver.perfil != Perfil.MOTORISTA or not driver.ativo:
            raise HTTPException(422, "Motorista associado deve estar ativo e com perfil MOTORISTA")
        if vehicle.motorista_id is not None and vehicle.motorista_id != driver.id:
            raise HTTPException(422, "Veículo associado deve estar compatível com o motorista da rota")
    if data.status in {StatusRota.FINALIZADA, StatusRota.CANCELADA} and rota.status not in {
        StatusRota.EM_EXECUCAO,
        StatusRota.PAUSADA,
        StatusRota.PRONTA,
    }:
        raise HTTPException(422, "Só é possível concluir ou cancelar uma rota em execução, pausada ou pronta")
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
    if data.status == StatusRota.EM_EXECUCAO and previous_status != StatusRota.EM_EXECUCAO:
        rota.data_inicio = rota.data_inicio or datetime.utcnow()
    if data.status in {StatusRota.FINALIZADA, StatusRota.CANCELADA} and rota.data_conclusao is None:
        rota.data_conclusao = datetime.utcnow()
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


@router.post("/{rota_id}/posicoes", response_model=RotaPosicaoOut, status_code=201)
async def create_route_position(
    rota_id: int,
    data: RotaPosicaoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)

    if data.veiculo_id is not None:
        veiculo = get_or_404(db, Veiculo, data.veiculo_id)
        if veiculo.organizacao_id != rota.organizacao_id:
            raise HTTPException(422, "Veículo deve pertencer à organização da rota")
        if rota.veiculo_id is not None and veiculo.id != rota.veiculo_id:
            raise HTTPException(422, "Veículo deve ser o mesmo associado à rota")
    else:
        if rota.veiculo_id is not None:
            data.veiculo_id = rota.veiculo_id

    if data.motorista_id is not None:
        motorista = get_or_404(db, Usuario, data.motorista_id)
        if motorista.perfil != Perfil.MOTORISTA or not motorista.ativo:
            raise HTTPException(422, "O motorista deve possuir perfil MOTORISTA e estar ativo")
        if rota.motorista_id is not None and motorista.id != rota.motorista_id:
            raise HTTPException(422, "Motorista deve ser o mesmo associado à rota")

    posicao = RotaPosicao(rota_id=rota_id, **data.model_dump(exclude_none=True))
    db.add(posicao)
    commit(db)
    db.refresh(posicao)
    payload = jsonable_encoder(RotaPosicaoOut.model_validate(posicao))
    await manager.broadcast({"type": "rota_posicao", "payload": payload})
    return posicao


@router.get("/{rota_id}/historico", response_model=list[RotaHistoricoOut])
def get_route_history(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    return db.scalars(
        select(RotaHistorico).where(RotaHistorico.rota_id == rota_id).order_by(RotaHistorico.criado_em)
    ).all()
