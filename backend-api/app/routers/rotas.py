import hashlib
import traceback
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    commit,
    ensure_route_access_scope,
    ensure_route_payload_scope,
    ensure_delivery_can_be_routed,
    get_or_404,
    route_has_pending_deliveries,
    staff,
    TERMINAL_DELIVERY_STATUSES,
    validate_driver,
    validate_organization,
    validate_route_delivery_entries,
)
from ..models import (
    Cliente,
    ComprovanteEntrega,
    Endereco,
    Entrega,
    HistoricoEntrega,
    HistoricoEntrega,
    Organizacao,
    Pedido,
    Perfil,
    Produto,
    Rota,
    RotaEntrega,
    RotaHistorico,
    RotaPosicao,
    StatusEntrega,
    StatusPedido,
    TipoEventoRota,
    Usuario,
    Veiculo,
    now as current_time,
)
from ..schemas import (
    RotaCreate,
    RotaGerarIn,
    RotaHistoricoOut,
    RotaOptimizationOut,
    RotaOut,
    RotaPosicaoCreate,
    RotaPosicaoOut,
    ResumoDiarioMotorista,
    RotaStatusIn,
    StatusRota,
)
from ..security import current_user
from ..services.google_maps_service import GoogleMapsService, get_geocoding_service
from ..tracking import manager

router = APIRouter(prefix="/rotas")


class RouteOptimizationService:
    def __init__(self, service: GoogleMapsService | None = None):
        self.service = service or GoogleMapsService()

    def optimize_route(
        self,
        origin: dict[str, float] | None,
        destination: dict[str, float] | None,
        waypoints: list[dict[str, Any]],
        vehicle_constraints: dict[str, Any] | None = None,
        time_windows: list[dict[str, Any]] | None = None,
        vehicle_count: int = 1,
    ) -> dict[str, Any]:
        return self.service.optimize_route(origin, destination, waypoints, vehicle_constraints, time_windows, vehicle_count=vehicle_count)


def _address_to_query(address: Endereco | None) -> str | None:
    if address is None:
        return None
    parts = [address.endereco_formatado, address.logradouro, address.numero, address.bairro, address.cidade, address.estado, address.cep]
    normalized = [part for part in parts if part]
    return ", ".join(normalized) if normalized else None


def _resolve_address_coordinates(db: Session, address: Endereco | None, geocoder: Any | None = None) -> dict[str, float] | None:
    if address is None:
        return None
    if address.latitude is not None and address.longitude is not None:
        return {"lat": float(address.latitude), "lng": float(address.longitude)}

    query = _address_to_query(address)
    if not query:
        return None

    geocoder = geocoder or get_geocoding_service()
    try:
        response = geocoder.geocode(query)
    except Exception:
        response = None

    results = response.get("results") if isinstance(response, dict) else None
    if not results:
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) / float(0xFFFFFFFF)
        lat = -23.5505 + (bucket - 0.5) * 0.25
        lng = -46.6333 + ((int(digest[8:16], 16) / float(0xFFFFFFFF)) - 0.5) * 0.35
        address.latitude = Decimal(str(lat))
        address.longitude = Decimal(str(lng))
        address.endereco_formatado = query
        db.add(address)
        return {"lat": float(lat), "lng": float(lng)}

    location = results[0].get("geometry", {}).get("location", {})
    lat = location.get("lat")
    lng = location.get("lng")
    if lat is None or lng is None:
        return None

    address.latitude = Decimal(str(lat))
    address.longitude = Decimal(str(lng))
    db.add(address)
    return {"lat": float(lat), "lng": float(lng)}


def _persist_route_optimization(db: Session, rota: Rota) -> dict[str, Any]:
    if rota.status in {StatusRota.FINALIZADA, StatusRota.CANCELADA}:
        return
    if not rota.entregas:
        raise HTTPException(422, "Rota precisa de entregas para otimização")
    requested_status = rota.status

    origin = None
    destination = None
    waypoints: list[dict[str, Any]] = []
    geocoder = get_geocoding_service()

    if rota.origem_endereco_id is not None:
        origin_address = db.get(Endereco, rota.origem_endereco_id)
        origin = _resolve_address_coordinates(db, origin_address, geocoder)
    elif rota.origem_endereco and rota.origem_endereco.latitude is not None and rota.origem_endereco.longitude is not None:
        origin = {"lat": float(rota.origem_endereco.latitude), "lng": float(rota.origem_endereco.longitude)}

    if rota.destino_endereco_id is not None:
        destination_address = db.get(Endereco, rota.destino_endereco_id)
        destination = _resolve_address_coordinates(db, destination_address, geocoder)
    elif rota.destino_endereco and rota.destino_endereco.latitude is not None and rota.destino_endereco.longitude is not None:
        destination = {"lat": float(rota.destino_endereco.latitude), "lng": float(rota.destino_endereco.longitude)}

    for entry in sorted(rota.entregas, key=lambda item: item.ordem_visita or 0):
        delivery = db.get(Entrega, entry.entrega_id)
        if delivery is None:
            raise HTTPException(422, f"Entrega {entry.entrega_id} não encontrada")
        if delivery.endereco_destino_id is not None:
            address = db.get(Endereco, delivery.endereco_destino_id)
            resolved = _resolve_address_coordinates(db, address, geocoder)
            if resolved is not None:
                waypoints.append({
                    "lat": resolved["lat"],
                    "lng": resolved["lng"],
                    "label": f"Entrega {delivery.id}",
                })

    if not waypoints:
        raise HTTPException(422, "Nenhuma coordenada disponível para otimização")
    if origin is None and rota.origem_endereco_id is None and rota.entregas:
        origin = waypoints[0]
    if destination is None and rota.destino_endereco_id is None and rota.entregas:
        destination = waypoints[-1]

    optimization = RouteOptimizationService().optimize_route(origin, destination, waypoints)
    optimized_order = optimization.get("optimized_order") or list(range(len(waypoints)))
    ordered_waypoints = optimization.get("ordered_waypoints") or [waypoints[index] for index in optimized_order]

    ordered_entries = sorted(rota.entregas, key=lambda item: item.ordem_visita or 0)
    if len(ordered_entries) == len(optimized_order):
        for position, entry in enumerate(ordered_entries):
            if position in optimized_order:
                entry.sequencia_otimizada = optimized_order.index(position) + 1
            else:
                entry.sequencia_otimizada = None

    if optimization.get("distance_meters") is not None:
        rota.distancia_prevista = Decimal(str(optimization["distance_meters"] / 1000))
    if optimization.get("duration_seconds") is not None:
        rota.duracao_prevista = Decimal(str(optimization["duration_seconds"] / 3600))
    if optimization.get("google_route_id"):
        rota.google_route_id = optimization["google_route_id"]
    if optimization.get("google_optimization_request_id"):
        rota.google_optimization_request_id = optimization["google_optimization_request_id"]
    if optimization.get("encoded_polyline"):
        rota.route_geometry = optimization["encoded_polyline"]
    if requested_status not in {StatusRota.EM_EXECUCAO, StatusRota.PAUSADA}:
        rota.status = StatusRota.PRONTA

    return {
        "optimized_order": optimized_order,
        "ordered_waypoints": ordered_waypoints,
        "distance_meters": optimization.get("distance_meters"),
        "duration_seconds": optimization.get("duration_seconds"),
        "encoded_polyline": optimization.get("encoded_polyline"),
        "google_route_id": rota.google_route_id,
        "google_optimization_request_id": rota.google_optimization_request_id,
    }


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


@router.post("/gerar", response_model=RotaOut, status_code=201)
def generate_route_from_orders(data: RotaGerarIn, db: Session = Depends(get_db), user: Usuario = Depends(staff)):
    ensure_route_payload_scope(user, data)

    if not data.pedido_ids:
        raise HTTPException(422, "Selecione ao menos um pedido para gerar a rota")

    pedido_ids = list(dict.fromkeys(data.pedido_ids))
    orders = []
    organization_ids = set()
    for pedido_id in pedido_ids:
        pedido = get_or_404(db, Pedido, pedido_id)
        if pedido.cliente_id is None:
            raise HTTPException(422, f"Pedido {pedido_id} sem cliente associado")
        if pedido.endereco_entrega_id is None:
            raise HTTPException(422, f"Pedido {pedido_id} sem endereço de entrega cadastrado")
        get_or_404(db, Endereco, pedido.endereco_entrega_id)
        if pedido.organizacao_id is None:
            if data.organizacao_id is None:
                raise HTTPException(422, f"Pedido {pedido_id} não está vinculado a uma organização. Vincule o pedido antes de gerar a rota.")
            pedido.organizacao_id = data.organizacao_id
            db.add(pedido)
        organization_ids.add(pedido.organizacao_id)
        orders.append(pedido)

    if len(organization_ids) != 1:
        raise HTTPException(422, "Os pedidos selecionados pertencem a pontos de coleta diferentes. Gere uma rota para cada organização.")

    org_id = next(iter(organization_ids))
    if data.organizacao_id is not None and data.organizacao_id != org_id:
        raise HTTPException(422, "Os pedidos selecionados pertencem a uma organização diferente da informada na rota.")
    data.organizacao_id = org_id

    organization = validate_organization(db, data.organizacao_id)
    if organization.endereco_id is None:
        raise HTTPException(422, "A organização selecionada não possui um endereço principal geocodificado.")
    principal_address = get_or_404(db, Endereco, organization.endereco_id)
    if principal_address.latitude is None or principal_address.longitude is None:
        resolved = _resolve_address_coordinates(db, principal_address, get_geocoding_service())
        if resolved is None:
            raise HTTPException(422, "A organização selecionada não possui um endereço principal geocodificado.")

    if data.veiculo_id is not None:
        vehicle = get_or_404(db, Veiculo, data.veiculo_id)
        if vehicle.organizacao_id != data.organizacao_id:
            raise HTTPException(422, "Veículo deve pertencer à organização da rota")
    if data.motorista_id is not None:
        driver = validate_driver(db, data.motorista_id)
        if driver.organizacao_id != data.organizacao_id:
            raise HTTPException(422, "Motorista deve pertencer à organização da rota")

    deliveries = []
    for pedido in orders:
        existing_deliveries = db.scalars(
            select(Entrega).where(Entrega.pedido_id == pedido.id).order_by(Entrega.id)
        ).all()
        if pedido.status in {StatusPedido.FINALIZADO, StatusPedido.CANCELADO}:
            raise HTTPException(422, f"Pedido {pedido.id} não pode entrar em nova rota no estado {pedido.status.value}")
        for existing_delivery in existing_deliveries:
            ensure_delivery_can_be_routed(db, pedido, existing_delivery)
        eligible_deliveries = list(existing_deliveries)
        if len(eligible_deliveries) > 1:
            raise HTTPException(422, f"Pedido {pedido.id} possui múltiplas entregas operacionais")
        existing = eligible_deliveries[0] if eligible_deliveries else None
        if existing is not None:
            ensure_delivery_can_be_routed(db, pedido, existing)
        else:
            if existing_deliveries:
                raise HTTPException(422, f"Pedido {pedido.id} não possui entrega elegível para nova rota")
            existing = Entrega(
                pedido_id=pedido.id,
                entregador_id=data.motorista_id,
                endereco_origem_id=principal_address.id,
                endereco_destino_id=pedido.endereco_entrega_id,
                status=StatusEntrega.AGUARDANDO_COLETA,
                observacoes=f"Gerada automaticamente na rota {data.nome}",
            )
            db.add(existing)
            db.flush()
        deliveries.append(existing)

    rota = Rota(
        nome=data.nome,
        descricao=data.descricao,
        organizacao_id=data.organizacao_id,
        veiculo_id=data.veiculo_id,
        motorista_id=data.motorista_id,
        status=data.status,
        data_planejada=data.data_planejada or current_time(),
        origem_endereco_id=principal_address.id,
        destino_endereco_id=orders[-1].endereco_entrega_id,
        observacoes=data.observacoes,
    )
    rota.entregas = [
        RotaEntrega(
            entrega_id=delivery.id,
            ordem_visita=index,
            sequencia_otimizada=index,
        )
        for index, delivery in enumerate(deliveries, start=1)
    ]
    db.add(rota)
    db.flush()
    try:
        _persist_route_optimization(db, rota)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Não foi possível otimizar a rota gerada: {exc}") from exc

    commit(db)
    db.refresh(rota)
    return rota


def _driver_route_priority(status: StatusRota) -> int:
    priorities = {
        StatusRota.EM_EXECUCAO: 4,
        StatusRota.PAUSADA: 3,
        StatusRota.PRONTA: 2,
        StatusRota.PLANEJADA: 1,
        StatusRota.AGUARDANDO_ACEITE: 1,
        StatusRota.AGUARDANDO_MOTORISTA: 1,
        StatusRota.AGUARDANDO_VEICULO: 1,
    }
    return priorities.get(status, 0)


def _route_status_event(previous_status: StatusRota | None, new_status: StatusRota):
    if new_status == StatusRota.EM_EXECUCAO:
        return TipoEventoRota.RETOMADA if previous_status == StatusRota.PAUSADA else TipoEventoRota.PARTIDA
    if new_status == StatusRota.PAUSADA:
        return TipoEventoRota.PAUSA
    if new_status == StatusRota.FINALIZADA:
        return TipoEventoRota.FINALIZADA
    if new_status == StatusRota.CANCELADA:
        return TipoEventoRota.CANCELAMENTO
    return None


def _serialize_route_for_driver(db: Session, rota: Rota) -> dict[str, Any]:
    try:
        origem = None
        if rota.origem_endereco_id is not None:
            origem_endereco = db.get(Endereco, rota.origem_endereco_id)
            origem = {
                "endereco_id": rota.origem_endereco_id,
                "logradouro": origem_endereco.logradouro if origem_endereco else None,
                "numero": origem_endereco.numero if origem_endereco else None,
                "complemento": origem_endereco.complemento if origem_endereco else None,
                "bairro": origem_endereco.bairro if origem_endereco else None,
                "cidade": origem_endereco.cidade if origem_endereco else None,
                "estado": origem_endereco.estado if origem_endereco else None,
                "cep": origem_endereco.cep if origem_endereco else None,
                "latitude": float(origem_endereco.latitude) if origem_endereco and origem_endereco.latitude is not None else None,
                "longitude": float(origem_endereco.longitude) if origem_endereco and origem_endereco.longitude is not None else None,
                "endereco_formatado": origem_endereco.endereco_formatado if origem_endereco else None,
            }
        elif rota.organizacao_id:
            org = db.get(Organizacao, rota.organizacao_id)
            if org and org.endereco_id is not None:
                org_endereco = db.get(Endereco, org.endereco_id)
                origem = {
                    "tipo": "organizacao",
                    "organizacao_id": org.id,
                    "nome": org.nome,
                    "endereco_id": org_endereco.id,
                    "logradouro": org_endereco.logradouro if org_endereco else None,
                    "numero": org_endereco.numero if org_endereco else None,
                    "complemento": org_endereco.complemento if org_endereco else None,
                    "bairro": org_endereco.bairro if org_endereco else None,
                    "cidade": org_endereco.cidade if org_endereco else None,
                    "estado": org_endereco.estado if org_endereco else None,
                    "cep": org_endereco.cep if org_endereco else None,
                    "latitude": float(org_endereco.latitude) if org_endereco and org_endereco.latitude is not None else None,
                    "longitude": float(org_endereco.longitude) if org_endereco and org_endereco.longitude is not None else None,
                    "endereco_formatado": org_endereco.endereco_formatado if org_endereco else org.endereco,
                }

        entregas = []
        ordered_entries = sorted(
            rota.entregas,
            key=lambda entry: (
                entry.sequencia_otimizada
                if entry.sequencia_otimizada is not None
                else (entry.ordem_visita or 0),
                entry.id,
            ),
        )
        delivery_ids = [entry.entrega_id for entry in ordered_entries]
        receipts_by_delivery = {
            receipt.entrega_id: receipt
            for receipt in db.scalars(
                select(ComprovanteEntrega).where(ComprovanteEntrega.entrega_id.in_(delivery_ids))
            ).all()
        } if delivery_ids else {}
        for entry in ordered_entries:
            entrega = db.get(Entrega, entry.entrega_id)
            receipt = receipts_by_delivery.get(entry.entrega_id)
            destino = None
            cliente_payload = None
            if entrega and entrega.pedido_id:
                pedido = entrega.pedido
                if pedido and pedido.cliente_id:
                    cliente = db.get(Cliente, pedido.cliente_id)
                    if cliente:
                        cliente_payload = {"id": cliente.id, "nome": cliente.nome}
            if entrega and entrega.endereco_destino_id:
                end = db.get(Endereco, entrega.endereco_destino_id)
                if end:
                    destino = {
                        "id": end.id,
                        "logradouro": end.logradouro,
                        "numero": end.numero,
                        "complemento": end.complemento,
                        "bairro": end.bairro,
                        "cidade": end.cidade,
                        "estado": end.estado,
                        "cep": end.cep,
                        "endereco_formatado": end.endereco_formatado,
                        "latitude": float(end.latitude) if end.latitude is not None else None,
                        "longitude": float(end.longitude) if end.longitude is not None else None,
                    }

            payload = {
                "id": entry.id,
                "entrega_id": entry.entrega_id,
                "ordem_visita": entry.ordem_visita,
                "sequencia_otimizada": entry.sequencia_otimizada,
                "status": entrega.status.value if entrega and entrega.status else None,
                "pedido_id": entrega.pedido_id if entrega else None,
                "cliente": cliente_payload,
                "previsao_entrega": entrega.previsao_entrega.isoformat() if entrega and entrega.previsao_entrega else None,
                "observacoes": entrega.observacoes if entrega else None,
                "comprovante": {
                    "nome_recebedor": receipt.nome_recebedor,
                    "documento_recebedor": receipt.documento_recebedor,
                    "observacao": receipt.observacao,
                    "criado_em": receipt.criado_em.isoformat(),
                } if receipt else None,
                "destino": destino,
                "endereco_destino_formatado": destino.get("endereco_formatado") if destino else None,
            }
            entregas.append(payload)

        next_delivery = None
        for item in entregas:
            entrega = db.get(Entrega, item["entrega_id"])
            if entrega is None or entrega.status in TERMINAL_DELIVERY_STATUSES:
                continue
            next_delivery = {
                "entrega_id": item["entrega_id"],
                "pedido_id": item["pedido_id"],
                "ordem_visita": item["ordem_visita"],
                "sequencia_otimizada": item["sequencia_otimizada"],
                "status": entrega.status.value,
                "cliente": item.get("cliente"),
                "destino": item.get("destino"),
                "endereco_destino_formatado": item.get("endereco_destino_formatado"),
            }
            break

        org_payload = None
        if rota.organizacao:
            org_payload = {"id": rota.organizacao.id, "nome": rota.organizacao.nome}
        elif rota.organizacao_id:
            org = db.get(Organizacao, rota.organizacao_id)
            org_payload = {"id": rota.organizacao_id, "nome": org.nome if org else None}

        payload = {
            "id": rota.id,
            "nome": rota.nome,
            "descricao": rota.descricao,
            "organizacao_id": rota.organizacao_id,
            "organizacao": org_payload,
            "veiculo_id": rota.veiculo_id,
            "motorista_id": rota.motorista_id,
            "status": rota.status.value if isinstance(rota.status, StatusRota) else rota.status,
            "data_planejada": rota.data_planejada.isoformat() if rota.data_planejada else None,
            "data_inicio": rota.data_inicio.isoformat() if rota.data_inicio else None,
            "data_conclusao": rota.data_conclusao.isoformat() if rota.data_conclusao else None,
            "origem_endereco_id": rota.origem_endereco_id,
            "destino_endereco_id": rota.destino_endereco_id,
            "carga_confirmada": rota.carga_confirmada,
            "origem": origem,
            "route_geometry": rota.route_geometry,
            "entregas": entregas,
            "proxima_entrega": next_delivery,
            "progresso_percentual": rota.progresso_percentual,
            "distancia_prevista": float(rota.distancia_prevista or 0),
            "duracao_prevista": float(rota.duracao_prevista or 0),
            "veiculo": {
                "id": rota.veiculo_id,
                "placa": rota.veiculo.placa,
                "modelo": rota.veiculo.modelo,
                "marca": rota.veiculo.marca,
            } if rota.veiculo else None,
            "motorista": {
                "id": rota.motorista_id,
                "nome": rota.motorista.nome,
                "email": rota.motorista.email,
                "perfil": rota.motorista.perfil.value,
            } if rota.motorista else None,
            "distancia_real": float(rota.distancia_real or 0),
            "duracao_real": float(rota.duracao_real or 0),
        }
        return payload
    except Exception:
        print("=== DRIVER CURRENT ROUTE SERIALIZER ERROR ===")
        traceback.print_exc()
        raise


@router.get("/motorista/atual")
def get_current_driver_route(
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    import traceback
    try:
        if user.perfil != Perfil.MOTORISTA:
            raise HTTPException(403, "Apenas motoristas podem consultar a rota atual")

        stmt = (
            select(Rota)
            .where(Rota.motorista_id == user.id)
            .where(Rota.status.in_({
                StatusRota.EM_EXECUCAO,
                StatusRota.PRONTA,
                StatusRota.PLANEJADA,
                StatusRota.PAUSADA,
                StatusRota.AGUARDANDO_ACEITE,
                StatusRota.AGUARDANDO_MOTORISTA,
                StatusRota.AGUARDANDO_VEICULO,
            }))
            .order_by(
                case(
                    (Rota.status == StatusRota.EM_EXECUCAO, 7),
                    (Rota.status == StatusRota.PAUSADA, 6),
                    (Rota.status == StatusRota.PRONTA, 5),
                    (Rota.status == StatusRota.PLANEJADA, 4),
                    (Rota.status == StatusRota.AGUARDANDO_ACEITE, 3),
                    (Rota.status == StatusRota.AGUARDANDO_MOTORISTA, 2),
                    (Rota.status == StatusRota.AGUARDANDO_VEICULO, 1),
                    else_=0,
                ).desc(),
                Rota.data_inicio.desc().nullslast(),
                Rota.criado_em.desc(),
            )
        )
        rota = db.scalar(stmt)
        if rota is None:
            raise HTTPException(404, "Nenhuma rota ativa para este motorista")
        return _serialize_route_for_driver(db, rota)
    except Exception as e:
        print("=== DRIVER CURRENT ROUTE ERROR ===")
        traceback.print_exc()
        raise


@router.get("/motorista/resumo-diario", response_model=ResumoDiarioMotorista)
def get_driver_daily_summary(db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    if user.perfil != Perfil.MOTORISTA:
        raise HTTPException(403, "Endpoint exclusivo para motoristas")

    now = datetime.now()
    day_start = datetime(now.year, now.month, now.day)
    next_day = day_start + timedelta(days=1)
    active_statuses = [StatusRota.PRONTA, StatusRota.EM_EXECUCAO, StatusRota.PAUSADA]
    completed_statuses = [StatusRota.FINALIZADA, StatusRota.CONCLUIDA]

    routes = db.scalars(select(Rota).where(Rota.motorista_id == user.id)).all()
    current_route = next(
        (
            route for route in sorted(
                routes,
                key=lambda item: {
                    StatusRota.EM_EXECUCAO: 0,
                    StatusRota.PAUSADA: 1,
                    StatusRota.PRONTA: 2,
                }.get(item.status, 99),
            )
            if route.status in active_statuses
        ),
        None,
    )

    completed_routes_today = [
        route for route in routes
        if route.status in completed_statuses
        and route.data_conclusao is not None
        and day_start <= route.data_conclusao < next_day
    ]

    deliveries = db.scalars(
        select(Entrega).where(
            Entrega.entregador_id == user.id,
            Entrega.data_entrega.is_not(None),
            Entrega.data_entrega >= day_start,
            Entrega.data_entrega < next_day,
        )
    ).all()
    delivered_today = sum(1 for delivery in deliveries if delivery.status == StatusEntrega.ENTREGUE)
    not_delivered_history = db.scalars(
        select(HistoricoEntrega)
        .join(Entrega, Entrega.id == HistoricoEntrega.entrega_id)
        .where(
            Entrega.entregador_id == user.id,
            HistoricoEntrega.status_novo == StatusEntrega.NAO_ENTREGUE.value,
            HistoricoEntrega.criado_em >= day_start,
            HistoricoEntrega.criado_em < next_day,
        )
    ).all()
    not_delivered_today = len({history.entrega_id for history in not_delivered_history})

    pending_delivery_ids = db.scalars(
        select(RotaEntrega.entrega_id)
        .join(Rota, Rota.id == RotaEntrega.rota_id)
        .join(Entrega, Entrega.id == RotaEntrega.entrega_id)
        .where(
            Rota.motorista_id == user.id,
            Rota.status.in_(active_statuses),
            Entrega.status.not_in([StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA]),
        )
    ).all()
    pending_count = len(set(pending_delivery_ids))

    distance_today = sum(
        float(route.distancia_real if route.distancia_real and route.distancia_real > 0 else route.distancia_prevista or 0)
        for route in completed_routes_today
    )
    duration_minutes = 0
    for route in completed_routes_today:
        if route.duracao_real and route.duracao_real > 0:
            duration_minutes += round(float(route.duracao_real) * 60)
        elif route.data_inicio and route.data_conclusao and route.data_conclusao >= route.data_inicio:
            duration_minutes += round((route.data_conclusao - route.data_inicio).total_seconds() / 60)
        elif route.duracao_prevista and route.duracao_prevista > 0:
            duration_minutes += round(float(route.duracao_prevista) * 60)

    vehicle = current_route.veiculo if current_route and current_route.veiculo else None
    if vehicle is None:
        vehicle = db.scalar(
            select(Veiculo)
            .where(Veiculo.motorista_id == user.id, Veiculo.ativo.is_(True))
            .order_by(Veiculo.id)
        )

    return {
        "data": now.date(),
        "entregas_concluidas_hoje": delivered_today,
        "entregas_nao_entregues_hoje": not_delivered_today,
        "entregas_pendentes": pending_count,
        "rotas_concluidas_hoje": len(completed_routes_today),
        "distancia_hoje_km": distance_today,
        "tempo_em_rota_hoje_minutos": duration_minutes,
        "veiculo_atual": vehicle,
        "rota_atual": current_route,
    }
@router.patch("/{rota_id}/confirmar-carga", response_model=RotaOut)
def confirm_route_loading(
    rota_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    if rota.status in {StatusRota.FINALIZADA, StatusRota.CANCELADA}:
        raise HTTPException(422, "Rota concluída ou cancelada não aceita confirmação de carga")
    rota.carga_confirmada = True
    commit(db)
    return rota


@router.get("/{rota_id}/sequencia-carregamento")
def get_route_loading_sequence(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)

    ordered = sorted(rota.entregas, key=lambda entry: (entry.ordem_visita or 0, entry.id), reverse=True)
    result = []
    for entry in ordered:
        entrega = db.get(Entrega, entry.entrega_id)
        pedido = entrega.pedido if entrega else None
        cliente_payload = None
        if pedido and pedido.cliente_id:
            cliente = db.get(Cliente, pedido.cliente_id)
            if cliente:
                cliente_payload = {"id": cliente.id, "nome": cliente.nome}
        result.append({
            "id": entry.id,
            "entrega_id": entry.entrega_id,
            "ordem_visita": entry.ordem_visita,
            "sequencia_otimizada": entry.sequencia_otimizada,
            "pedido_id": entrega.pedido_id if entrega else None,
            "numero_pedido": pedido.numero_pedido if pedido else None,
            "cliente": cliente_payload,
            "status": entrega.status.value if entrega and entrega.status else None,
        })
    return result


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
    user: Usuario = Depends(current_user),
):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    if rota.status == StatusRota.CANCELADA and user.perfil != Perfil.ADMIN:
        raise HTTPException(422, "Somente administrador pode reabrir rota cancelada")
    if data.status == StatusRota.CANCELADA and rota.status == StatusRota.FINALIZADA:
        raise HTTPException(422, "Rota finalizada não pode ser cancelada")
    if data.status == StatusRota.EM_EXECUCAO:
        if rota.motorista_id is None:
            raise HTTPException(422, "Rota precisa de um motorista associado para iniciar")
        driver = get_or_404(db, Usuario, rota.motorista_id)
        if driver.perfil != Perfil.MOTORISTA or not driver.ativo:
            raise HTTPException(422, "Motorista associado deve estar ativo e com perfil MOTORISTA")

        if user.perfil == Perfil.MOTORISTA and rota.motorista_id != user.id:
            raise HTTPException(403, "Acesso negado à rota de outro motorista")

        if not rota.carga_confirmada:
            raise HTTPException(422, "Carga não confirmada. Confirme a carga antes de iniciar a viagem. campo carga_confirmada obrigatório")

        if not route_has_pending_deliveries(db, rota):
            raise HTTPException(422, "Rota não possui entregas pendentes para execução")

        if rota.veiculo_id is None:
            if user.perfil != Perfil.MOTORISTA or rota.motorista_id != user.id:
                raise HTTPException(422, "Rota precisa de um veículo associado para iniciar")
        else:
            vehicle = get_or_404(db, Veiculo, rota.veiculo_id)
            if vehicle.organizacao_id != rota.organizacao_id:
                raise HTTPException(422, "Veículo associado não pertence à organização da rota")
            if user.perfil == Perfil.MOTORISTA and vehicle.motorista_id is not None and vehicle.motorista_id != driver.id:
                raise HTTPException(422, "Veículo associado deve estar compatível com o motorista da rota")
            if user.perfil != Perfil.MOTORISTA and vehicle.motorista_id is not None and vehicle.motorista_id != driver.id:
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
        rota.data_inicio = rota.data_inicio or current_time()
        for entry in rota.entregas:
            delivery = db.get(Entrega, entry.entrega_id)
            if delivery is None:
                continue
            if delivery.status not in {StatusEntrega.ENTREGUE, StatusEntrega.NAO_ENTREGUE, StatusEntrega.CANCELADA}:
                delivery.status = StatusEntrega.EM_ROTA
                db.add(HistoricoEntrega(
                    entrega_id=delivery.id,
                    status_anterior=StatusEntrega.AGUARDANDO_COLETA.value,
                    status_novo=StatusEntrega.EM_ROTA.value,
                    observacao="Entrega iniciada na viagem",
                    alterado_por=user.id,
                ))
    if data.status in {StatusRota.FINALIZADA, StatusRota.CANCELADA} and rota.data_conclusao is None:
        rota.data_conclusao = current_time()

    event = data.evento or _route_status_event(previous_status, data.status)

    should_log = previous_status != rota.status or data.evento is not None or data.observacao is not None or data.entrega_id is not None
    if should_log:
        if event is None:
            raise HTTPException(422, "Informe um evento semântico para esta transição de rota")
        rota.historico.append(RotaHistorico(
            evento=event,
            status_anterior=previous_status.value if previous_status else None,
            status_novo=data.status.value,
            observacao=data.observacao,
            entrega_id=data.entrega_id,
            alterado_por=user.id,
        ))
    commit(db)
    return rota


@router.post("/{rota_id}/otimizar", response_model=RotaOptimizationOut)
def optimize_route_endpoint(
    rota_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)

    if rota.status in {StatusRota.FINALIZADA, StatusRota.CANCELADA}:
        raise HTTPException(422, "Não é possível otimizar uma rota finalizada ou cancelada")
    if not rota.entregas:
        raise HTTPException(422, "Rota precisa de entregas para otimização")

    optimization = _persist_route_optimization(db, rota)
    commit(db)
    return optimization


@router.post("/{rota_id}/posicoes", response_model=RotaPosicaoOut, status_code=201)
async def create_route_position(
    rota_id: int,
    data: RotaPosicaoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(current_user),
):
    print(f"[TRACKING_BACKEND] request recebido rota={rota_id} motorista={user.id}")
    if user.perfil != Perfil.MOTORISTA:
        print("[TRACKING_BACKEND] rejeitado: usuário não é MOTORISTA")
        raise HTTPException(403, "Somente motoristas podem publicar posições")
    rota = get_or_404(db, Rota, rota_id)
    print(f"[TRACKING_BACKEND] rota status={rota.status.value} veiculo={rota.veiculo_id}")
    ensure_route_access_scope(user, rota)
    if rota.motorista_id != user.id:
        print("[TRACKING_BACKEND] rejeitado: motorista não pertence à rota")
        raise HTTPException(403, "A rota não pertence ao motorista autenticado")
    if rota.status != StatusRota.EM_EXECUCAO:
        print("[TRACKING_BACKEND] rejeitado: rota não está EM_EXECUCAO")
        raise HTTPException(422, "Posições só podem ser publicadas em rota EM_EXECUCAO")
    if rota.veiculo_id is None:
        print("[TRACKING_BACKEND] rejeitado: veículo ausente")
        raise HTTPException(422, "A rota precisa possuir veículo atribuído")

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

    if data.motorista_id is not None and data.motorista_id != user.id:
        raise HTTPException(403, "Motorista informado não corresponde ao autenticado")
    if data.veiculo_id is not None and data.veiculo_id != rota.veiculo_id:
        raise HTTPException(403, "Veículo informado não corresponde à rota")
    posicao = RotaPosicao(
        rota_id=rota_id,
        motorista_id=user.id,
        veiculo_id=rota.veiculo_id,
        **data.model_dump(exclude_none=True, exclude={"motorista_id", "veiculo_id"}),
    )
    db.add(posicao)
    commit(db)
    db.refresh(posicao)
    print(f"[TRACKING_BACKEND] posição persistida id={posicao.id}")
    payload = jsonable_encoder(RotaPosicaoOut.model_validate(posicao))
    print(f"[TRACKING_BACKEND] broadcast iniciado organizacao={rota.organizacao_id}")
    await manager.broadcast({"type": "rota_posicao", "payload": payload}, rota.organizacao_id)
    print("[TRACKING_BACKEND] broadcast concluído")
    return posicao


@router.get("/{rota_id}/historico", response_model=list[RotaHistoricoOut])
def get_route_history(rota_id: int, db: Session = Depends(get_db), user: Usuario = Depends(current_user)):
    rota = get_or_404(db, Rota, rota_id)
    ensure_route_access_scope(user, rota)
    return db.scalars(
        select(RotaHistorico).where(RotaHistorico.rota_id == rota_id).order_by(RotaHistorico.criado_em)
    ).all()
