from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Entrega, Perfil, Rota, RotaEntrega, StatusEntrega, StatusRota, StatusVeiculo, Usuario, Veiculo
from ..schemas import DashboardOut
from ..security import current_user
from ..deps import admin

router = APIRouter(prefix="/relatorios")


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), _: Usuario = Depends(admin)):
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


@router.get("/entregas")
def delivery_report(
    inicio: datetime | None = None,
    fim: datetime | None = None,
    status: StatusEntrega | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(admin),
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
