"""Agente BikeGuard: captura -> /infer -> ocupacao -> maquina de estados -> eventos.

Roda sempre no dispositivo (Pi/Jetson). So a INFERENCIA muda de lugar conforme o
modo configurado no site (edge / fog / cloud) -- CLAUDE.md §2.

    python -m agent.main --source demo.mp4 --api http://localhost:3000 --camera cam1
    python -m agent.main --source 0 --show
"""

import argparse
import base64
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import cv2

from agent import draw as draw_mod
from agent.api_client import ApiClient, InferenceClient
from agent.face_buffer import FaceBuffer, link_faces_to_slots
from agent.occupancy import build_slots, load_slots, raw_occupancy
from agent.slots_state import OCCUPIED, SlotStateMachine
from common.geometry import crop_roi
from common.schemas import response_from_dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("agent")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SLOTS = os.path.join(HERE, "config", "slots.json")


def open_source(source: str):
    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not cap.isOpened():
        raise SystemExit(f"nao consegui abrir a fonte de video: {source}")
    return cap


def offset_detections(resp, ox: int, oy: int) -> None:
    """Deteccoes voltam da ROI para as coordenadas do frame cheio."""
    if ox == 0 and oy == 0:
        return
    for b in resp.bikes:
        b.bbox = [b.bbox[0] + ox, b.bbox[1] + oy, b.bbox[2] + ox, b.bbox[3] + oy]
        if b.polygon:
            b.polygon = [[p[0] + ox, p[1] + oy] for p in b.polygon]
    for p in resp.persons:
        p.bbox = [p.bbox[0] + ox, p.bbox[1] + oy, p.bbox[2] + ox, p.bbox[3] + oy]
        if p.face is not None:
            f = p.face
            f.bbox = [f.bbox[0] + ox, f.bbox[1] + oy, f.bbox[2], f.bbox[3]]


def infer_params(cfg: dict, mode: str) -> dict:
    detector = (cfg.get("detector") or {}).get(mode, "yolo26")
    bike_conf = (cfg.get("bike_min_conf") or {}).get(detector, 0.25)
    return {
        "faces": "true",
        "detector": detector,
        "bike_conf": bike_conf,
        "person_conf": cfg.get("person_min_conf", 0.4),
        "imgsz": cfg.get("infer_width", 640),
        "face_min_score": cfg.get("face_min_score", 0.5),
        "face_min_px": cfg.get("face_min_px", 20),
    }


def run(args: argparse.Namespace) -> None:
    api = ApiClient(args.api, camera_id=args.camera) if args.api else None
    cfg = api.poll_config(force=True) if api else dict()
    if not cfg:
        from agent.api_client import DEFAULT_CONFIG

        cfg = dict(DEFAULT_CONFIG)

    slots_raw = load_slots(args.slots)
    cap = open_source(args.source)

    state: Optional[SlotStateMachine] = None
    slots_cfg = None
    frame_size = (0, 0)
    faces = FaceBuffer(window_seconds=float(cfg.get("face_window_seconds", 15)))
    frame_idx = 0
    fps_ema = 0.0
    last_loop = time.time()

    log.info("agente iniciado | fonte=%s | api=%s | vagas=%s", args.source, args.api or "off", args.slots)

    while True:
        ok, frame = cap.read()
        if not ok:
            if args.source.isdigit():
                log.error("camera parou de entregar frames")
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # video em loop (plano B da demo)
            continue

        now = time.time()
        frame_idx += 1
        if api:
            cfg = api.poll_config()

        h, w = frame.shape[:2]
        if slots_cfg is None or frame_size != (w, h):
            frame_size = (w, h)
            slots_cfg = build_slots(slots_raw, w, h)
        if state is None:
            state = SlotStateMachine(
                [s.id for s in slots_cfg.slots],
                debounce_seconds=float(cfg.get("debounce_seconds", 3)),
                occupied_ratio=float(cfg.get("occupied_ratio", 0.7)),
                empty_ratio=float(cfg.get("empty_ratio", 0.2)),
            )

        # ---- ROI em resolucao nativa (§5): mais pixels em rostos e bikes de graca
        roi_frame, (ox, oy) = crop_roi(frame, cfg.get("roi"))
        jpg = draw_mod.encode_jpg(roi_frame, cfg.get("jpeg_quality", 75))
        if jpg is None:
            continue

        mode = cfg.get("mode", "edge")
        urls = cfg.get("inference_urls", {})
        url = args.edge_url if mode == "edge" and args.edge_url else urls.get(mode) or args.edge_url
        params = infer_params(cfg, mode)
        timeout_ms = int(cfg.get("timeout_ms", 2000))

        t0 = time.perf_counter()
        fallback = False
        data = None
        try:
            data = InferenceClient(url, timeout_ms).infer(jpg, params)
        except Exception as exc:  # noqa: BLE001
            edge_url = args.edge_url or urls.get("edge")
            if mode != "edge" and edge_url:
                log.warning("modo %s falhou (%s); caindo para o edge neste frame", mode, exc)
                fallback = True
                try:
                    data = InferenceClient(edge_url, max(timeout_ms, 5000)).infer(
                        jpg, infer_params(cfg, "edge")
                    )
                except Exception as exc2:  # noqa: BLE001
                    log.error("fallback edge tambem falhou: %s", exc2)
            else:
                log.error("inferencia falhou: %s", exc)
        rtt_ms = (time.perf_counter() - t0) * 1000.0

        if data is None:
            time.sleep(0.2)
            continue

        resp = response_from_dict(data)
        offset_detections(resp, ox, oy)

        # ---- ocupacao + debounce com histerese
        raw, coverage = raw_occupancy(
            slots_cfg.slots, resp.bikes, (w, h), float(cfg.get("occupancy_threshold", 0.25))
        )
        transitions = state.update(now, raw)

        # ---- ring buffer de rostos
        faces.window_seconds = float(cfg.get("face_window_seconds", 15))
        for slot_id, face in link_faces_to_slots(
            resp.persons, slots_cfg.slots, slots_cfg.interaction_zone_px
        ):
            faces.add(now, slot_id, face)
        faces.prune(now)

        # ---- eventos
        for tr in transitions:
            emit_event(api, args, cfg, faces, tr, frame, now)

        # ---- frame anotado (1/s) + metricas
        occupied_n = sum(1 for v in state.snapshot().values() if v == OCCUPIED)
        dt = now - last_loop
        last_loop = now
        fps_ema = (1.0 / dt) if fps_ema == 0 and dt > 0 else (fps_ema * 0.8 + (1.0 / dt) * 0.2 if dt > 0 else fps_ema)
        header = (
            f"modo={mode}{'(fallback)' if fallback else ''} det={resp.model} "
            f"infer={resp.inference_ms:.0f}ms rtt={rtt_ms:.0f}ms fps={fps_ema:.1f} "
            f"ocupadas={occupied_n}/{len(slots_cfg.slots)}"
        )
        annotated = draw_mod.draw_overlay(
            frame, slots_cfg.slots, state.snapshot(), resp.bikes, resp.persons,
            coverage=coverage, interaction_zone_px=slots_cfg.interaction_zone_px, header=header,
        )
        if api:
            frame_jpg = draw_mod.encode_jpg(annotated, cfg.get("jpeg_quality", 75))
            if frame_jpg:
                api.post_frame(frame_jpg)
            api.add_metric({
                "mode": "edge" if fallback else mode,
                "inference_ms": resp.inference_ms,
                "rtt_ms": round(rtt_ms, 1),
                "payload_bytes": len(jpg),
                "fallback": 1 if fallback else 0,
            })
        if args.show:
            cv2.imshow("BikeGuard", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        if frame_idx % 30 == 0:
            log.info(header)

        # ---- ritmo alvo
        target_fps = float(cfg.get("target_fps", 3)) or 3.0
        sleep_for = (1.0 / target_fps) - (time.time() - now)
        if sleep_for > 0:
            time.sleep(sleep_for)

    cap.release()
    if args.show:
        cv2.destroyAllWindows()
    if api:
        api.maybe_flush_metrics(force=True)


def emit_event(api, args, cfg: dict, faces: FaceBuffer, tr, frame, now: float) -> None:
    """Monta e envia o evento de deposito/retirada da vaga."""
    top_k = int(cfg.get("top_k", 5))
    since = now - float(cfg.get("face_window_seconds", 15))
    records = faces.best(tr.slot_id, since, top_k)

    payload: Dict[str, object] = {
        "type": tr.kind,
        "camera_id": args.camera,
        "slot_id": tr.slot_id,
        "ts": tr.ts,
        "embeddings": [r.embedding for r in records],
        "face_jpg_b64": records[0].crop_jpg_b64 if records else None,
        "frame_jpg_b64": _b64_frame(frame, cfg.get("jpeg_quality", 75)),
    }
    log.info(
        "[%s] vaga=%s rostos=%d (melhor score=%s) ratio=%.2f",
        tr.kind.upper(), tr.slot_id, len(records),
        f"{records[0].score:.2f}" if records else "-", tr.ratio,
    )
    faces.clear(tr.slot_id)
    if api:
        result = api.post_event(payload)
        if result:
            log.info("    api -> %s", {k: v for k, v in result.items() if k != "session"})


def _b64_frame(frame, quality: int) -> Optional[str]:
    jpg = draw_mod.encode_jpg(frame, quality)
    return base64.b64encode(jpg).decode("ascii") if jpg else None


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Agente BikeGuard")
    ap.add_argument("--source", default="0", help="indice da webcam (0) ou caminho do video")
    ap.add_argument("--api", default="http://localhost:3000", help="url da api ('' desliga)")
    ap.add_argument("--camera", default="cam1")
    ap.add_argument("--slots", default=DEFAULT_SLOTS)
    ap.add_argument("--edge-url", default="http://localhost:8001", help="servidor de inferencia local")
    ap.add_argument("--show", action="store_true", help="abre uma janela com o overlay")
    args = ap.parse_args(argv)
    try:
        run(args)
    except KeyboardInterrupt:
        log.info("encerrando")


if __name__ == "__main__":
    sys.exit(main())
