"""Overlay das vagas e deteccoes -- e o que a portaria ve no Dashboard."""

from typing import Dict, Optional, Sequence

import cv2
import numpy as np

COLOR_EMPTY = (80, 200, 80)      # verde
COLOR_OCCUPIED = (230, 160, 40)  # azul (BGR)
COLOR_BIKE = (0, 215, 255)
COLOR_PERSON = (200, 200, 200)
COLOR_FACE = (60, 60, 240)
COLOR_ZONE = (160, 120, 255)


def _poly(points) -> np.ndarray:
    return np.array(points, dtype=np.int32).reshape(-1, 1, 2)


def draw_overlay(
    frame,
    slots,
    states: Dict[str, str],
    bikes: Sequence,
    persons: Sequence,
    coverage: Optional[Dict[str, float]] = None,
    interaction_zone_px: Optional[Sequence] = None,
    header: str = "",
    offset=(0, 0),
):
    """Desenha tudo num frame BGR. `offset` = canto da ROI, para as deteccoes
    voltarem para as coordenadas do frame cheio."""
    out = frame.copy()
    ox, oy = offset

    if interaction_zone_px:
        cv2.polylines(out, [_poly(interaction_zone_px)], True, COLOR_ZONE, 1, cv2.LINE_AA)

    overlay = out.copy()
    for slot in slots:
        occupied = states.get(slot.id) == "OCCUPIED"
        color = COLOR_OCCUPIED if occupied else COLOR_EMPTY
        cv2.fillPoly(overlay, [_poly(slot.polygon_px)], color)
    cv2.addWeighted(overlay, 0.22, out, 0.78, 0, out)

    for slot in slots:
        occupied = states.get(slot.id) == "OCCUPIED"
        color = COLOR_OCCUPIED if occupied else COLOR_EMPTY
        cv2.polylines(out, [_poly(slot.polygon_px)], True, color, 2, cv2.LINE_AA)
        x1, y1, _x2, _y2 = slot.bounds_px
        label = slot.id
        if coverage is not None and slot.id in coverage:
            label += f" {coverage[slot.id]:.2f}"
        cv2.putText(out, label, (int(x1) + 4, int(y1) + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

    for b in bikes:
        x1, y1, x2, y2 = [int(v) for v in b.bbox]
        cv2.rectangle(out, (x1 + ox, y1 + oy), (x2 + ox, y2 + oy), COLOR_BIKE, 2)
        if b.polygon:
            cv2.polylines(out, [_poly([(p[0] + ox, p[1] + oy) for p in b.polygon])], True, COLOR_BIKE, 1, cv2.LINE_AA)
        cv2.putText(out, f"bike {b.conf:.2f}", (x1 + ox, y1 + oy - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_BIKE, 1, cv2.LINE_AA)

    for p in persons:
        x1, y1, x2, y2 = [int(v) for v in p.bbox]
        cv2.rectangle(out, (x1 + ox, y1 + oy), (x2 + ox, y2 + oy), COLOR_PERSON, 1)
        cv2.putText(out, f"pessoa {p.conf:.2f}", (x1 + ox, y1 + oy - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_PERSON, 1, cv2.LINE_AA)
        if p.face is not None:
            fx, fy, fw, fh = [int(v) for v in p.face.bbox]
            cv2.rectangle(out, (fx + ox, fy + oy), (fx + fw + ox, fy + fh + oy), COLOR_FACE, 2)
            cv2.putText(out, f"{p.face.score:.2f}", (fx + ox, fy + oy - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_FACE, 1, cv2.LINE_AA)

    if header:
        cv2.rectangle(out, (0, 0), (out.shape[1], 26), (20, 20, 20), -1)
        cv2.putText(out, header, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
    return out


def encode_jpg(frame, quality: int = 75) -> Optional[bytes]:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else None
