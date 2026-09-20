#!/usr/bin/env bash
# Baixa os pesos usados pelo BikeGuard (CLAUDE.md §4).
# Todos os pesos sao os pre-treinados de COCO -- sem fine-tuning.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS="$HERE/models"
PY="${PYTHON:-$HERE/.venv/bin/python}"
mkdir -p "$MODELS"

echo "==> YOLO26n-seg (detector padrao do modo edge)"
if [ ! -f "$MODELS/yolo26n-seg.pt" ]; then
  curl -fL --progress-bar -o "$MODELS/yolo26n-seg.pt" \
    https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n-seg.pt
else
  echo "    ja existe, pulando"
fi

echo "==> RF-DETR-Seg Nano (detector padrao do fog/cloud)"
# o pacote rfdetr baixa e valida o MD5 sozinho, em ~/.roboflow/models
"$PY" - <<'PY'
from rfdetr import RFDETRSegNano
RFDETRSegNano()
print("    ok")
PY

# buffalo_l e o padrao (INSIGHTFACE_PACK); buffalo_s fica como alternativa para CPU fraca.
for pack in ${INSIGHTFACE_PACKS:-buffalo_l buffalo_s}; do
  echo "==> InsightFace $pack"
  # baixa para ~/.insightface/models/$pack
  "$PY" -c "
import sys
from insightface.app import FaceAnalysis
app = FaceAnalysis(name=sys.argv[1], allowed_modules=['detection', 'recognition'])
app.prepare(ctx_id=-1, det_size=(640, 640))
print('    ok')
" "$pack"
  # os .onnx de landmark 3D / genderage nao sao usados -- fora daqui (licenca/espaco)
  BUFFALO="$HOME/.insightface/models/$pack"
  if [ -d "$BUFFALO" ]; then
    rm -f "$BUFFALO"/1k3d68.onnx "$BUFFALO"/2d106det.onnx "$BUFFALO"/genderage.onnx || true
  fi
done

echo "==> Fallback OpenCV (YuNet + SFace) -- usado se FACE_BACKEND=opencv"
ZOO=https://github.com/opencv/opencv_zoo/raw/main
for f in \
  "face_detection_yunet/face_detection_yunet_2023mar.onnx" \
  "face_recognition_sface/face_recognition_sface_2021dec.onnx"
do
  name="$(basename "$f")"
  if [ ! -f "$MODELS/$name" ]; then
    curl -fL --progress-bar -o "$MODELS/$name" "$ZOO/models/$f" || echo "    aviso: falhou $name"
  else
    echo "    $name ja existe, pulando"
  fi
done

echo "==> pronto. Conteudo de $MODELS:"
ls -la "$MODELS"
