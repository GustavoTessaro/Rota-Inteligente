from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .services import get_google_maps_service

router = APIRouter(prefix="/api/maps")


@router.get("/config")
def maps_config():
    """Return public maps configuration (no secret keys)."""
    from .config import settings
    # Only return the restricted key intended for browser use (if provided)
    return {
        "maps_default_center": settings.maps_default_center,
        "google_maps_key": settings.google_maps_restricted_key or None,
    }


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


class DirectionsSummary(BaseModel):
    encoded_polyline: str | None = None
    distance_meters: int | None = None
    duration_seconds: int | None = None
    waypoint_order: list[int] | None = None
    instructions: list[str] | None = None
    raw: dict | None = None


@router.post("/geocode", response_model=GeocodeOut)
def geocode(payload: GeocodeIn, svc=Depends(get_google_maps_service)):
    try:
        res = svc.geocode(payload.address)
        return {"raw": res}
    except Exception as e:
        raise HTTPException(502, f"Erro no serviço de geocodificação: {e}")


@router.post("/directions", response_model=DirectionsSummary)
def directions(payload: DirectionsIn, svc=Depends(get_google_maps_service)):
    try:
        res = svc.directions(payload.origin, payload.destination, payload.waypoints, payload.travel_mode)
    except Exception as e:
        raise HTTPException(502, f"Erro no serviço de rotas: {e}")

    # defensive parsing of Google Routes response
    route = None
    try:
        routes = res.get("routes") if isinstance(res, dict) else None
        if routes:
            route = routes[0]
    except Exception:
        route = None

    encoded = None
    distance = None
    duration = None
    waypoint_order = None
    instructions = []

    if route:
        # polyline
        poly = route.get("polyline") or route.get("overview_polyline")
        if isinstance(poly, dict):
            encoded = poly.get("encodedPolyline") or poly.get("points")
        elif isinstance(route.get("legs"), list):
            # try to join leg polylines
            leg_points = []
            for leg in route.get("legs", []):
                lp = leg.get("polyline") or {}
                p = lp.get("encodedPolyline") or lp.get("points")
                if p:
                    leg_points.append(p)
            if leg_points:
                # prefer first if no overview
                encoded = leg_points[0]

        # distance/duration
        if route.get("distanceMeters") is not None:
            distance = int(route.get("distanceMeters"))
        else:
            # sum legs
            try:
                distance = sum(int(leg.get("distanceMeters", 0)) for leg in route.get("legs", []))
            except Exception:
                distance = None

        if route.get("duration") is not None:
            # some APIs return nested duration with seconds
            dur = route.get("duration")
            if isinstance(dur, dict) and dur.get("seconds") is not None:
                duration = int(dur.get("seconds"))
            elif isinstance(dur, (int, float)):
                duration = int(dur)
        else:
            try:
                duration = sum(int(leg.get("durationSeconds", 0)) or int(leg.get("duration", {}).get("seconds", 0)) for leg in route.get("legs", []))
            except Exception:
                duration = None

        # waypoint order (if present)
        waypoint_order = route.get("waypointOrder") or route.get("optimizedWaypointOrder") or route.get("waypoint_order")

        # instructions: collect top-level step text from legs
        for leg in route.get("legs", []):
            for step in leg.get("steps", []) if isinstance(leg.get("steps"), list) else []:
                text = None
                # common keys
                if isinstance(step, dict):
                    text = step.get("html_instructions") or step.get("instruction") or step.get("travel_advice")
                    # nested navigation instruction
                    nav = step.get("navigationInstruction") or step.get("maneuver")
                    if not text and isinstance(nav, dict):
                        text = nav.get("displayText") or nav.get("instructions")
                if text:
                    instructions.append(text)

    summary = {
        "encoded_polyline": encoded,
        "distance_meters": distance,
        "duration_seconds": duration,
        "waypoint_order": waypoint_order,
        "instructions": instructions or None,
        "raw": res,
    }
    return summary


@router.post("/optimize")
def optimize(payload: DirectionsIn, svc=Depends(get_google_maps_service)):
    # lightweight stub for optimization
    return svc.optimize_route(payload.waypoints or [])
