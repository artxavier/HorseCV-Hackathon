import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { FastifyInstance } from "fastify";
import { FRAMES_DIR } from "../db.js";

/** Ultimo frame anotado de cada camera. Fica em memoria (o Dashboard recarrega
 *  a imagem a cada ~1 s) e tambem em disco, para sobreviver a um restart. */
const latest = new Map<string, { jpg: Buffer; ts: number }>();

/** Recupera o ultimo frame do disco depois de um restart da api, para o Dashboard
 *  nao ficar com a imagem quebrada ate o agente postar o proximo frame. */
function fromDisk(id: string): { jpg: Buffer; ts: number } | undefined {
  const path = join(FRAMES_DIR, `${id}.jpg`);
  if (!existsSync(path)) return undefined;
  try {
    const frame = { jpg: readFileSync(path), ts: statSync(path).mtimeMs / 1000 };
    latest.set(id, frame);
    return frame;
  } catch {
    return undefined;
  }
}

export default async function cameras(app: FastifyInstance): Promise<void> {
  app.addContentTypeParser("image/jpeg", { parseAs: "buffer" }, (_req, body, done) => done(null, body));

  app.post("/api/cameras/:id/frame", async (req, reply) => {
    const { id } = req.params as { id: string };
    const body = req.body as Buffer;
    if (!Buffer.isBuffer(body) || body.length === 0) {
      return reply.code(400).send({ error: "esperado um JPEG no corpo (Content-Type: image/jpeg)" });
    }
    latest.set(id, { jpg: body, ts: Date.now() / 1000 });
    try {
      writeFileSync(join(FRAMES_DIR, `${id}.jpg`), body);
    } catch {
      /* disco cheio nao pode derrubar a demo */
    }
    return { ok: true, bytes: body.length };
  });

  app.get("/api/cameras/:id/frame.jpg", async (req, reply) => {
    const { id } = req.params as { id: string };
    const frame = latest.get(id) ?? fromDisk(id);
    if (!frame) return reply.code(404).send({ error: "sem frame ainda" });
    return reply
      .header("Content-Type", "image/jpeg")
      .header("Cache-Control", "no-store")
      .header("X-Frame-Ts", String(frame.ts))
      .send(frame.jpg);
  });

  app.get("/api/cameras", async () =>
    [...latest.entries()].map(([id, f]) => ({ id, ts: f.ts, age_seconds: Date.now() / 1000 - f.ts })));
}
