import type { FastifyInstance } from "fastify";
import { getConfig, saveConfig } from "../config.js";

export default async function config(app: FastifyInstance): Promise<void> {
  app.get("/api/config", async () => getConfig());

  app.put("/api/config", async (req, reply) => {
    const patch = req.body as Record<string, unknown>;
    if (!patch || typeof patch !== "object") {
      return reply.code(400).send({ error: "corpo deve ser um objeto" });
    }
    return saveConfig(patch);
  });
}
