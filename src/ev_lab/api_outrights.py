from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime, timezone

app = FastAPI(
    title="PunterX EV Lab - Outrights",
    version="0.1.0",
    description="Servicio EV para apuestas futuras (outrights) de torneos de fútbol.",
)


# --------- Modelos de entrada/salida --------- #

class Outcome(BaseModel):
    name: str
    price: float


class Market(BaseModel):
    key: str
    outcomes: List[Outcome] = Field(default_factory=list)


class Bookmaker(BaseModel):
    title: str
    markets: List[Market] = Field(default_factory=list)


class Event(BaseModel):
    id: Optional[str] = None
    sport_key: Optional[str] = None
    sport_title: Optional[str] = None
    commence_time: Optional[datetime] = None
    bookmakers: List[Bookmaker] = Field(default_factory=list)


class OutrightsRequest(BaseModel):
    event: Event


class OutrightsResponse(BaseModel):
    ev: float
    selection_name: str
    selection_key: Optional[str] = None
    price: float
    bookmaker_title: str
    edge_reason: str


# --------- Configuración de torneos prioritarios --------- #

# Esta lista se puede ajustar mirando lo que devuelve diag-outrights
# en punterx-core (sport_key reales de OddsAPI).
OUTRIGHTS_PRIORITY: Dict[str, str] = {
    "soccer_fifa_world_cup_winner": "alta",
    "soccer_uefa_champions_league_winner": "alta",
    "soccer_uefa_european_championship_winner": "alta",
    "soccer_copa_america_winner": "media",
    "soccer_uefa_europa_league_winner": "media",
}


def _priority_factor(sport_key: Optional[str]) -> float:
    if not sport_key:
        return 0.4
    level = OUTRIGHTS_PRIORITY.get(sport_key, "baja")
    if level == "alta":
        return 1.0
    if level == "media":
        return 0.7
    return 0.4  # baja


def _time_factor(commence_time: Optional[datetime]) -> float:
    """
    Factor de 0..1 según la distancia en días al inicio del torneo.

    - <= 0 días: 0.0 (ya empezó o está en el pasado).
    - > 365 días: 0.1 (demasiado lejos, casi sin señal).
    - 30..365 días: 0.4 (seguimiento general).
    - 7..30 días: 0.7 (ya bastante cerca).
    - 0..7 días: 1.0 (ventana caliente).
    """
    if not commence_time:
        return 0.0

    now = datetime.now(timezone.utc)
    if commence_time.tzinfo is None:
        commence_time = commence_time.replace(tzinfo=timezone.utc)

    delta_days = (commence_time - now).total_seconds() / 86400.0

    if delta_days <= 0:
        return 0.0
    if delta_days > 365:
        return 0.1
    if delta_days > 30:
        return 0.4
    if delta_days > 7:
        return 0.7
    return 1.0  # 0..7 días


def _price_factor(price: float) -> float:
    """
    Factor heurístico según el rango de cuota.

    Buscamos evitar favoritos ultra cortos y super-longshots,
    y priorizar cuotas "semi-realistas" tipo 3-6, 6-15, etc.
    """
    if price <= 1.3 or price > 200:
        return 0.0
    if 1.3 < price <= 2.5:
        return 0.5
    if 2.5 < price <= 6.0:
        return 1.0
    if 6.0 < price <= 15.0:
        return 0.8
    if 15.0 < price <= 30.0:
        return 0.5
    if 30.0 < price <= 60.0:
        return 0.3
    return 0.2  # 60..200 pero no tan extremos


def _compute_ev_raw(time_f: float, price_f: float, priority_f: float) -> float:
    """
    Combina los factores en un score 0..1 y lo escala a un rango EV 0..0.25 aprox.
    """
    score = (0.4 * time_f) + (0.4 * price_f) + (0.2 * priority_f)
    score_clamped = max(0.0, min(1.0, score))
    ev = 0.25 * score_clamped
    return round(ev, 3)


def _flatten_candidates(event: Event):
    """
    Devuelve una lista de candidatos:
    [(bookmaker_title, outcome_name, price, market_key)]
    tomando solo markets tipo 'outrights' / 'winner'.
    """
    candidates = []
    for bm in event.bookmakers:
        title = bm.title or "Unknown"
        for mk in bm.markets:
            key = (mk.key or "").lower()
            if "outright" not in key and key not in ("outrights", "winner"):
                continue
            for outcome in mk.outcomes:
                try:
                    price = float(outcome.price)
                except (TypeError, ValueError):
                    continue
                if price <= 1.0:
                    continue
                candidates.append((title, outcome.name, price, key))
    return candidates


def score_outright_event(event_dict: dict) -> OutrightsResponse:
    """
    Función principal de modelo.
    Recibe un event (dict como viene de OddsAPI) y devuelve OutrightsResponse.
    """
    event = Event.parse_obj(event_dict)

    if not event.bookmakers:
        return OutrightsResponse(
            ev=0.0,
            selection_name="N/A",
            selection_key=None,
            price=1.0,
            bookmaker_title="N/A",
            edge_reason="Sin bookmakers en el evento; no se puede evaluar EV.",
        )

    candidates = _flatten_candidates(event)
    if not candidates:
        return OutrightsResponse(
            ev=0.0,
            selection_name="N/A",
            selection_key=None,
            price=1.0,
            bookmaker_title="N/A",
            edge_reason="Sin outcomes válidos de outrights en el evento.",
        )

    time_f = _time_factor(event.commence_time)
    priority_f = _priority_factor(event.sport_key)

    best = None
    best_ev = -1.0

    for (bm_title, outcome_name, price, mkey) in candidates:
        price_f = _price_factor(price)
        ev_val = _compute_ev_raw(time_f, price_f, priority_f)
        if ev_val > best_ev:
            best_ev = ev_val
            best = (bm_title, outcome_name, price, mkey)

    if best is None or best_ev <= 0:
        return OutrightsResponse(
            ev=0.0,
            selection_name="N/A",
            selection_key=None,
            price=1.0,
            bookmaker_title="N/A",
            edge_reason="Modelo heurístico no encontró valor en este torneo.",
        )

    bm_title, outcome_name, price, mkey = best
    selection_key = f"{mkey}:{outcome_name}"

    now = datetime.now(timezone.utc)
    if event.commence_time and event.commence_time.tzinfo is None:
        event_ct = event.commence_time.replace(tzinfo=timezone.utc)
    else:
        event_ct = event.commence_time

    if event_ct:
        days_to_start = (event_ct - now).total_seconds() / 86400.0
        days_txt = f"{days_to_start:.1f} días"
    else:
        days_txt = "desconocido"

    sport_title = event.sport_title or event.sport_key or "torneo"

    edge_reason = (
        f"Torneo: {sport_title}. "
        f"Comienza en {days_txt}. "
        f"Selección: {outcome_name} @ {price:.2f} en {bm_title}. "
        f"Factores considerados: ventana temporal, rango de cuota y prioridad del torneo."
    )

    return OutrightsResponse(
        ev=best_ev,
        selection_name=outcome_name,
        selection_key=selection_key,
        price=price,
        bookmaker_title=bm_title,
        edge_reason=edge_reason,
    )


# --------- Endpoints HTTP --------- #

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "ev-outrights",
        "version": "0.1.0",
    }


@app.post("/ev/outrights/score", response_model=OutrightsResponse)
def ev_outrights_score(payload: OutrightsRequest) -> OutrightsResponse:
    """
    Endpoint que consumirá punterx-core (OUTRIGHTS_EV_URL).

    Recibe:  { "event": { ... } }
    Devuelve: { ev, selection_name, selection_key, price, bookmaker_title, edge_reason }
    """
    event_dict = payload.event.dict()
    try:
        return score_outright_event(event_dict)
    except Exception as exc:
        # En producción real se podría loguear con más detalle.
        return OutrightsResponse(
            ev=0.0,
            selection_name="Error",
            selection_key=None,
            price=1.0,
            bookmaker_title="N/A",
            edge_reason=f"error_modelo: {exc}",
        )
