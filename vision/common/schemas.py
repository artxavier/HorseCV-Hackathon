"""Contrato do servidor de inferencia (CLAUDE.md §5).

Identico nos tres modos (edge / fog / cloud). Coordenadas sempre em pixels do
frame que foi enviado no POST /infer.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple

BBox = Tuple[float, float, float, float]  # x1, y1, x2, y2
Polygon = List[Tuple[float, float]]


@dataclass
class Face:
    bbox: List[float]  # x, y, w, h (no frame enviado)
    score: float
    embedding: List[float]
    crop_jpg_b64: Optional[str] = None

    @property
    def size_px(self) -> float:
        return max(self.bbox[2], self.bbox[3])

    @property
    def quality(self) -> float:
        """score * min(lado, 112) -- criterio do ring buffer (§6)."""
        return float(self.score) * min(self.size_px, 112.0)


@dataclass
class Person:
    bbox: List[float]
    conf: float
    face: Optional[Face] = None


@dataclass
class Bike:
    bbox: List[float]
    conf: float
    polygon: Optional[Polygon] = None


@dataclass
class InferResponse:
    model: str
    device: str
    inference_ms: float
    width: int
    height: int
    bikes: List[Bike] = field(default_factory=list)
    persons: List[Person] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def face_from_dict(d: Optional[dict]) -> Optional[Face]:
    if not d:
        return None
    return Face(
        bbox=list(d["bbox"]),
        score=float(d["score"]),
        embedding=list(d.get("embedding") or []),
        crop_jpg_b64=d.get("crop_jpg_b64"),
    )


def response_from_dict(d: dict) -> InferResponse:
    """Usado pelo agente para reidratar a resposta JSON."""
    return InferResponse(
        model=d.get("model", "?"),
        device=d.get("device", "?"),
        inference_ms=float(d.get("inference_ms", 0.0)),
        width=int(d.get("width", 0)),
        height=int(d.get("height", 0)),
        bikes=[
            Bike(bbox=list(b["bbox"]), conf=float(b["conf"]), polygon=b.get("polygon"))
            for b in d.get("bikes", [])
        ],
        persons=[
            Person(bbox=list(p["bbox"]), conf=float(p["conf"]), face=face_from_dict(p.get("face")))
            for p in d.get("persons", [])
        ],
    )

