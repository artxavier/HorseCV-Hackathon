"""Calibra o limiar de similaridade facial (CLAUDE.md §10, passo 2b).

Entrada: uma pasta com uma subpasta por pessoa.

    samples/pessoas/
      ana/    foto1.jpg foto2.jpg ...
      bruno/  ...

Para cada imagem roda o pipeline real (detector de pessoa -> recorte da cabeca ->
upscale -> SCRFD -> embedding) e calcula o cosseno de todos os pares:
  - genuinos  = mesma pessoa
  - impostores = pessoas diferentes

Sai com os dois histogramas (o grafico vai para a apresentacao) e o limiar sugerido.

    python scripts/calibrate.py --dir samples/pessoas --out samples/calibracao.png
"""

import argparse
import itertools
import os
import sys
from typing import Dict, List

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inference import faces as faces_mod  # noqa: E402
from inference.detector import build_detector  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def embeddings_for_person(folder: str, detector, engine, min_score: float, min_px: float) -> List[np.ndarray]:
    out = []
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.splitext(name)[1].lower() not in IMG_EXT:
            continue
        img = cv2.imread(path)
        if img is None:
            continue
        _bikes, persons = detector.infer(img, 0.25, 0.4, 640)
        best = None
        for p in persons:
            face = faces_mod.best_face_for_person(img, p.bbox, engine, min_score, min_px, with_crop=False)
            if face and (best is None or face.quality > best.quality):
                best = face
        if best is None:
            print(f"  [sem rosto] {path}")
            continue
        out.append(np.asarray(best.embedding, dtype=np.float32))
        print(f"  [ok] {path} score={best.score:.2f}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="pasta com uma subpasta por pessoa")
    ap.add_argument("--out", default="calibracao.png")
    ap.add_argument("--detector", default="rfdetr", choices=["yolo26", "rfdetr"])
    ap.add_argument("--face-backend", default=None)
    ap.add_argument("--face-min-score", type=float, default=0.5)
    ap.add_argument("--face-min-px", type=float, default=20.0)
    args = ap.parse_args()

    detector = build_detector(args.detector)
    engine = faces_mod.build_face_engine(args.face_backend, device="cpu")
    print(f"detector={detector.name} rostos={engine.name}")

    people: Dict[str, List[np.ndarray]] = {}
    for person in sorted(os.listdir(args.dir)):
        folder = os.path.join(args.dir, person)
        if not os.path.isdir(folder):
            continue
        print(f"pessoa: {person}")
        embs = embeddings_for_person(folder, detector, engine, args.face_min_score, args.face_min_px)
        if embs:
            people[person] = embs

    if len(people) < 2:
        print("\nAVISO: com menos de 2 pessoas nao da para medir impostores -- o limiar fica um chute.")

    genuine, impostor = [], []
    for person, embs in people.items():
        for a, b in itertools.combinations(embs, 2):
            genuine.append(float(np.dot(a, b)))
    for (p1, e1), (p2, e2) in itertools.combinations(people.items(), 2):
        for a in e1:
            for b in e2:
                impostor.append(float(np.dot(a, b)))

    print(f"\npares genuinos:  {len(genuine)}")
    if genuine:
        print(f"  min={min(genuine):.3f} media={np.mean(genuine):.3f} max={max(genuine):.3f}")
    print(f"pares impostores: {len(impostor)}")
    if impostor:
        print(f"  min={min(impostor):.3f} media={np.mean(impostor):.3f} max={max(impostor):.3f}")

    threshold = suggest_threshold(genuine, impostor)
    if threshold is not None:
        print(f"\n>>> limiar sugerido (menor erro total): {threshold:.3f}")
        print("    coloque esse valor em similarity_threshold, na pagina de Configuracoes")

    plot(genuine, impostor, threshold, args.out)


def suggest_threshold(genuine, impostor):
    if not genuine:
        return None
    if not impostor:
        # sem impostores, fica a margem abaixo do pior genuino
        return max(0.0, min(genuine) - 0.05)
    best_t, best_err = None, 1e9
    for t in np.arange(0.0, 1.0, 0.01):
        fr = sum(1 for g in genuine if g < t) / len(genuine)      # falsa rejeicao
        fa = sum(1 for i in impostor if i >= t) / len(impostor)   # falsa aceitacao
        err = fr + fa
        if err < best_err:
            best_t, best_err = float(t), err
    return best_t


def plot(genuine, impostor, threshold, out_path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.figure(figsize=(8, 4.5))
    bins = np.linspace(-0.2, 1.0, 40)
    if genuine:
        plt.hist(genuine, bins=bins, alpha=0.65, label=f"mesma pessoa (n={len(genuine)})", color="#2a9d8f")
    if impostor:
        plt.hist(impostor, bins=bins, alpha=0.65, label=f"pessoas diferentes (n={len(impostor)})", color="#e76f51")
    if threshold is not None:
        plt.axvline(threshold, color="#264653", linestyle="--", label=f"limiar {threshold:.2f}")
    plt.xlabel("similaridade do cosseno")
    plt.ylabel("pares")
    plt.title("BikeGuard - calibracao do limiar facial")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    print(f"grafico salvo em {out_path}")


if __name__ == "__main__":
    main()
