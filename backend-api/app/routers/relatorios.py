#routers/relatorios.py
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Entrega, Organizacao, Pedido, Perfil, Rota, RotaEntrega, StatusEntrega, StatusRota, StatusVeiculo, Usuario, Veiculo
from ..schemas import DashboardOut
from ..security import current_user
from ..deps import report_organization_scope

router = APIRouter(prefix="/relatorios")


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    organization_id = report_organization_scope(user)
    now = datetime.now()
    delivery_scope = [Entrega.pedido_id == Pedido.id]
    if organization_id is not None:
        delivery_scope.append(Pedido.organizacao_id == organization_id)
    counts = dict(db.execute(
        select(Entrega.status, func.count())
        .join(Pedido, Pedido.id == Entrega.pedido_id)
        .where(*delivery_scope)
        .group_by(Entrega.status)
    ).all())
    terminal = [StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA]
    delayed_query = select(func.count()).select_from(Entrega).join(Pedido, Pedido.id == Entrega.pedido_id).where(
        Entrega.previsao_entrega < now, Entrega.status.not_in(terminal), *delivery_scope
    )
    delayed = db.scalar(delayed_query) or 0
    route_filters = [Rota.status == StatusRota.EM_EXECUCAO]
    vehicle_filters = [Veiculo.status == StatusVeiculo.DISPONIVEL, Veiculo.ativo.is_(True)]
    driver_filters = [Usuario.perfil == Perfil.MOTORISTA, Usuario.ativo.is_(True)]
    if organization_id is not None:
        route_filters.append(Rota.organizacao_id == organization_id)
        vehicle_filters.append(Veiculo.organizacao_id == organization_id)
        driver_filters.append(Usuario.organizacao_id == organization_id)
    routes_in_execution = db.scalar(select(func.count()).select_from(Rota).where(*route_filters)) or 0
    vehicles_available = db.scalar(select(func.count()).select_from(Veiculo).where(*vehicle_filters)) or 0
    active_drivers = db.scalar(select(func.count()).select_from(Usuario).where(*driver_filters)) or 0
    total_deliveries_today = db.scalar(
        select(func.count()).select_from(Entrega).join(Pedido, Pedido.id == Entrega.pedido_id)
        .where(func.date(Entrega.criado_em) == now.date(), *delivery_scope)
    ) or 0
    deliveries_by_status = [
        {"status": status, "quantidade": counts.get(status, 0)}
        for status in StatusEntrega
    ]
    deliveries_by_driver = [
        {"nome": nome, "quantidade": quantidade}
        for _, nome, quantidade in db.execute(
            select(Usuario.id, Usuario.nome, func.count(Entrega.id))
            .join(Entrega, Entrega.entregador_id == Usuario.id)
            .join(Pedido, Pedido.id == Entrega.pedido_id)
            .where(*driver_filters, *([Pedido.organizacao_id == organization_id] if organization_id is not None else []))
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
            .where(*vehicle_filters, *([Rota.organizacao_id == organization_id] if organization_id is not None else []))
            .group_by(Veiculo.id, Veiculo.placa)
            .order_by(func.count(RotaEntrega.id).desc())
        ).all()
    ]
    last_week = now.date() - timedelta(days=6)
    evolution_rows = {str(date_key): count for date_key, count in db.execute(
        select(func.date(Entrega.criado_em), func.count())
        .join(Pedido, Pedido.id == Entrega.pedido_id)
        .where(Entrega.criado_em >= last_week, *delivery_scope)
        .group_by(func.date(Entrega.criado_em))
        .order_by(func.date(Entrega.criado_em))
    ).all()}
    evolucao_diaria_entregas = [
        {"data": (last_week + timedelta(days=i)), "quantidade": evolution_rows.get(str(last_week + timedelta(days=i)), 0)}
        for i in range(7)
    ]
    latest_deliveries = db.scalars(
        select(Entrega)
        .join(Pedido, Pedido.id == Entrega.pedido_id)
        .where(Entrega.status == StatusEntrega.ENTREGUE, *delivery_scope)
        .order_by(Entrega.data_entrega.desc())
        .limit(5)
    ).all()
    if not latest_deliveries:
        latest_deliveries = db.scalars(
            select(Entrega)
            .join(Pedido, Pedido.id == Entrega.pedido_id)
            .where(*delivery_scope)
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
            *([Rota.organizacao_id == organization_id] if organization_id is not None else []),
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
    user: Usuario = Depends(current_user),
):
    organization_id = report_organization_scope(user)
    stmt = select(Entrega).join(Pedido, Pedido.id == Entrega.pedido_id)
    if organization_id is not None:
        stmt = stmt.where(Pedido.organizacao_id == organization_id)
    if inicio:
        stmt = stmt.where(Entrega.criado_em >= inicio)
    if fim:
        stmt = stmt.where(Entrega.criado_em <= fim)
    if status:
        stmt = stmt.where(Entrega.status == status)
    rows = db.scalars(stmt.order_by(Entrega.criado_em.desc())).all()

    terminal_statuses = {StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA}
    now = datetime.now()
    atrasadas = sum(
        1
        for delivery in rows
        if delivery.previsao_entrega is not None
        and delivery.previsao_entrega < now
        and delivery.status not in terminal_statuses
    )
    em_dia = sum(
        1
        for delivery in rows
        if delivery.previsao_entrega is not None
        and delivery.previsao_entrega >= now
        and delivery.status not in terminal_statuses
    )
    entregas_por_status = [
        {"status": current_status.value, "quantidade": sum(1 for delivery in rows if delivery.status == current_status)}
        for current_status in StatusEntrega
    ]
    entregas_por_motorista = []
    driver_totals = {}
    for delivery in rows:
        if delivery.entregador_id is None:
            continue
        driver_totals[delivery.entregador_id] = driver_totals.get(delivery.entregador_id, 0) + 1
    if driver_totals:
        drivers = db.execute(
            select(Usuario.id, Usuario.nome).where(Usuario.id.in_(list(driver_totals.keys())))
        ).all()
        driver_names = {driver_id: nome for driver_id, nome in drivers}
        entregas_por_motorista = [
            {
                "motorista_id": driver_id,
                "motorista": driver_names.get(driver_id, f"Motorista #{driver_id}"),
                "quantidade": quantity,
            }
            for driver_id, quantity in sorted(driver_totals.items(), key=lambda item: (-item[1], item[0]))
        ]

    entregas_por_organizacao = []
    organization_totals = {}
    organization_statuses = {}
    for delivery in rows:
        if delivery.pedido is None or delivery.pedido.organizacao_id is None:
            continue
        organization_id = delivery.pedido.organizacao_id
        organization_totals[organization_id] = organization_totals.get(organization_id, set())
        organization_totals[organization_id].add(delivery.pedido_id)
        organization_statuses.setdefault(organization_id, {})
        organization_statuses[organization_id][delivery.status] = organization_statuses[organization_id].get(delivery.status, 0) + 1
    if organization_totals:
        organization_names = {
            organization_id: name
            for organization_id, name in db.execute(
                select(Organizacao.id, Organizacao.nome).where(Organizacao.id.in_(list(organization_totals.keys())))
            ).all()
        }
        entregas_por_organizacao = [
            {
                "organizacao_id": organization_id,
                "organizacao": organization_names.get(organization_id, f"Organização #{organization_id}"),
                "quantidade_total_pedidos": len(pedido_ids),
                "distribuicao_por_status": [
                    {"status": status.value, "quantidade": quantity}
                    for status, quantity in sorted(
                        organization_statuses.get(organization_id, {}).items(),
                        key=lambda item: (-item[1], item[0].value if hasattr(item[0], "value") else str(item[0]))
                    )
                ],
            }
            for organization_id, pedido_ids in sorted(
                organization_totals.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )
        ]

    intervalos_eligiveis = [
        (delivery.data_entrega - delivery.data_coleta).total_seconds() / 60
        for delivery in rows
        if delivery.data_coleta is not None
        and delivery.data_entrega is not None
        and delivery.data_entrega >= delivery.data_coleta
    ]
    tempo_medio_minutos = (
        sum(intervalos_eligiveis) / len(intervalos_eligiveis)
        if intervalos_eligiveis
        else 0
    )

    return {
        "total": len(rows),
        "entregas": rows,
        "entregas_atrasadas": atrasadas,
        "entregas_em_dia": em_dia,
        "entregas_por_status": entregas_por_status,
        "entregas_por_motorista": entregas_por_motorista,
        "entregas_por_organizacao": entregas_por_organizacao,
        "tempo_medio_minutos": tempo_medio_minutos,
    }
