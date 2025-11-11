"""
Stub de modelo EV en Python.

Objetivo: entrenar/ajustar un modelo en Colab que luego
exporta parámetros a un JSON que consumirá punterx-core.
"""

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class EvPrediction:
    fixture_id: str
    market: str
    ev: float               # decimal, p.ej. 0.18 = 18%
    prob_model: float       # 0..1
    version: str
    meta: Dict[str, Any]


def score_events(events: List[Dict[str, Any]]) -> List[EvPrediction]:
    """Stub simple para arrancar: aquí luego se conectará tu modelo real."""
    out: List[EvPrediction] = []
    for idx, ev in enumerate(events):
        fixture_id = str(ev.get("fixture_id") or idx)
        market = ev.get("market") or "h2h"

        # Por ahora: EV dummy suave, solo para probar el pipeline.
        base_ev = 0.05
        prob = 0.55

        out.append(
            EvPrediction(
                fixture_id=fixture_id,
                market=market,
                ev=base_ev,
                prob_model=prob,
                version="lab_stub_v0",
                meta={"reasons": ["lab_stub"]},
            )
        )
    return out
