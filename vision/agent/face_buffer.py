"""Ring buffer de rostos recentes por vaga (CLAUDE.md §6).

Ao encaixar a bike a pessoa olha para baixo, entao o melhor rosto costuma ser o da
chegada -- por isso a janela e generosa (15 s) e a busca comeca ANTES do inicio da
transicao bruta.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from common.geometry import bbox_foot, horizontal_overlap, point_in_polygon
from common.schemas import Face, Person


@dataclass
class FaceRecord:
    ts: float
    slot_id: str
    score: float
    quality: float
    embedding: List[float]
    crop_jpg_b64: Optional[str]


class FaceBuffer:
    def __init__(self, window_seconds: float = 15.0, max_per_slot: int = 300):
        self.window_seconds = window_seconds
        self._by_slot: Dict[str, Deque[FaceRecord]] = defaultdict(lambda: deque(maxlen=max_per_slot))

    def add(self, ts: float, slot_id: str, face: Face) -> None:
        if not face.embedding:
            return
        self._by_slot[slot_id].append(
            FaceRecord(
                ts=ts,
                slot_id=slot_id,
                score=float(face.score),
                quality=float(face.quality),
                embedding=list(face.embedding),
                crop_jpg_b64=face.crop_jpg_b64,
            )
        )

    def prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for buf in self._by_slot.values():
            while buf and buf[0].ts < cutoff:
                buf.popleft()

    def best(self, slot_id: str, since_ts: float, top_k: int = 5) -> List[FaceRecord]:
        """Os `top_k` rostos de maior qualidade da vaga desde `since_ts`."""
        candidates = [r for r in self._by_slot.get(slot_id, ()) if r.ts >= since_ts]
        candidates.sort(key=lambda r: r.quality, reverse=True)
        return candidates[:top_k]

    def clear(self, slot_id: str) -> None:
        self._by_slot.pop(slot_id, None)

    def count(self, slot_id: str) -> int:
        return len(self._by_slot.get(slot_id, ()))


def link_faces_to_slots(
    persons: Sequence[Person],
    slots,
    interaction_zone_px: Optional[Sequence[Tuple[float, float]]] = None,
    min_column_overlap: float = 0.3,
) -> List[Tuple[str, Face]]:
    """Liga cada rosto valido as vagas plausiveis (§4.1 e §6).

    Duas condicoes: os pes da pessoa caem na `interaction_zone` (isso filtra os
    transeuntes da calcada) e a faixa horizontal da pessoa cobre a coluna da vaga.
    """
    pairs: List[Tuple[str, Face]] = []
    for person in persons:
        face = person.face
        if face is None or not face.embedding:
            continue
        if interaction_zone_px and not point_in_polygon(bbox_foot(person.bbox), interaction_zone_px):
            continue
        for slot in slots:
            if horizontal_overlap(slot.bounds_px, person.bbox) >= min_column_overlap:
                pairs.append((slot.id, face))
    return pairs
