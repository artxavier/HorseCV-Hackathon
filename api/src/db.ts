import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
export const DATA_DIR = resolve(process.env.DATA_DIR ?? join(here, "..", "data"));
export const FACES_DIR = join(DATA_DIR, "faces");
export const FRAMES_DIR = join(DATA_DIR, "frames");

mkdirSync(FACES_DIR, { recursive: true });
mkdirSync(FRAMES_DIR, { recursive: true });

export const db = new Database(join(DATA_DIR, "bikeguard.db"));
db.pragma("journal_mode = WAL");

db.exec(`
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  camera_id TEXT NOT NULL,
  slot_id TEXT NOT NULL,
  deposit_ts REAL NOT NULL,
  deposit_embeddings TEXT,          -- JSON number[][]; apagado apos a comparacao (LGPD)
  deposit_face TEXT,
  deposit_frame TEXT,
  withdrawal_ts REAL,
  withdrawal_face TEXT,
  withdrawal_frame TEXT,
  similarity REAL,
  status TEXT NOT NULL              -- parked | ok | alert
);

CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  ts REAL NOT NULL,
  reason TEXT NOT NULL,             -- low_similarity | no_face_deposit | no_face_withdrawal
  similarity REAL,
  acknowledged INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  camera_id TEXT NOT NULL,
  slot_id TEXT,
  type TEXT NOT NULL,
  payload TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  camera_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  inference_ms REAL,
  rtt_ms REAL,
  payload_bytes INTEGER,
  fallback INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_slot ON sessions (camera_id, slot_id, status);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts (acknowledged, ts);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics (ts);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);
`);

export interface SessionRow {
  id: string;
  camera_id: string;
  slot_id: string;
  deposit_ts: number;
  deposit_embeddings: string | null;
  deposit_face: string | null;
  deposit_frame: string | null;
  withdrawal_ts: number | null;
  withdrawal_face: string | null;
  withdrawal_frame: string | null;
  similarity: number | null;
  status: "parked" | "ok" | "alert";
}

export interface AlertRow {
  id: string;
  session_id: string;
  ts: number;
  reason: string;
  similarity: number | null;
  acknowledged: number;
}
