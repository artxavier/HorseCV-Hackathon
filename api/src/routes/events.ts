import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { getConfig } from "../config.js";
import { db, type SessionRow } from "../db.js";
import { deleteFile, saveJpgB64 } from "../images.js";
import { setSimilarity } from "../similarity.js";

interface EventBody {
  type: "deposit" | "withdrawal";
  camera_id?: string;
  slot_id: string;
  ts?: number;
  embeddings?: number[][];
  face_jpg_b64?: string | null;
  frame_jpg_b64?: string | null;
}

const insertEvent = db.prepare(
  "INSERT INTO events (ts, camera_id, slot_id, type, payload) VALUES (?, ?, ?, ?, ?)",
);

const findParked = db.prepare(
  "SELECT * FROM sessions WHERE camera_id = ? AND slot_id = ? AND status = 'parked' ORDER BY deposit_ts DESC",
);

export default async function events(app: FastifyInstance): Promise<void> {
  app.post("/api/events", async (req, reply) => {
    const body = req.body as EventBody;
    if (!body?.type || !body?.slot_id) {
      return reply.code(400).send({ error: "type e slot_id sao obrigatorios" });
    }
    const cameraId = body.camera_id ?? "cam1";
    const ts = body.ts ?? Date.now() / 1000;
    const embeddings = Array.isArray(body.embeddings) ? body.embeddings : [];

    insertEvent.run(ts, cameraId, body.slot_id, body.type, JSON.stringify({ faces: embeddings.length }));

    return body.type === "deposit"
      ? handleDeposit(cameraId, body, ts, embeddings)
      : handleWithdrawal(cameraId, body, ts, embeddings);
  });

  app.get("/api/events", async (req) => {
    const { limit = "100" } = req.query as { limit?: string };
    return db
      .prepare("SELECT * FROM events ORDER BY ts DESC LIMIT ?")
      .all(Math.min(Number(limit) || 100, 1000));
  });
}

function handleDeposit(cameraId: string, body: EventBody, ts: number, embeddings: number[][]) {
  // ja havia uma sessao aberta nessa vaga? fecha como orfa (a retirada nunca foi vista)
  const orphans = findParked.all(cameraId, body.slot_id) as SessionRow[];
  for (const o of orphans) {
    db.prepare("UPDATE sessions SET status = 'orphan', deposit_embeddings = NULL WHERE id = ?").run(o.id);
  }

  const id = randomUUID();
  db.prepare(
    `INSERT INTO sessions (id, camera_id, slot_id, deposit_ts, deposit_embeddings, deposit_face, deposit_frame, status)
     VALUES (?, ?, ?, ?, ?, ?, ?, 'parked')`,
  ).run(
    id,
    cameraId,
    body.slot_id,
    ts,
    embeddings.length ? JSON.stringify(embeddings) : null,
    saveJpgB64(body.face_jpg_b64),
    saveJpgB64(body.frame_jpg_b64),
  );

  return { ok: true, session_id: id, status: "parked", faces: embeddings.length, orphans: orphans.length };
}

function handleWithdrawal(cameraId: string, body: EventBody, ts: number, embeddings: number[][]) {
  const session = (findParked.all(cameraId, body.slot_id) as SessionRow[])[0];
  if (!session) {
    return { ok: false, status: "no_session", message: "retirada sem deposito aberto nesta vaga" };
  }

  const cfg = getConfig();
  const threshold = Number(cfg.similarity_threshold) || 0.3;
  const depositEmb: number[][] = session.deposit_embeddings ? JSON.parse(session.deposit_embeddings) : [];
  const similarity = setSimilarity(depositEmb, embeddings);

  let status: "ok" | "alert" = "ok";
  let reason: string | null = null;
  if (!depositEmb.length) {
    status = "alert";
    reason = "no_face_deposit";
  } else if (!embeddings.length) {
    status = "alert";
    reason = "no_face_withdrawal";
  } else if ((similarity ?? 0) < threshold) {
    status = "alert";
    reason = "low_similarity";
  }

  db.prepare(
    `UPDATE sessions
        SET withdrawal_ts = ?, withdrawal_face = ?, withdrawal_frame = ?,
            similarity = ?, status = ?, deposit_embeddings = NULL
      WHERE id = ?`,
  ).run(
    ts,
    saveJpgB64(body.face_jpg_b64),
    saveJpgB64(body.frame_jpg_b64),
    similarity,
    status,
    session.id,
  );
  // embeddings existem so enquanto a bike esta estacionada (LGPD, §12)

  let alertId: string | null = null;
  if (status === "alert") {
    alertId = randomUUID();
    db.prepare("INSERT INTO alerts (id, session_id, ts, reason, similarity) VALUES (?, ?, ?, ?, ?)").run(
      alertId,
      session.id,
      ts,
      reason,
      similarity,
    );
  }

  return {
    ok: true,
    session_id: session.id,
    status,
    reason,
    similarity,
    threshold,
    alert_id: alertId,
    faces: { deposit: depositEmb.length, withdrawal: embeddings.length },
  };
}

/** Retencao LGPD: apaga as fotos de sessoes normais depois de `retention_hours`. */
export function purgeOldFaces(): number {
  const cfg = getConfig();
  const cutoff = Date.now() / 1000 - Number(cfg.retention_hours ?? 24) * 3600;
  const rows = db
    .prepare(
      `SELECT id, deposit_face, deposit_frame, withdrawal_face, withdrawal_frame
         FROM sessions
        WHERE status IN ('ok', 'orphan')
          AND COALESCE(withdrawal_ts, deposit_ts) < ?
          AND (deposit_face IS NOT NULL OR withdrawal_face IS NOT NULL
               OR deposit_frame IS NOT NULL OR withdrawal_frame IS NOT NULL)`,
    )
    .all(cutoff) as Array<Pick<SessionRow, "id" | "deposit_face" | "deposit_frame" | "withdrawal_face" | "withdrawal_frame">>;

  const clear = db.prepare(
    `UPDATE sessions SET deposit_face = NULL, deposit_frame = NULL,
                         withdrawal_face = NULL, withdrawal_frame = NULL
      WHERE id = ?`,
  );
  for (const row of rows) {
    deleteFile(row.deposit_face);
    deleteFile(row.deposit_frame);
    deleteFile(row.withdrawal_face);
    deleteFile(row.withdrawal_frame);
    clear.run(row.id);
  }
  return rows.length;
}
