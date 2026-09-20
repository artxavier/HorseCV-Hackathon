"""Deteccao de rosto + embedding (CLAUDE.md §4).

REGRA DE OURO: nunca rodar o detector de rosto no frame inteiro. Os rostos nessa
cena tem 20-45 px e o SCRFD redimensiona a entrada para 640. Pipeline obrigatorio:

    bbox da pessoa (detector) -> 45% superiores da bbox NO FRAME ORIGINAL
      -> upscale ate 640 no maior lado (INTER_CUBIC) -> detector de rosto -> embedding

Dois backends:
  - "insightface" (padrao): buffalo_s = SCRFD-500M + MobileFaceNet (512-d)
  - "opencv" (fallback):    YuNet + SFace do OpenCV Zoo (128-d)

Os dois devolvem embeddings L2-normalizados, entao o cosseno e so o produto interno.
"""

import base64
import logging
import os
from typing import List, Optional, Sequence

import cv2
import numpy as np

from common.schemas import Face, Person

log = logging.getLogger("faces")

HEAD_FRACTION = 0.45       # 45% superiores da bbox da pessoa
UPSCALE_TARGET = 640       # maior lado do recorte ampliado
MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "models"))


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #
class InsightFaceBackend:
    """Pacote de modelos escolhido por INSIGHTFACE_PACK.

    O padrao e buffalo_l (SCRFD-10G + ResNet50, 300 MB): nos videos de samples/ ele
    quase triplicou a margem entre a pessoa certa e a errada (+0.288 contra +0.117),
    ao custo de 101 ms/frame na GPU em vez de 45 ms. buffalo_s (SCRFD-500M +
    MobileFaceNet, 16 MB) fica como alternativa para CPU fraca -- e la o limiar cai
    de 0.38 para 0.31, porque trocar o pacote muda a escala do cosseno."""

    def __init__(self, device: str = "cpu"):
        from insightface.app import FaceAnalysis

        pack = os.getenv("INSIGHTFACE_PACK", "buffalo_l")
        self.name = f"insightface-{pack}"
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device != "cpu" else ["CPUExecutionProvider"]
        self.app = FaceAnalysis(
            name=pack,
            allowed_modules=["detection", "recognition"],
            providers=providers,
        )
        self.app.prepare(ctx_id=0 if device != "cpu" else -1, det_size=(UPSCALE_TARGET, UPSCALE_TARGET))

    def detect(self, crop_bgr: np.ndarray):
        out = []
        for f in self.app.get(crop_bgr):
            x1, y1, x2, y2 = [float(v) for v in f.bbox]
            emb = getattr(f, "normed_embedding", None)
            if emb is None:
                emb = f.embedding
            out.append(((x1, y1, x2 - x1, y2 - y1), float(f.det_score), np.asarray(emb, dtype=np.float32)))
        return out


class OpenCVBackend:
    """YuNet + SFace. Pesos em vision/models/ (scripts/download_models.sh)."""

    name = "opencv-yunet-sface"
    DET = "face_detection_yunet_2023mar.onnx"
    REC = "face_recognition_sface_2021dec.onnx"

    def __init__(self, device: str = "cpu"):
        det_path = os.path.join(MODELS_DIR, self.DET)
        rec_path = os.path.join(MODELS_DIR, self.REC)
        for p in (det_path, rec_path):
            if not os.path.exists(p):
                raise FileNotFoundError(f"peso ausente: {p} (rode scripts/download_models.sh)")
        self.detector = cv2.FaceDetectorYN.create(det_path, "", (UPSCALE_TARGET, UPSCALE_TARGET), 0.5, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(rec_path, "")

    def detect(self, crop_bgr: np.ndarray):
        h, w = crop_bgr.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(crop_bgr)
        out = []
        if faces is None:
            return out
        for row in faces:
            x, y, fw, fh = [float(v) for v in row[:4]]
            score = float(row[-1])
            aligned = self.recognizer.alignCrop(crop_bgr, row)
            emb = self.recognizer.feature(aligned).flatten().astype(np.float32)
            out.append(((x, y, fw, fh), score, emb))
        return out


_BACKENDS = {"insightface": InsightFaceBackend, "opencv": OpenCVBackend}
_cache: dict = {}


def build_face_engine(backend: Optional[str] = None, device: str = "cpu"):
    """Constroi (com cache) o backend de rosto; cai para o opencv se o outro falhar."""
    backend = backend or os.getenv("FACE_BACKEND") or "insightface"
    key = (backend, device)
    if key in _cache:
        return _cache[key]
    try:
        engine = _BACKENDS[backend](device=device)
    except Exception as exc:  # noqa: BLE001
        if backend == "insightface":
            log.warning("insightface indisponivel (%s); caindo para o backend opencv", exc)
            engine = _BACKENDS["opencv"](device=device)
        else:
            raise
    _cache[key] = engine
    return engine


# --------------------------------------------------------------------------- #
# pipeline
# --------------------------------------------------------------------------- #
def _l2(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _head_crop(frame_bgr: np.ndarray, bbox: Sequence[float]):
    """45% superiores da bbox da pessoa, no frame em resolucao original."""
    h, w = frame_bgr.shape[:2]
    x1 = int(max(0, np.floor(bbox[0])))
    y1 = int(max(0, np.floor(bbox[1])))
    x2 = int(min(w, np.ceil(bbox[2])))
    y2 = int(min(h, np.ceil(bbox[3])))
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None, (0, 0), 1.0
    y2 = y1 + max(8, int((y2 - y1) * HEAD_FRACTION))
    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None, (0, 0), 1.0
    ch, cw = crop.shape[:2]
    scale = UPSCALE_TARGET / max(ch, cw)
    if scale > 1.0:
        crop = cv2.resize(crop, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_CUBIC)
    else:
        scale = 1.0
    return crop, (x1, y1), scale


def _encode_jpg(img: np.ndarray, quality: int = 85) -> str:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def best_face_for_person(
    frame_bgr: np.ndarray,
    person_bbox: Sequence[float],
    engine,
    min_score: float = 0.5,
    min_px: float = 20.0,
    with_crop: bool = True,
) -> Optional[Face]:
    """Melhor rosto dentro da bbox de uma pessoa, em coordenadas do frame enviado."""
    crop, (ox, oy), scale = _head_crop(frame_bgr, person_bbox)
    if crop is None:
        return None
    try:
        found = engine.detect(crop)
    except Exception as exc:  # noqa: BLE001
        log.warning("falha no detector de rosto: %s", exc)
        return None

    best = None
    for (fx, fy, fw, fh), score, emb in found:
        if score < min_score:
            continue
        # lado do rosto medido NO FRAME ORIGINAL (§4)
        side_original = max(fw, fh) / scale
        if side_original < min_px:
            continue
        rank = score * min(side_original, 112.0)
        if best is None or rank > best[0]:
            best = (rank, (fx, fy, fw, fh), score, emb, side_original)

    if best is None:
        return None

    _, (fx, fy, fw, fh), score, emb, _side = best
    face_crop_b64 = None
    if with_crop:
        pad = 0.25
        cx1 = int(max(0, fx - fw * pad))
        cy1 = int(max(0, fy - fh * pad))
        cx2 = int(min(crop.shape[1], fx + fw * (1 + pad)))
        cy2 = int(min(crop.shape[0], fy + fh * (1 + pad)))
        piece = crop[cy1:cy2, cx1:cx2]
        if piece.size > 0:
            face_crop_b64 = _encode_jpg(piece)

    return Face(
        bbox=[ox + fx / scale, oy + fy / scale, fw / scale, fh / scale],
        score=float(score),
        embedding=[float(v) for v in _l2(np.asarray(emb, dtype=np.float32))],
        crop_jpg_b64=face_crop_b64,
    )


def attach_faces(
    frame_bgr: np.ndarray,
    persons: List[Person],
    engine,
    min_score: float = 0.5,
    min_px: float = 20.0,
) -> None:
    """Preenche `person.face` in-place para cada pessoa detectada."""
    for p in persons:
        p.face = best_face_for_person(frame_bgr, p.bbox, engine, min_score, min_px)
