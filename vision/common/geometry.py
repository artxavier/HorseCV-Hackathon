"""Geometria: IoU, cobertura de vaga por mascaras, conversao de coordenadas.

Vagas e zona de interacao vivem normalizadas [0..1] em config/slots.json e sao
convertidas para pixels no agente (CLAUDE.md §13).
"""

from typing import Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

Point = Tuple[float, float]
Polygon = Sequence[Point]
BBox = Sequence[float]

# grade usada para rasterizar a cobertura da vaga (§6)
COVERAGE_GRID = (160, 120)  # (w, h)


def denorm_polygon(poly: Polygon, width: int, height: int) -> List[Point]:
    return [(float(x) * width, float(y) * height) for x, y in poly]


def denorm_bbox(box: BBox, width: int, height: int) -> List[float]:
    x1, y1, x2, y2 = box
    return [x1 * width, y1 * height, x2 * width, y2 * height]


def bbox_to_polygon(box: BBox) -> List[Point]:
    x1, y1, x2, y2 = box
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def polygon_bounds(poly: Polygon) -> List[float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def iou(a: BBox, b: BBox) -> float:
    inter = _intersection_area(a, b)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def bbox_intersection_ratio(inner: BBox, outer: BBox) -> float:
    """Fracao da area de `outer` coberta por `inner`. Fallback sem mascara."""
    area_outer = max(0.0, outer[2] - outer[0]) * max(0.0, outer[3] - outer[1])
    if area_outer <= 0:
        return 0.0
    return _intersection_area(inner, outer) / area_outer


def _intersection_area(a: BBox, b: BBox) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def horizontal_overlap(a: BBox, b: BBox) -> float:
    """Fracao da largura de `a` que se sobrepoe horizontalmente a `b`.

    No angulo frontal as vagas sao colunas, entao o que liga uma pessoa a uma
    vaga e a sobreposicao em x (§4.1).
    """
    width_a = max(0.0, a[2] - a[0])
    if width_a <= 0:
        return 0.0
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    return overlap / width_a


def point_in_polygon(point: Point, poly: Polygon) -> bool:
    contour = np.array(poly, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(contour, (float(point[0]), float(point[1])), False) >= 0


def bbox_foot(box: BBox) -> Point:
    """Ponto dos 'pes': centro da borda inferior da bbox."""
    return ((box[0] + box[2]) / 2.0, box[3])


def _rasterize(polys: Iterable[Polygon], size: Tuple[int, int], scale: Tuple[float, float]) -> np.ndarray:
    mask = np.zeros((size[1], size[0]), dtype=np.uint8)
    contours = []
    for poly in polys:
        pts = np.array([[p[0] * scale[0], p[1] * scale[1]] for p in poly], dtype=np.int32)
        if len(pts) >= 3:
            contours.append(pts)
    if contours:
        cv2.fillPoly(mask, contours, 1)
    return mask


def coverage(
    slot_poly: Polygon,
    shapes: Iterable[Polygon],
    frame_size: Tuple[int, int],
    grid: Tuple[int, int] = COVERAGE_GRID,
) -> float:
    """Fracao da area da vaga coberta pela uniao de `shapes`.

    `frame_size` e (w, h) do frame em que os poligonos estao em pixels.
    """
    fw, fh = frame_size
    if fw <= 0 or fh <= 0:
        return 0.0
    scale = (grid[0] / fw, grid[1] / fh)
    slot_mask = _rasterize([slot_poly], grid, scale)
    slot_area = int(slot_mask.sum())
    if slot_area == 0:
        return 0.0
    shapes_mask = _rasterize(shapes, grid, scale)
    inter = int(np.logical_and(slot_mask, shapes_mask).sum())
    return inter / slot_area


def crop_roi(frame: np.ndarray, roi: Optional[Sequence[float]]) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Recorta a ROI normalizada [x1, y1, x2, y2]; devolve (recorte, offset px)."""
    if not roi:
        return frame, (0, 0)
    h, w = frame.shape[:2]
    x1 = int(max(0.0, min(1.0, roi[0])) * w)
    y1 = int(max(0.0, min(1.0, roi[1])) * h)
    x2 = int(max(0.0, min(1.0, roi[2])) * w)
    y2 = int(max(0.0, min(1.0, roi[3])) * h)
    if x2 - x1 < 16 or y2 - y1 < 16:
        return frame, (0, 0)
    return frame[y1:y2, x1:x2], (x1, y1)
