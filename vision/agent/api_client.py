"""Cliente da api: config, eventos, metricas e frame anotado (CLAUDE.md §6 e §7).

Tudo aqui e best-effort: se a api estiver fora, o agente continua rodando com os
defaults e apenas loga. A demo nao pode morrer porque o laptop caiu do wifi.
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("api_client")

CONFIG_POLL_SECONDS = 5.0
METRICS_FLUSH_SECONDS = 5.0
FRAME_MIN_INTERVAL = 1.0

DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "edge",
    "inference_urls": {
        "edge": "http://localhost:8001",
        "fog": "http://192.168.0.10:8001",
        "cloud": "https://bikeguard.example.run.app",
    },
    "detector": {"edge": "yolo26", "fog": "rfdetr", "cloud": "rfdetr"},
    "target_fps": 3,
    "jpeg_quality": 75,
    "infer_width": 640,
    "roi": [0.0, 0.15, 1.0, 0.80],
    "occupancy_threshold": 0.25,
    "debounce_seconds": 3,
    "face_window_seconds": 15,
    "bike_min_conf": {"yolo26": 0.25, "rfdetr": 0.5},
    "person_min_conf": 0.4,
    "occupied_ratio": 0.7,
    "empty_ratio": 0.2,
    "face_min_score": 0.5,
    "face_min_px": 20,
    "top_k": 5,
    "similarity_threshold": 0.30,
    "retention_hours": 24,
    "timeout_ms": 2000,
}


class ApiClient:
    def __init__(self, base_url: str, camera_id: str = "cam1", timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.camera_id = camera_id
        self.timeout = timeout
        self.config: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))
        self.online = False
        self._last_config_poll = 0.0
        self._metrics: List[dict] = []
        self._last_flush = time.time()
        self._last_frame = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ config
    def poll_config(self, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        if not force and now - self._last_config_poll < CONFIG_POLL_SECONDS:
            return self.config
        self._last_config_poll = now
        try:
            r = requests.get(f"{self.base_url}/api/config", timeout=self.timeout)
            r.raise_for_status()
            remote = r.json()
            if isinstance(remote, dict):
                merged = json.loads(json.dumps(DEFAULT_CONFIG))
                merged.update(remote)
                self.config = merged
            if not self.online:
                log.info("api online em %s (modo=%s)", self.base_url, self.config.get("mode"))
            self.online = True
        except Exception as exc:  # noqa: BLE001
            if self.online or self._last_config_poll == now:
                log.warning("api offline (%s); usando a config atual", exc)
            self.online = False
        return self.config

    # ------------------------------------------------------------------ eventos
    def post_event(self, payload: dict) -> Optional[dict]:
        try:
            r = requests.post(f"{self.base_url}/api/events", json=payload, timeout=self.timeout * 3)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log.error("falha ao enviar evento %s: %s", payload.get("type"), exc)
            return None

    # ----------------------------------------------------------------- metricas
    def add_metric(self, metric: dict) -> None:
        with self._lock:
            metric.setdefault("camera_id", self.camera_id)
            metric.setdefault("ts", time.time())
            self._metrics.append(metric)
        self.maybe_flush_metrics()

    def maybe_flush_metrics(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_flush < METRICS_FLUSH_SECONDS:
            return
        with self._lock:
            batch, self._metrics = self._metrics, []
            self._last_flush = now
        if not batch:
            return
        try:
            requests.post(f"{self.base_url}/api/metrics", json={"metrics": batch}, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            log.debug("metricas nao enviadas: %s", exc)

    # -------------------------------------------------------------------- frame
    def post_frame(self, jpg: bytes, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_frame < FRAME_MIN_INTERVAL:
            return
        self._last_frame = now
        try:
            requests.post(
                f"{self.base_url}/api/cameras/{self.camera_id}/frame",
                data=jpg,
                headers={"Content-Type": "image/jpeg"},
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("frame nao enviado: %s", exc)


class InferenceClient:
    """Chama POST /infer. O mesmo contrato serve edge, fog e cloud (§5)."""

    def __init__(self, url: str, timeout_ms: int = 2000):
        self.url = url.rstrip("/")
        self.timeout = timeout_ms / 1000.0

    def infer(self, jpg: bytes, params: dict) -> dict:
        r = requests.post(
            f"{self.url}/infer",
            files={"image": ("frame.jpg", jpg, "image/jpeg")},
            params=params,
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()

    def health(self) -> Optional[dict]:
        try:
            r = requests.get(f"{self.url}/health", timeout=self.timeout)
            return r.json()
        except Exception:  # noqa: BLE001
            return None
