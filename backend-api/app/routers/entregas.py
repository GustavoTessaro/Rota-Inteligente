from datetime import datetime

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    admin,
    apply_delivery_status,
    commit,
    delivery_roles,
    ensure_route_access_scope,
    get_or_404,
    staff,
    validate_driver,
)
from ..models import (
    ComprovanteEntrega,
    Endereco,
    Entrega,
    HistoricoEntrega,
    Ocorrencia,
    Pedido,
    Perfil,
    Rota,
    RotaEntrega,
    StatusEntrega,
    StatusRota,
    Usuario,
)
from ..schemas import (
    AtribuirIn,
    ComprovanteIn,
    ComprovanteOut,
    EntregaCreate,
    EntregaOut,
    EntregaStatusIn,
    OcorrenciaIn,
    OcorrenciaOut,
    StatusEntrega,
)
from ..security import current_user

router = APIRouter(prefix="/entregas")


@router.get("", response_model=list[EntregaOut])
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


@router.get("/minhas", response_model=list[EntregaOut])
def my_deliveries(db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    if user.perfil != Perfil.MOTORISTA:
        raise HTTPException(403, "Endpoint exclusivo para motoristas")
    return db.scalars(
        select(Entrega).where(Entrega.entregador_id == user.id).order_by(Entrega.previsao_entrega)
    ).all()


@router.post("", response_model=EntregaOut, status_code=201)
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
        entrega_id=delivery.id,
        status_anterior=None,
        status_novo=StatusEntrega.AGUARDANDO_COLETA.value,
        observacao="Entrega criada",
        alterado_por=user.id,
    ))
    commit(db)
    return delivery


@router.get("/{delivery_id}", response_model=EntregaOut)
def get_delivery(delivery_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    return delivery


@router.put("/{delivery_id}", response_model=EntregaOut)
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


@router.delete("/{delivery_id}", status_code=204)
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


@router.patch("/{delivery_id}/atribuir", response_model=EntregaOut)
def assign_delivery(
    delivery_id: int, data: AtribuirIn, db: Session = Depends(get_db), _: Usuario = Depends(staff)
):
    delivery = get_or_404(db, Entrega, delivery_id)
    validate_driver(db, data.entregador_id)
    delivery.entregador_id = data.entregador_id
    commit(db)
    return delivery


@router.patch("/{delivery_id}/status", response_model=EntregaOut)
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
    apply_delivery_status(db, delivery, data.status, data.observacao, user.id)
    commit(db)
    return delivery


@router.post("/{delivery_id}/concluir", response_model=ComprovanteOut)
def complete_delivery_with_receipt(
    delivery_id: int,
    data: ComprovanteIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(delivery_roles),
):
    delivery = get_or_404(db, Entrega, delivery_id)
    route = None
    if user.perfil == Perfil.MOTORISTA:
        route = db.scalar(
            select(Rota)
            .join(RotaEntrega, RotaEntrega.rota_id == Rota.id)
            .where(Rota.motorista_id == user.id)
            .where(Rota.status == StatusRota.EM_EXECUCAO)
            .where(RotaEntrega.entrega_id == delivery_id)
            .limit(1)
        )
        if route is None:
            raise HTTPException(403, "Entrega não pertence à rota ativa do motorista")
        ordered_entries = sorted(
            route.entregas,
            key=lambda entry: (
                entry.sequencia_otimizada
                if entry.sequencia_otimizada is not None
                else (entry.ordem_visita or 0),
                entry.id,
            ),
        )
        current_entry = next(
            (
                entry for entry in ordered_entries
                if entry.entrega and entry.entrega.status not in {
                    StatusEntrega.ENTREGUE,
                    StatusEntrega.NAO_ENTREGUE,
                    StatusEntrega.CANCELADA,
                }
            ),
            None,
        )
        if current_entry is None or current_entry.entrega_id != delivery_id:
            raise HTTPException(409, "A entrega informada não é a parada atual da rota")
    if delivery.status in {
        StatusEntrega.ENTREGUE,
        StatusEntrega.NAO_ENTREGUE,
        StatusEntrega.CANCELADA,
    }:
        raise HTTPException(409, "Entrega já processada e não pode ser concluída novamente")

    receipt = delivery.comprovante
    if receipt is None:
        receipt = ComprovanteEntrega(entrega_id=delivery_id, criado_por=user.id, **data.model_dump())
        db.add(receipt)
    else:
        receipt.nome_recebedor = data.nome_recebedor
        receipt.documento_recebedor = data.documento_recebedor
        receipt.observacao = data.observacao

    try:
        apply_delivery_status(db, delivery, StatusEntrega.ENTREGUE, data.observacao, user.id)
        db.commit()
        db.refresh(receipt)
        return receipt
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, "Não foi possível concluir a entrega") from exc


@router.get("/{delivery_id}/historico")
def delivery_history(
    delivery_id: int, db: Session = Depends(get_db), _: Usuario = Depends(current_user)
):
    get_or_404(db, Entrega, delivery_id)
    return db.scalars(
        select(HistoricoEntrega).where(HistoricoEntrega.entrega_id == delivery_id).order_by(HistoricoEntrega.criado_em)
    ).all()


@router.post("/{delivery_id}/ocorrencias", response_model=OcorrenciaOut, status_code=201)
def create_incident(
    delivery_id: int, data: OcorrenciaIn, db: Session = Depends(get_db), user: Usuario = Depends(delivery_roles)
):
    get_or_404(db, Entrega, delivery_id)
    incident = Ocorrencia(entrega_id=delivery_id, registrado_por=user.id, **data.model_dump())
    db.add(incident)
    commit(db)
    return incident


@router.get("/{delivery_id}/ocorrencias", response_model=list[OcorrenciaOut])
def list_incidents(delivery_id: int, db: Session = Depends(get_db), _: Usuario = Depends(current_user)):
    get_or_404(db, Entrega, delivery_id)
    return db.scalars(select(Ocorrencia).where(Ocorrencia.entrega_id == delivery_id)).all()


@router.put("/{delivery_id}/ocorrencias/{incident_id}", response_model=OcorrenciaOut)
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


@router.delete("/{delivery_id}/ocorrencias/{incident_id}", status_code=204)
def delete_incident(
    delivery_id: int, incident_id: int, db: Session = Depends(get_db), _: Usuario = Depends(delivery_roles)
):
    incident = get_or_404(db, Ocorrencia, incident_id)
    if incident.entrega_id != delivery_id:
        raise HTTPException(404, "Registro não encontrado")
    db.delete(incident)
    commit(db)


@router.post("/{delivery_id}/comprovante", response_model=ComprovanteOut, status_code=201)
def create_receipt(
    delivery_id: int, data: ComprovanteIn, db: Session = Depends(get_db), user: Usuario = Depends(delivery_roles)
):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    if delivery.status in {StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA}:
        raise HTTPException(409, "Não é possível criar comprovante para uma entrega já processada")
    if delivery.comprovante:
        raise HTTPException(409, "A entrega já possui comprovante")
    receipt = ComprovanteEntrega(entrega_id=delivery_id, criado_por=user.id, **data.model_dump())
    db.add(receipt)
    commit(db)
    return receipt


@router.get("/{delivery_id}/comprovante", response_model=ComprovanteOut)
def get_receipt(delivery_id: int, db: Session = Depends(get_db), _: Usuario = Depends(current_user)):
    receipt = db.scalar(select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id))
    if not receipt:
        raise HTTPException(404, "Comprovante não encontrado")
    return receipt


@router.put("/{delivery_id}/comprovante", response_model=ComprovanteOut)
def update_receipt(
    delivery_id: int, data: ComprovanteIn, db: Session = Depends(get_db), user: Usuario = Depends(delivery_roles)
):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    if user.perfil == Perfil.MOTORISTA and delivery.status == StatusEntrega.ENTREGUE:
        raise HTTPException(409, "Motorista não pode editar comprovante após a entrega")
    receipt = db.scalar(select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id))
    if not receipt:
        raise HTTPException(404, "Comprovante não encontrado")
    for key, value in data.model_dump().items():
        setattr(receipt, key, value)
    commit(db)
    return receipt


@router.delete("/{delivery_id}/comprovante", status_code=204)
def delete_receipt(delivery_id: int, db: Session = Depends(get_db), user: Usuario = Depends(delivery_roles)):
    delivery = get_or_404(db, Entrega, delivery_id)
    if user.perfil == Perfil.MOTORISTA and delivery.entregador_id != user.id:
        raise HTTPException(403, "Entrega não atribuída ao usuário")
    if user.perfil == Perfil.MOTORISTA and delivery.status == StatusEntrega.ENTREGUE:
        raise HTTPException(409, "Motorista não pode excluir comprovante após a entrega")
    receipt = db.scalar(select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id == delivery_id))
    if not receipt:
        raise HTTPException(404, "Comprovante não encontrado")
    db.delete(receipt)
    commit(db)
