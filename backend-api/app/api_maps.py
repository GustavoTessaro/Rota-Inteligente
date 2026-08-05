from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .services import get_google_maps_service

router = APIRouter(prefix="/api/maps")


class GeocodeIn(BaseModel):
    address: str


class GeocodeOut(BaseModel):
    raw: dict


class DirectionsIn(BaseModel):
    origin: dict
    destination: dict
    waypoints: list | None = None
    travel_mode: str = "DRIVE"


class DirectionsOut(BaseModel):
    raw: dict


@router.post("/geocode", response_model=GeocodeOut)
def geocode(payload: GeocodeIn, svc=Depends(get_google_maps_service)):
    try:
        res = svc.geocode(payload.address)
        return {"raw": res}
    except Exception as e:
        raise HTTPException(502, f"Erro no serviço de geocodificação: {e}")


@router.post("/directions", response_model=DirectionsOut)
def directions(payload: DirectionsIn, svc=Depends(get_google_maps_service)):
    try:
        res = svc.directions(payload.origin, payload.destination, payload.waypoints, payload.travel_mode)
        return {"raw": res}
    except Exception as e:
        raise HTTPException(502, f"Erro no serviço de rotas: {e}")


@router.post("/optimize")
def optimize(payload: DirectionsIn, svc=Depends(get_google_maps_service)):
    # lightweight stub for optimization
    return svc.optimize_route(payload.waypoints or [])
