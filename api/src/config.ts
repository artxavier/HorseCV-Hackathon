import { db } from "./db.js";

/** Config default -- CLAUDE.md §7. O agente busca isso em GET /api/config. */
export const DEFAULT_CONFIG = {
  mode: "edge" as "edge" | "fog" | "cloud",
  inference_urls: {
    edge: "http://localhost:8001",
    fog: "http://192.168.0.10:8001",
    cloud: "https://bikeguard.example.run.app",
  },
  // Medido nos videos de samples/: com os pesos COCO o yolo26n-seg so ve a bike em 55%
  // dos frames e a vaga nunca chega aos 70% da janela -- nenhum evento e emitido. Ate os
  // pesos com fine-tuning chegarem, o edge tambem roda rfdetr. (CLAUDE.md, Decisoes tomadas)
  detector: { edge: "rfdetr", fog: "rfdetr", cloud: "rfdetr" },
  // so para a grade do Dashboard; a verdade sobre as vagas esta em vision/config/slots.json
  slot_ids: ["S1", "S2", "S3", "S4", "S5", "S6"],
  target_fps: 3,
  jpeg_quality: 75,
  infer_width: 640,
  // Enquadramento de samples/: a cabeca de quem empurra a bike encosta no topo do frame e
  // as rodas vao ate ~95% da altura, entao nao sobra margem para cortar. Reduza a ROI se a
  // camera final for montada mais longe.
  roi: [0.0, 0.0, 1.0, 1.0],
  occupancy_threshold: 0.25,
  debounce_seconds: 3,
  face_window_seconds: 15,
  bike_min_conf: { yolo26: 0.25, rfdetr: 0.5 },
  person_min_conf: 0.4,
  occupied_ratio: 0.7,
  empty_ratio: 0.2,
  face_min_score: 0.5,
  face_min_px: 20,
  top_k: 5,
  // Vale para o par (template, buffalo_l), que e o default. Medido em samples/:
  // genuinos 0.525-0.710 x impostores 0.089-0.237. Com INSIGHTFACE_PACK=buffalo_s
  // (genuinos 0.371-0.510 x impostores 0.101-0.254) baixe para ~0.31. Recalibrar
  // sempre que trocar o pacote de modelos OU o agregador: a escala muda.
  similarity_threshold: 0.38,
  retention_hours: 24,
  timeout_ms: 2000,
};

export type Config = typeof DEFAULT_CONFIG & Record<string, unknown>;

export function getConfig(): Config {
  const row = db.prepare("SELECT json FROM config WHERE id = 1").get() as { json: string } | undefined;
  if (!row) return { ...DEFAULT_CONFIG };
  try {
    return { ...DEFAULT_CONFIG, ...(JSON.parse(row.json) as Record<string, unknown>) };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

export function saveConfig(patch: Record<string, unknown>): Config {
  const merged = { ...getConfig(), ...patch };
  db.prepare("INSERT INTO config (id, json) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET json = excluded.json")
    .run(JSON.stringify(merged));
  return merged;
}
