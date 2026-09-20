"""Ocupacao das vagas (CLAUDE.md §6).

No angulo frontal cada vaga e uma faixa vertical entre duas barras do rack. Uma
vaga esta ocupada quando a uniao das mascaras de bike cobre pelo menos
`occupancy_threshold` da area do poligono da vaga.
"""

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from common.geometry import bbox_to_polygon, coverage, denorm_polygon, polygon_bounds
from common.schemas import Bike


@dataclass
class Slot:
    id: str
    polygon_norm: List[Tuple[float, float]]
    polygon_px: List[Tuple[float, float]]

    @property
    def bounds_px(self) -> List[float]:
        return polygon_bounds(self.polygon_px)


@dataclass
class SlotsConfig:
    camera_id: str
    slots: List[Slot]
    interaction_zone_norm: List[Tuple[float, float]]
    interaction_zone_px: List[Tuple[float, float]]


def load_slots(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_slots(raw: dict, width: int, height: int) -> SlotsConfig:
    """Converte os poligonos normalizados de slots.json para pixels do frame cheio."""
    slots = []
    for s in raw.get("slots", []):
        poly_norm = [(float(x), float(y)) for x, y in s["polygon"]]
        slots.append(
            Slot(
                id=str(s["id"]),
                polygon_norm=poly_norm,
                polygon_px=denorm_polygon(poly_norm, width, height),
            )
        )
    zone_norm = [(float(x), float(y)) for x, y in raw.get("interaction_zone", [])]
    return SlotsConfig(
        camera_id=str(raw.get("camera_id", "cam1")),
        slots=slots,
        interaction_zone_norm=zone_norm,
        interaction_zone_px=denorm_polygon(zone_norm, width, height) if zone_norm else [],
    )


def bike_shapes(bikes: Sequence[Bike]) -> List[List[Tuple[float, float]]]:
    """Poligono de cada bike; sem mascara, usa a bbox (§6)."""
    shapes = []
    for b in bikes:
        if b.polygon and len(b.polygon) >= 3:
            shapes.append([(float(x), float(y)) for x, y in b.polygon])
        else:
            shapes.append(bbox_to_polygon(b.bbox))
    return shapes


def compute_coverage(
    slots: Sequence[Slot],
    bikes: Sequence[Bike],
    frame_size: Tuple[int, int],
) -> Dict[str, float]:
    shapes = bike_shapes(bikes)
    return {slot.id: coverage(slot.polygon_px, shapes, frame_size) for slot in slots}


def raw_occupancy(
    slots: Sequence[Slot],
    bikes: Sequence[Bike],
    frame_size: Tuple[int, int],
    threshold: float = 0.25,
) -> Tuple[Dict[str, bool], Dict[str, float]]:
    """Estado bruto (por frame) de cada vaga + a cobertura medida, para debug."""
    cov = compute_coverage(slots, bikes, frame_size)
    return {sid: value >= threshold for sid, value in cov.items()}, cov


def slot_for_bike(slots: Sequence[Slot], bike: Bike, frame_size: Tuple[int, int]) -> Optional[str]:
    """Vaga mais coberta por esta bike. None = bike fora do rack monitorado (§4.1)."""
    shape = bike_shapes([bike])
    best_id, best_val = None, 0.0
    for slot in slots:
        val = coverage(slot.polygon_px, shape, frame_size)
        if val > best_val:
            best_id, best_val = slot.id, val
    return best_id
