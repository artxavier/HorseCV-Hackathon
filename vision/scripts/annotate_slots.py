"""Anota os poligonos das vagas e da zona de interacao sobre um frame da camera.

    python scripts/annotate_slots.py --source 0
    python scripts/annotate_slots.py --source samples/frame.jpg --out config/slots.json

Controles:
    clique esquerdo  adiciona um ponto no poligono atual
    n                fecha o poligono atual e comeca o proximo (vaga)
    i                alterna: vagas <-> zona de interacao
    z                desfaz o ultimo ponto
    r                reinicia tudo
    s                salva e sai
    q / ESC          sai sem salvar

Coordenadas salvas normalizadas [0..1] no FRAME CHEIO (CLAUDE.md §13).
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WINDOW = "annotate_slots"


def grab_frame(source: str):
    if not source.isdigit() and os.path.isfile(source) and source.lower().endswith(
        (".jpg", ".jpeg", ".png", ".bmp", ".webp")
    ):
        frame = cv2.imread(source)
        if frame is None:
            raise SystemExit(f"nao consegui ler a imagem {source}")
        return frame
    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not cap.isOpened():
        raise SystemExit(f"nao consegui abrir {source}")
    print("Posicione a cena e aperte ESPACO para congelar o frame.")
    frame = None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        cv2.imshow(WINDOW, f)
        key = cv2.waitKey(30) & 0xFF
        if key == 32:  # espaco
            frame = f.copy()
            break
        if key in (ord("q"), 27):
            break
    cap.release()
    if frame is None:
        raise SystemExit("nenhum frame capturado")
    return frame


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0")
    ap.add_argument("--out", default=os.path.join("config", "slots.json"))
    ap.add_argument("--camera", default="cam1")
    args = ap.parse_args()

    frame = grab_frame(args.source)
    h, w = frame.shape[:2]

    slots = []       # lista de poligonos fechados
    zone = []        # poligono da zona de interacao
    current = []
    editing_zone = False

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            current.append((x, y))

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)

    while True:
        canvas = frame.copy()
        for i, poly in enumerate(slots):
            pts = [(int(x), int(y)) for x, y in poly]
            cv2.polylines(canvas, [np.array(pts, dtype=np.int32)], True, (80, 200, 80), 2)
            cv2.putText(canvas, f"S{i+1}", (pts[0][0] + 4, pts[0][1] + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 200, 80), 2)
        if zone:
            cv2.polylines(canvas, [np.array(zone, dtype=np.int32)], True, (160, 120, 255), 2)
        for p in current:
            cv2.circle(canvas, p, 4, (0, 215, 255), -1)
        if len(current) > 1:
            cv2.polylines(canvas, [np.array(current, dtype=np.int32)], False, (0, 215, 255), 2)

        modo = "ZONA DE INTERACAO" if editing_zone else f"VAGA S{len(slots)+1}"
        cv2.rectangle(canvas, (0, 0), (w, 26), (20, 20, 20), -1)
        cv2.putText(canvas, f"{modo} | n=proximo  i=alterna  z=desfaz  r=reinicia  s=salvar  q=sair",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1)
        cv2.imshow(WINDOW, canvas)

        key = cv2.waitKey(20) & 0xFF
        if key == ord("n"):
            if len(current) >= 3:
                if editing_zone:
                    zone = list(current)
                else:
                    slots.append(list(current))
                current = []
            else:
                print("precisa de pelo menos 3 pontos")
        elif key == ord("i"):
            if len(current) >= 3:
                if editing_zone:
                    zone = list(current)
                else:
                    slots.append(list(current))
            current = []
            editing_zone = not editing_zone
        elif key == ord("z") and current:
            current.pop()
        elif key == ord("r"):
            slots, zone, current = [], [], []
        elif key == ord("s"):
            if len(current) >= 3:
                if editing_zone:
                    zone = list(current)
                else:
                    slots.append(list(current))
            break
        elif key in (ord("q"), 27):
            cv2.destroyAllWindows()
            raise SystemExit("saiu sem salvar")

    cv2.destroyAllWindows()
    if not slots:
        raise SystemExit("nenhuma vaga anotada")

    data = {
        "camera_id": args.camera,
        "slots": [
            {"id": f"S{i+1}", "polygon": [[round(x / w, 4), round(y / h, 4)] for x, y in poly]}
            for i, poly in enumerate(slots)
        ],
        "interaction_zone": [[round(x / w, 4), round(y / h, 4)] for x, y in zone],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    print(f"salvo em {args.out}: {len(slots)} vagas, zona com {len(zone)} pontos")


if __name__ == "__main__":
    main()
