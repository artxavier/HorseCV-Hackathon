"""Detector plugavel de pessoas e bicicletas (CLAUDE.md §4).

Dois backends com a mesma saida:
  - "yolo26"  -> Ultralytics YOLO26n-seg  (padrao no edge; rapido, erra mais bikes)
  - "rfdetr"  -> RF-DETR-Seg Nano         (padrao no fog/cloud; 5x mais lento, bem melhor)

Os pesos sao os pre-treinados de COCO (person=0, bicycle=1 no indice do YOLO).
Quando os pesos com fine-tuning chegarem, basta apontar `model_path` para o novo
.pt -- nada mais no pipeline muda.
"""

import logging
import os
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from common.schemas import Bike, Person

log = logging.getLogger("detector")

# nomes COCO que nos interessam
PERSON = "person"
BICYCLE = "bicycle"

# poligono devolvido ao agente: simplificado para o JSON nao explodir
POLY_EPSILON_RATIO = 0.01
POLY_MAX_POINTS = 40


def _mask_to_polygon(mask: np.ndarray) -> Optional[List[List[float]]]:
    """Maior contorno externo de uma mascara binaria -> poligono simplificado."""
    if mask is None:
        return None
    m = (mask > 0).astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    return _simplify(contour)


def _simplify(contour: np.ndarray) -> Optional[List[List[float]]]:
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, POLY_EPSILON_RATIO * peri, True)
    pts = approx.reshape(-1, 2)
    if len(pts) < 3:
        return None
    if len(pts) > POLY_MAX_POINTS:
        idx = np.linspace(0, len(pts) - 1, POLY_MAX_POINTS).astype(int)
        pts = pts[idx]
    return [[float(x), float(y)] for x, y in pts]


def _pick_device(device: Optional[str]) -> str:
    if device:
        return device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: BLE001 - torch pode nem existir no Pi
        pass
    return "cpu"


class BaseDetector:
    name = "base"
    device = "cpu"

    def infer(
        self,
        frame_bgr: np.ndarray,
        bike_conf: float,
        person_conf: float,
        imgsz: int,
    ) -> Tuple[List[Bike], List[Person]]:
        raise NotImplementedError


MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"))


class YoloDetector(BaseDetector):
    """Ultralytics YOLO26n-seg. Usa `masks` se o modelo for -seg, senao a bbox.

    Para usar os pesos com fine-tuning: aponte YOLO_WEIGHTS (ou o `model_path` da
    config) para o novo .pt. Nada mais no pipeline muda.
    """

    DEFAULT_WEIGHTS = "yolo26n-seg.pt"

    @classmethod
    def _default_weights(cls) -> str:
        local = os.path.join(MODELS_DIR, cls.DEFAULT_WEIGHTS)
        # se nao estiver em models/, o ultralytics baixa sozinho
        return local if os.path.exists(local) else cls.DEFAULT_WEIGHTS

    def __init__(self, model_path: Optional[str] = None, device: Optional[str] = None):
        from ultralytics import YOLO

        weights = model_path or os.getenv("YOLO_WEIGHTS") or self._default_weights()
        self.device = _pick_device(device)
        self.model = YOLO(weights)
        self.name = os.path.basename(str(weights)).replace(".pt", "")
        # indice -> nome, para nao depender de person=0/bicycle=1 apos um fine-tuning
        names = self.model.names
        self._names = {int(k): str(v) for k, v in (names.items() if isinstance(names, dict) else enumerate(names))}
        self._wanted = {i for i, n in self._names.items() if n in (PERSON, BICYCLE)}
        log.info("YOLO %s em %s (classes %s)", weights, self.device, sorted(self._wanted))

    def infer(self, frame_bgr, bike_conf, person_conf, imgsz):
        conf = max(0.01, min(bike_conf, person_conf))
        results = self.model.predict(
            source=frame_bgr,
            classes=sorted(self._wanted) or None,
            conf=conf,
            imgsz=imgsz,
            device=self.device,
            verbose=False,
        )
        bikes: List[Bike] = []
        persons: List[Person] = []
        if not results:
            return bikes, persons
        r = results[0]
        if r.boxes is None:
            return bikes, persons

        polys = None
        if getattr(r, "masks", None) is not None and r.masks is not None:
            # masks.xy ja vem nas coordenadas do frame original
            polys = [np.asarray(p, dtype=np.float32) for p in r.masks.xy]

        for i, box in enumerate(r.boxes):
            cls = int(box.cls.item())
            score = float(box.conf.item())
            label = self._names.get(cls, str(cls))
            xyxy = [float(v) for v in box.xyxy[0].tolist()]
            if label == BICYCLE and score >= bike_conf:
                polygon = None
                if polys is not None and i < len(polys) and len(polys[i]) >= 3:
                    polygon = _simplify(polys[i].reshape(-1, 1, 2).astype(np.int32))
                bikes.append(Bike(bbox=xyxy, conf=score, polygon=polygon))
            elif label == PERSON and score >= person_conf:
                persons.append(Person(bbox=xyxy, conf=score))
        return bikes, persons


class RFDetrDetector(BaseDetector):
    """RF-DETR-Seg Nano (pacote `rfdetr`). Baixa os pesos no primeiro uso."""

    def __init__(self, model_path: Optional[str] = None, device: Optional[str] = None):
        self.device = _pick_device(device)
        model_cls = self._load_class()
        kwargs = {}
        if model_path:
            kwargs["pretrain_weights"] = model_path
        self.model = model_cls(**kwargs)
        self.name = "rfdetr-seg-nano"
        self._names = self._class_names()
        log.info("RF-DETR-Seg Nano em %s", self.device)

    @staticmethod
    def _load_class():
        import rfdetr

        for attr in ("RFDETRSegNano", "RFDETRSegSmall", "RFDETRSegPreview"):
            if hasattr(rfdetr, attr):
                return getattr(rfdetr, attr)
        raise RuntimeError("pacote rfdetr sem classe de segmentacao conhecida")

    def _class_names(self):
        """Mapa class_id -> nome COCO.

        Verificado no rfdetr 1.10.1: `predict` devolve class_id 1-indexado em
        relacao a `model.class_names` (person=1, bicycle=2).
        """
        names = list(getattr(self.model, "class_names", []) or [])
        if names:
            return {i + 1: str(n) for i, n in enumerate(names)}
        return {1: PERSON, 2: BICYCLE}

    def infer(self, frame_bgr, bike_conf, person_conf, imgsz):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        threshold = max(0.01, min(bike_conf, person_conf))
        det = self.model.predict(rgb, threshold=threshold)

        bikes: List[Bike] = []
        persons: List[Person] = []
        xyxy = getattr(det, "xyxy", None)
        if xyxy is None or len(xyxy) == 0:
            return bikes, persons
        confs = getattr(det, "confidence", None)
        class_ids = getattr(det, "class_id", None)
        masks = getattr(det, "mask", None)

        for i in range(len(xyxy)):
            score = float(confs[i]) if confs is not None else 1.0
            cls = int(class_ids[i]) if class_ids is not None else -1
            label = self._names.get(cls, "")
            box = [float(v) for v in xyxy[i]]
            if label == BICYCLE and score >= bike_conf:
                polygon = _mask_to_polygon(masks[i]) if masks is not None else None
                bikes.append(Bike(bbox=box, conf=score, polygon=polygon))
            elif label == PERSON and score >= person_conf:
                persons.append(Person(bbox=box, conf=score))
        return bikes, persons


_BACKENDS = {"yolo26": YoloDetector, "rfdetr": RFDetrDetector}
_cache: dict = {}


def build_detector(
    name: str = "yolo26",
    model_path: Optional[str] = None,
    device: Optional[str] = None,
) -> BaseDetector:
    """Fabrica com cache -- carregar o modelo custa segundos, nao repetir por request."""
    key = (name, model_path, device)
    if key in _cache:
        return _cache[key]
    if name not in _BACKENDS:
        raise ValueError(f"detector desconhecido: {name} (use {sorted(_BACKENDS)})")
    det = _BACKENDS[name](model_path=model_path, device=device)
    _cache[key] = det
    return det


def available_backends() -> Sequence[str]:
    return sorted(_BACKENDS)
