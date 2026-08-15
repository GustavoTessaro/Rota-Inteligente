from datetime import datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import (
    ComprovanteEntrega,
    Entrega,
    HistoricoEntrega,
    Ocorrencia,
    Organizacao,
    Pedido,
    PedidoItem,
    Perfil,
    Rota,
    RotaEntrega,
    RotaHistorico,
    StatusEntrega,
    StatusRota,
    Usuario,
    Veiculo,
    Endereco,
)
from .security import require_roles
from .services.google_maps_service import get_geocoding_service

admin = require_roles(Perfil.ADMIN)
staff = require_roles(Perfil.ADMIN, Perfil.GESTOR)
delivery_roles = require_roles(Perfil.ADMIN, Perfil.GESTOR, Perfil.MOTORISTA)


def get_or_404(db: Session, model, item_id: int):
    item = db.get(model, item_id)
    if not item:
        raise HTTPException(404, "Registro não encontrado")
    return item


def commit(db: Session):
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(409, "Registro duplicado ou relacionamento inválido")


def validate_driver(db: Session, driver_id: int) -> Usuario:
    driver = get_or_404(db, Usuario, driver_id)
    if driver.perfil != Perfil.MOTORISTA or not driver.ativo:
        raise HTTPException(422, "O motorista deve possuir perfil MOTORISTA e estar ativo")
    return driver


def validate_organization(db: Session, organization_id: int) -> Organizacao:
    organization = get_or_404(db, Organizacao, organization_id)
    if not organization.ativo:
        raise HTTPException(422, "Organização inativa não pode receber veículos")
    return organization


def ensure_vehicle_access_scope(user: Usuario, vehicle: Veiculo):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None or vehicle.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Acesso negado ao veículo de outra organização")
        return
    if user.perfil == Perfil.MOTORISTA:
        if vehicle.motorista_id != user.id:
            raise HTTPException(403, "Acesso negado ao veículo de outro motorista")
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def ensure_vehicle_payload_scope(user: Usuario, data):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode gerir veículos")
        if data.organizacao_id is not None and data.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Gestor só pode gerir veículos de sua organização")
        data.organizacao_id = user.organizacao_id
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def ensure_manageable_user_payload(current: Usuario, data):
    if current.perfil == Perfil.ADMIN:
        return
    if current.perfil != Perfil.GESTOR:
        raise HTTPException(403, "Perfil sem permissão para esta operação")
    if data.perfil == Perfil.ADMIN:
        raise HTTPException(403, "Gestor não pode criar ou alterar usuários com perfil ADMIN")
    if current.organizacao_id is None:
        raise HTTPException(403, "Gestor sem organização não pode gerir usuários")
    if data.organizacao_id is not None and data.organizacao_id != current.organizacao_id:
        raise HTTPException(403, "Gestor só pode gerir usuários de sua organização")
    data.organizacao_id = current.organizacao_id


def ensure_user_management_scope(current: Usuario, target: Usuario):
    if current.perfil == Perfil.ADMIN:
        return
    if current.perfil != Perfil.GESTOR:
        raise HTTPException(403, "Perfil sem permissão para esta operação")
    if current.organizacao_id is None:
        raise HTTPException(403, "Gestor sem organização não pode gerir usuários")
    if target.perfil == Perfil.ADMIN:
        raise HTTPException(403, "Gestor não pode criar ou alterar usuários com perfil ADMIN")
    if target.organizacao_id is not None and target.organizacao_id != current.organizacao_id:
        raise HTTPException(403, "Gestor só pode gerir usuários de sua organização")
    if target.organizacao_id is None:
        target.organizacao_id = current.organizacao_id


def order_has_delivery(db: Session, order_id: int) -> bool:
    return bool(db.scalar(select(func.count()).select_from(Entrega).where(Entrega.pedido_id == order_id)))


def recalculate_order_total(order: Pedido):
    order.valor_total = sum((item.valor_unitario * item.quantidade for item in order.itens), Decimal("0"))


def ensure_route_access_scope(user: Usuario, rota: Rota):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None or rota.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Acesso negado à rota de outra organização")
        return
    if user.perfil == Perfil.MOTORISTA:
        if rota.motorista_id != user.id:
            raise HTTPException(403, "Acesso negado à rota de outro motorista")
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def ensure_route_payload_scope(user: Usuario, data):
    if user.perfil == Perfil.ADMIN:
        return
    if user.perfil == Perfil.GESTOR:
        if user.organizacao_id is None:
            raise HTTPException(403, "Gestor sem organização não pode gerir rotas")
        if data.organizacao_id is not None and data.organizacao_id != user.organizacao_id:
            raise HTTPException(403, "Gestor só pode gerir rotas de sua organização")
        data.organizacao_id = user.organizacao_id
        return
    raise HTTPException(403, "Perfil sem permissão para esta operação")


def validate_route_delivery_entries(db: Session, route_data):
    entrega_ids = set()
    for entry in route_data.entregas:
        if entry.entrega_id in entrega_ids:
            raise HTTPException(422, "Uma entrega só pode ser adicionada uma vez à rota")
        entrega_ids.add(entry.entrega_id)
        entrega = get_or_404(db, Entrega, entry.entrega_id)
        if entrega.status == StatusEntrega.CANCELADA:
            raise HTTPException(422, "Entrega cancelada não pode fazer parte da rota")


def geocode_address(db: Session, endereco: Endereco) -> dict:
    """
    Geocodifica um endereço usando Google Maps.
    
    Atualiza os campos:
    - latitude
    - longitude
    - endereco_formatado
    - place_id
    
    Args:
        db: Sessão do banco
        endereco: Objeto Endereco a geocodificar
        
    Returns:
        Dicionário com resultado:
        {
            "success": bool,
            "endereco_formatado": str | None,
            "latitude": float | None,
            "longitude": float | None,
            "place_id": str | None,
            "error": str | None,
        }
    """
    try:
        # Construir query apenas com os campos que afetam a geolocalização.
        # O complemento é persistido no banco, mas não deve ser enviado ao Nominatim/Google
        # porque ele pode quebrar o match do endereço ou gerar resultados inválidos.
        parts = [
            endereco.logradouro,
            endereco.numero,
            endereco.bairro,
            endereco.cidade,
            endereco.estado,
            endereco.cep,
        ]
        query = ", ".join(str(p) for p in parts if p)
        if "brasil" not in query.lower() and "brazil" not in query.lower():
            query = f"{query}, Brasil"
        
        if not query.strip():
            return {
                "success": False,
                "error": "Endereço vazio",
            }
        
        print(f"[DEBUG GEOCODE] Query enviada para Geocoding provider: {query}")

        # Chamar provedor de geocodificação configurado (Google ou Nominatim)
        geocoder = get_geocoding_service()
        response = geocoder.geocode(query)

        print(f"[DEBUG GEOCODE] Resposta do provedor: {response}")
        
        if not isinstance(response, dict):
            print(f"[DEBUG GEOCODE] Resposta não é dict: {type(response)}")
            return {
                "success": False,
                "error": "Resposta inválida da API de geocodificação",
            }
        
        # Verificar status da API
        api_status = response.get("status")
        print(f"[DEBUG GEOCODE] Status da API: {api_status}")
        
        if api_status != "OK":
            provider_name = (getattr(__import__('app.config', fromlist=['settings']).settings, 'geocoding_provider', 'nominatim') or 'nominatim').upper()
            provider_message = response.get("error_message")
            if provider_message:
                error_message = f"Provider {provider_name}: {provider_message}"
            else:
                error_message = f"API Status: {api_status}"
                if api_status == "ZERO_RESULTS":
                    error_message = f"Endereço não encontrado pelo provedor de geocodificação ({provider_name})"
                elif api_status == "INVALID_REQUEST":
                    error_message = f"Requisição inválida para o provedor de geocodificação ({provider_name})"
                elif api_status == "REQUEST_DENIED":
                    error_message = f"Requisição negada pelo provedor de geocodificação ({provider_name})"
                elif api_status == "OVER_QUERY_LIMIT":
                    error_message = f"Limite de requisições excedido no provedor ({provider_name})"
                elif api_status == "UNKNOWN_ERROR":
                    error_message = f"Erro desconhecido no provedor de geocodificação ({provider_name})"

            print(f"[DEBUG GEOCODE] Erro: {error_message}")
            return {
                "success": False,
                "error": error_message,
            }
        
        results = response.get("results", [])
        if not results:
            print(f"[DEBUG GEOCODE] Nenhum resultado encontrado (results vazio)")
            return {
                "success": False,
                "error": "Endereço não encontrado",
            }
        
        print(f"[DEBUG GEOCODE] Encontrado {len(results)} resultado(s)")
        
        first_result = results[0]
        print(f"[DEBUG GEOCODE] Primeiro resultado: {first_result}")
        
        geometry = first_result.get("geometry", {})
        location = geometry.get("location", {})
        
        lat = location.get("lat")
        lng = location.get("lng")
        formatted = first_result.get("formatted_address")
        place_id = first_result.get("place_id")
        
        print(f"[DEBUG GEOCODE] Coordinates: lat={lat}, lng={lng}, formatted={formatted}, place_id={place_id}")
        
        if lat is None or lng is None:
            print(f"[DEBUG GEOCODE] Coordenadas inválidas")
            return {
                "success": False,
                "error": "Coordenadas não encontradas",
            }
        
        # Atualizar o objeto
        endereco.latitude = Decimal(str(lat))
        endereco.longitude = Decimal(str(lng))
        endereco.endereco_formatado = formatted
        endereco.place_id = place_id
        
        print(f"[DEBUG GEOCODE] Endereço geocodificado com sucesso!")
        
        return {
            "success": True,
            "endereco_formatado": formatted,
            "latitude": float(lat),
            "longitude": float(lng),
            "place_id": place_id,
        }
        
    except Exception as exc:
        print(f"[DEBUG GEOCODE] Exceção: {str(exc)}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Erro ao geocodificar: {str(exc)}",
        }
