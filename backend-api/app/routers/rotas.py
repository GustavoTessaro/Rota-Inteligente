from datetime import datetime
from decimal import Decimal
from typing import Any

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
    Entrega,
    Organizacao,
    Pedido,
    Perfil,
    Produto,
    Rota,
    RotaEntrega,
    RotaHistorico,
    RotaPosicao,
    StatusEntrega,
    TipoEventoRota,
    Usuario,
    Veiculo,
)
from ..schemas import (
    RotaCreate,
    RotaGerarIn,
    RotaHistoricoOut,
    RotaOptimizationOut,
    RotaOut,
    RotaPosicaoCreate,
    RotaPosicaoOut,
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
        return None

    results = response.get("results") if isinstance(response, dict) else None
    if not results:
        return None

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
    validate_organization(db, data.organizacao_id)
    if data.veiculo_id is not None:
        vehicle = get_or_404(db, Veiculo, data.veiculo_id)
        if vehicle.organizacao_id != data.organizacao_id:
            raise HTTPException(422, "Veículo deve pertencer à organização da rota")
    if data.motorista_id is not None:
        driver = validate_driver(db, data.motorista_id)
        if driver.organizacao_id != data.organizacao_id:
            raise HTTPException(422, "Motorista deve pertencer à organização da rota")

    if not data.pedido_ids:
        raise HTTPException(422, "Selecione ao menos um pedido para gerar a rota")

    pedido_ids = list(dict.fromkeys(data.pedido_ids))
    orders = []
    for pedido_id in pedido_ids:
        pedido = get_or_404(db, Pedido, pedido_id)
        if pedido.cliente_id is None:
            raise HTTPException(422, f"Pedido {pedido_id} sem cliente associado")
        if pedido.endereco_entrega_id is None:
            raise HTTPException(422, f"Pedido {pedido_id} sem endereço de entrega cadastrado")
        get_or_404(db, Endereco, pedido.endereco_entrega_id)
        orders.append(pedido)

    collection_addresses: list[Endereco] = []
    for ponto_id in data.pontos_coleta_ids:
        org = get_or_404(db, Organizacao, ponto_id)
        if org.endereco_id is not None:
            collection_addresses.append(get_or_404(db, Endereco, org.endereco_id))

    deliveries = []
    for index, pedido in enumerate(orders, start=1):
        existing = db.scalar(select(Entrega).where(Entrega.pedido_id == pedido.id))
        if existing is None:
            origin_id = collection_addresses[0].id if collection_addresses else pedido.endereco_entrega_id
            existing = Entrega(
                pedido_id=pedido.id,
                entregador_id=data.motorista_id,
                endereco_origem_id=origin_id,
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
        data_planejada=data.data_planejada or datetime.utcnow(),
        origem_endereco_id=collection_addresses[0].id if collection_addresses else None,
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

    event = data.evento
    if event is None:
        if previous_status == StatusRota.EM_EXECUCAO and data.status == StatusRota.PAUSADA:
            event = TipoEventoRota.PAUSA
        elif previous_status == StatusRota.PAUSADA and data.status == StatusRota.EM_EXECUCAO:
            event = TipoEventoRota.RETOMADA
        elif data.status == StatusRota.FINALIZADA:
            event = TipoEventoRota.FINALIZADA
        elif data.status == StatusRota.EM_EXECUCAO and previous_status != StatusRota.EM_EXECUCAO:
            event = TipoEventoRota.PARTIDA

    should_log = previous_status != rota.status or data.evento is not None or data.observacao is not None or data.entrega_id is not None
    if should_log:
        rota.historico.append(RotaHistorico(
            evento=event or TipoEventoRota.PARTIDA,
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
