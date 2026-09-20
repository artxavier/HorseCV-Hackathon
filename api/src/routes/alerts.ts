import type { FastifyInstance } from "fastify";
import { db, type AlertRow, type SessionRow } from "../db.js";
import { toPublicSession } from "./sessions.js";

export default async function alerts(app: FastifyInstance): Promise<void> {
  app.get("/api/alerts", async (req) => {
    const { open, limit = "100" } = req.query as { open?: string; limit?: string };
    const sql = `SELECT * FROM alerts ${open === "1" ? "WHERE acknowledged = 0" : ""} ORDER BY ts DESC LIMIT ?`;
    const rows = db.prepare(sql).all(Math.min(Number(limit) || 100, 500)) as AlertRow[];
    const getSession = db.prepare("SELECT * FROM sessions WHERE id = ?");
    return rows.map((a) => {
      const session = getSession.get(a.session_id) as SessionRow | undefined;
      return { ...a, acknowledged: !!a.acknowledged, session: session ? toPublicSession(session) : null };
    });
  });

  /** A portaria confere as duas fotos e marca como verificado -- humano no loop (§12). */
  app.post("/api/alerts/:id/ack", async (req, reply) => {
    const { id } = req.params as { id: string };
    const res = db.prepare("UPDATE alerts SET acknowledged = 1 WHERE id = ?").run(id);
    if (res.changes === 0) return reply.code(404).send({ error: "alerta nao encontrado" });
    return { ok: true, id };
  });
}
