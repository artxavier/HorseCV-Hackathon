import type { FastifyInstance } from "fastify";
import { db } from "../db.js";

interface Metric {
  ts?: number;
  camera_id?: string;
  mode?: string;
  inference_ms?: number;
  rtt_ms?: number;
  payload_bytes?: number;
  fallback?: number | boolean;
}

const insert = db.prepare(
  `INSERT INTO metrics (ts, camera_id, mode, inference_ms, rtt_ms, payload_bytes, fallback)
   VALUES (?, ?, ?, ?, ?, ?, ?)`,
);

export default async function metrics(app: FastifyInstance): Promise<void> {
  /** O agente manda em lote a cada 5 s (§6). Aceita um objeto ou {metrics: [...]}. */
  app.post("/api/metrics", async (req) => {
    const body = req.body as { metrics?: Metric[] } | Metric;
    const batch: Metric[] = Array.isArray((body as { metrics?: Metric[] })?.metrics)
      ? (body as { metrics: Metric[] }).metrics
      : [body as Metric];

    const now = Date.now() / 1000;
    const insertMany = db.transaction((rows: Metric[]) => {
      for (const m of rows) {
        insert.run(
          m.ts ?? now,
          m.camera_id ?? "cam1",
          m.mode ?? "edge",
          m.inference_ms ?? null,
          m.rtt_ms ?? null,
          m.payload_bytes ?? null,
          m.fallback ? 1 : 0,
        );
      }
    });
    insertMany(batch);
    return { ok: true, saved: batch.length };
  });

  app.get("/api/metrics", async (req) => {
    const { since, limit = "500" } = req.query as { since?: string; limit?: string };
    const cutoff = since ? Number(since) : Date.now() / 1000 - 600;
    const rows = db
      .prepare("SELECT * FROM metrics WHERE ts >= ? ORDER BY ts DESC LIMIT ?")
      .all(cutoff, Math.min(Number(limit) || 500, 5000));

    const summary = db
      .prepare(
        `SELECT mode,
                COUNT(*)              AS frames,
                AVG(inference_ms)     AS avg_inference_ms,
                AVG(rtt_ms)           AS avg_rtt_ms,
                AVG(payload_bytes)    AS avg_payload_bytes,
                SUM(payload_bytes)    AS total_bytes,
                AVG(fallback) * 100.0 AS fallback_pct
           FROM metrics WHERE ts >= ? GROUP BY mode`,
      )
      .all(cutoff);

    return { rows: (rows as unknown[]).reverse(), summary };
  });
}
