import type { FastifyInstance } from "fastify";
import { db, type SessionRow } from "../db.js";
import { fileUrl } from "../images.js";

export function toPublicSession(s: SessionRow) {
  return {
    id: s.id,
    camera_id: s.camera_id,
    slot_id: s.slot_id,
    deposit_ts: s.deposit_ts,
    withdrawal_ts: s.withdrawal_ts,
    similarity: s.similarity,
    status: s.status,
    deposit_face_url: fileUrl(s.deposit_face),
    deposit_frame_url: fileUrl(s.deposit_frame),
    withdrawal_face_url: fileUrl(s.withdrawal_face),
    withdrawal_frame_url: fileUrl(s.withdrawal_frame),
    // deposit_embeddings nunca sai da api (LGPD, §12)
  };
}

export default async function sessions(app: FastifyInstance): Promise<void> {
  app.get("/api/sessions", async (req) => {
    const { status, limit = "100", camera_id } = req.query as {
      status?: string;
      limit?: string;
      camera_id?: string;
    };
    const where: string[] = [];
    const params: unknown[] = [];
    if (status) {
      where.push("status = ?");
      params.push(status);
    }
    if (camera_id) {
      where.push("camera_id = ?");
      params.push(camera_id);
    }
    const sql = `SELECT * FROM sessions ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
                 ORDER BY COALESCE(withdrawal_ts, deposit_ts) DESC LIMIT ?`;
    params.push(Math.min(Number(limit) || 100, 500));
    return (db.prepare(sql).all(...params) as SessionRow[]).map(toPublicSession);
  });

  /** Estado atual por vaga, derivado das sessoes: o Dashboard pinta a grade com isso. */
  app.get("/api/slots", async (req) => {
    const { camera_id = "cam1" } = req.query as { camera_id?: string };

    const parked = db
      .prepare("SELECT * FROM sessions WHERE camera_id = ? AND status = 'parked'")
      .all(camera_id) as SessionRow[];

    const alerting = db
      .prepare(
        `SELECT s.* FROM sessions s
           JOIN alerts a ON a.session_id = s.id
          WHERE s.camera_id = ? AND a.acknowledged = 0`,
      )
      .all(camera_id) as SessionRow[];

    const bySlot = new Map<string, { slot_id: string; state: string; session: ReturnType<typeof toPublicSession> | null }>();
    for (const s of parked) {
      bySlot.set(s.slot_id, { slot_id: s.slot_id, state: "occupied", session: toPublicSession(s) });
    }
    for (const s of alerting) {
      bySlot.set(s.slot_id, { slot_id: s.slot_id, state: "alert", session: toPublicSession(s) });
    }
    return [...bySlot.values()].sort((a, b) => a.slot_id.localeCompare(b.slot_id));
  });
}
