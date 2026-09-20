"""Servidor de inferencia -- identico nos tres modos: edge, fog e cloud (CLAUDE.md §5).

Stateless: sem tracking, sem sessao. Todo o estado vive no agente.

    uvicorn inference.server:app --host 0.0.0.0 --port 8001

Variaveis de ambiente:
    DETECTOR      yolo26 | rfdetr        (default: yolo26)
    YOLO_WEIGHTS  caminho do .pt         (default: yolo26n-seg.pt)
    FACE_BACKEND  insightface | opencv   (default: insightface, com fallback automatico)
    DEVICE        cpu | cuda | 0 | ...   (default: cuda se disponivel)
    DEVICE_LABEL  rotulo mostrado nas metricas (ex.: rpi5-cpu, laptop-cuda)
"""

import logging
import os
import time
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Query, UploadFile
from fastapi.responses import JSONResponse

from common.schemas import InferResponse
from inference import faces as faces_mod
from inference.detector import build_detector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("inference")

DEFAULT_DETECTOR = os.getenv("DETECTOR", "yolo26")
DEFAULT_FACE_BACKEND = os.getenv("FACE_BACKEND") or None
DEVICE = os.getenv("DEVICE") or None
DEVICE_LABEL = os.getenv("DEVICE_LABEL") or None

app = FastAPI(title="BikeGuard inference", version="1.0")


def _device_label(detector) -> str:
    if DEVICE_LABEL:
        return DEVICE_LABEL
    return f"{os.uname().nodename}-{detector.device}"


@app.on_event("startup")
def _warmup() -> None:
    """Carrega o modelo no boot para o primeiro frame nao pagar o custo."""
    try:
        det = build_detector(DEFAULT_DETECTOR, device=DEVICE)
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        det.infer(blank, 0.5, 0.5, 640)
        log.info("detector %s pronto (%s)", det.name, det.device)
    except Exception as exc:  # noqa: BLE001
        log.warning("nao consegui pre-carregar o detector: %s", exc)
    try:
        engine = faces_mod.build_face_engine(DEFAULT_FACE_BACKEND, device=DEVICE or "cpu")
        log.info("backend de rosto: %s", engine.name)
    except Exception as exc:  # noqa: BLE001
        log.warning("backend de rosto indisponivel: %s", exc)


@app.get("/health")
def health():
    try:
        det = build_detector(DEFAULT_DETECTOR, device=DEVICE)
        return {"ok": True, "model": det.name, "device": _device_label(det)}
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})


@app.post("/infer")
async def infer(
    image: UploadFile = File(...),
    faces: bool = Query(True),
    detector: Optional[str] = Query(None, description="yolo26 | rfdetr"),
    bike_conf: float = Query(0.25),
    person_conf: float = Query(0.4),
    imgsz: int = Query(640),
    face_min_score: float = Query(0.5),
    face_min_px: float = Query(20.0),
):
    raw = await image.read()
    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse(status_code=400, content={"error": "imagem invalida"})

    t0 = time.perf_counter()
    det = build_detector(detector or DEFAULT_DETECTOR, device=DEVICE)
    bikes, persons = det.infer(frame, bike_conf, person_conf, imgsz)

    if faces and persons:
        try:
            engine = faces_mod.build_face_engine(DEFAULT_FACE_BACKEND, device=DEVICE or "cpu")
            faces_mod.attach_faces(frame, persons, engine, face_min_score, face_min_px)
        except Exception as exc:  # noqa: BLE001
            log.warning("sem rostos neste frame: %s", exc)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    h, w = frame.shape[:2]
    resp = InferResponse(
        model=det.name,
        device=_device_label(det),
        inference_ms=round(elapsed_ms, 1),
        width=w,
        height=h,
        bikes=bikes,
        persons=persons,
    )
    return resp.to_dict()
