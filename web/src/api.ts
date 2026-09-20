import { useCallback, useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------- tipos
export interface Session {
  id: string;
  camera_id: string;
  slot_id: string;
  deposit_ts: number;
  withdrawal_ts: number | null;
  similarity: number | null;
  status: "parked" | "ok" | "alert" | "orphan";
  deposit_face_url: string | null;
  deposit_frame_url: string | null;
  withdrawal_face_url: string | null;
  withdrawal_frame_url: string | null;
}

export interface Alert {
  id: string;
  session_id: string;
  ts: number;
  reason: "low_similarity" | "no_face_deposit" | "no_face_withdrawal";
  similarity: number | null;
  acknowledged: boolean;
  session: Session | null;
}

export interface SlotState {
  slot_id: string;
  state: "occupied" | "alert";
  session: Session | null;
}

export interface EventRow {
  id: number;
  ts: number;
  camera_id: string;
  slot_id: string | null;
  type: string;
  payload: string | null;
}

export interface MetricRow {
  id: number;
  ts: number;
  camera_id: string;
  mode: string;
  inference_ms: number | null;
  rtt_ms: number | null;
  payload_bytes: number | null;
  fallback: number;
}

export interface MetricSummary {
  mode: string;
  frames: number;
  avg_inference_ms: number | null;
  avg_rtt_ms: number | null;
  avg_payload_bytes: number | null;
  total_bytes: number | null;
  fallback_pct: number | null;
  first_ts: number | null;
  last_ts: number | null;
}

export type Mode = "edge" | "fog" | "cloud";

export interface Config {
  mode: Mode;
  inference_urls: Record<Mode, string>;
  detector: Record<Mode, string>;
  slot_ids: string[];
  target_fps: number;
  jpeg_quality: number;
  infer_width: number;
  roi: number[];
  occupancy_threshold: number;
  debounce_seconds: number;
  face_window_seconds: number;
  bike_min_conf: Record<string, number>;
  person_min_conf: number;
  occupied_ratio: number;
  empty_ratio: number;
  face_min_score: number;
  face_min_px: number;
  top_k: number;
  similarity_threshold: number;
  retention_hours: number;
  timeout_ms: number;
  [key: string]: unknown;
}

// ---------------------------------------------------------------- fetch
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const api = {
  config: () => request<Config>("/api/config"),
  saveConfig: (patch: Partial<Config>) =>
    request<Config>("/api/config", { method: "PUT", body: JSON.stringify(patch) }),
  slots: (cameraId = "cam1") => request<SlotState[]>(`/api/slots?camera_id=${cameraId}`),
  sessions: (status?: string) =>
    request<Session[]>(`/api/sessions${status ? `?status=${status}` : ""}`),
  alerts: (openOnly = true) => request<Alert[]>(`/api/alerts${openOnly ? "?open=1" : ""}`),
  ackAlert: (id: string) => request<{ ok: boolean }>(`/api/alerts/${id}/ack`, { method: "POST" }),
  events: (limit = 100) => request<EventRow[]>(`/api/events?limit=${limit}`),
  metrics: (sinceSeconds = 600) =>
    request<{ rows: MetricRow[]; summary: MetricSummary[] }>(
      `/api/metrics?since=${Date.now() / 1000 - sinceSeconds}`,
    ),
};

// ---------------------------------------------------------------- polling
/** Sem WebSocket: o dashboard so faz polling a cada 1-2 s (CLAUDE.md §8). */
export function usePolling<T>(fn: () => Promise<T>, intervalMs = 1500) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const refresh = useCallback(async () => {
    try {
      setData(await fnRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (alive) await refresh();
    };
    void tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs, refresh]);

  return { data, error, refresh };
}

// ---------------------------------------------------------------- formato
export function fmtTime(ts: number | null | undefined): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleTimeString("pt-BR");
}

export function fmtDateTime(ts: number | null | undefined): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("pt-BR");
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "-";
  if (n < 1024) return `${Math.round(n)} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export const REASON_LABEL: Record<string, string> = {
  low_similarity: "rostos diferentes",
  no_face_deposit: "sem rosto no deposito",
  no_face_withdrawal: "sem rosto na retirada",
};
