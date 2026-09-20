/** BikeGuard api -- Fastify + SQLite, sem ORM e sem camadas (CLAUDE.md §7 e §13). */

import cors from "@fastify/cors";
import fastifyStatic from "@fastify/static";
import Fastify from "fastify";
import { FACES_DIR } from "./db.js";
import { getConfig } from "./config.js";
import alerts from "./routes/alerts.js";
import cameras from "./routes/cameras.js";
import config from "./routes/config.js";
import events, { purgeOldFaces } from "./routes/events.js";
import metrics from "./routes/metrics.js";
import sessions from "./routes/sessions.js";

const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOST ?? "0.0.0.0";

const app = Fastify({
  logger: { transport: { target: "pino-pretty" } },
  // frames e rostos vem em base64 dentro do JSON do evento
  bodyLimit: 32 * 1024 * 1024,
});

await app.register(cors, { origin: true });
await app.register(fastifyStatic, { root: FACES_DIR, prefix: "/files/" });

await app.register(events);
await app.register(sessions);
await app.register(alerts);
await app.register(config);
await app.register(metrics);
await app.register(cameras);

app.get("/api/health", async () => ({ ok: true, mode: getConfig().mode }));

// retencao LGPD: limpeza no boot + de hora em hora (§7)
const purged = purgeOldFaces();
if (purged) app.log.info(`retencao: ${purged} sessoes tiveram as fotos apagadas`);
setInterval(() => {
  const n = purgeOldFaces();
  if (n) app.log.info(`retencao: ${n} sessoes tiveram as fotos apagadas`);
}, 60 * 60 * 1000).unref();

await app.listen({ port: PORT, host: HOST });
