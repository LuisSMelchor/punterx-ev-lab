"""
Modelo EV sencillo (lab v1).

Objetivo:
- Usar solo la info que ya tenemos (commence_time, league).
- Dar más EV a:
  - Partidos más cercanos en el tiempo.
  - Ligas importantes (Champions, World Cup, etc).
- Mantener un rango razonable de EV (0..0.10 por ahora).
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


@dataclass
class EvPrediction:
    fixture_id: str
    market: str
    ev: float               # decimal, p.ej. 0.18 = 18%
    prob_model: float       # 0..1
    version: str
    meta: Dict[str, Any]


def _minutes_to_start(ev: Dict[str, Any]) -> Optional[float]:
    """
    Calcula minutos hasta el inicio a partir de campos típicos.
    Compatible con el formato de ev-ndjson de punterx-core.
    """
    iso = (
        ev.get("commence_time")
        or ev.get("tsISO")
        or (ev.get("fixture") or {}).get("date")
        or ev.get("date")
    )
    if not iso:
        return None
    try:
        s = str(iso)
        # Manejar "2025-11-16T13:00:00Z"
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return None

    now = datetime.now(timezone.utc)
    return (ts - now).total_seconds() / 60.0


def _is_big_league(name: str) -> bool:
    if not name:
        return False
    s = name.lower()
    keywords = [
        "world cup",
        "champions league",
        "premier league",
        "la liga",
        "serie a",
        "bundesliga",
        "ligue 1",
        "europa league",
    ]
    return any(k in s for k in keywords)


def _score_single(ev: Dict[str, Any]) -> float:
    """
    Heurística v1:
    - Base 0.01.
    - Bumps por ventana de tiempo.
    - Bump por liga importante.
    """
    base = 0.01
    mins = _minutes_to_start(ev)
    league = ev.get("league") or ""

    # Bump por tiempo a inicio (pensando en cuando falten pocas horas).
    if mins is not None:
        if 20 <= mins <= 60:
            base += 0.03
        elif 60 < mins <= 180:
            base += 0.025
        elif 180 < mins <= 360:
        #     3 a 6 horas
            base += 0.02
        elif 360 < mins <= 1440:
        #     6h a 24h
            base += 0.015
        else:
            base += 0.0

    # Liga "grande"
    if _is_big_league(league):
        base += 0.015

    # Cap y piso
    ev_val = max(0.0, min(0.10, base))
    return ev_val


def score_events(events: List[Dict[str, Any]]) -> List[EvPrediction]:
    """Aplica la heurística v1 a una lista de eventos."""
    out: List[EvPrediction] = []
    for idx, ev in enumerate(events or []):
        fixture_id = str(ev.get("fixture_id") or idx)
        market = ev.get("market") or "h2h"

        ev_val = _score_single(ev)
        # Probabilidad modelo simple: 0.5 + EV (0.5..0.6)
        prob = 0.5 + ev_val

        out.append(
            EvPrediction(
                fixture_id=fixture_id,
                market=market,
                ev=ev_val,
                prob_model=min(0.99, max(0.01, prob)),
                version="lab_v1_time_league",
                meta={
                    "reasons": ["time_window", "league_importance"],
                },
            )
        )
    return out
