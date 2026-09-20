import { randomUUID } from "node:crypto";
import { existsSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { FACES_DIR } from "./db.js";

/** Salva um JPEG base64 em data/faces/<uuid>.jpg e devolve o nome do arquivo.
 *  As imagens sao servidas estaticamente em /files/.
 */
export function saveJpgB64(b64: string | null | undefined): string | null {
  if (!b64) return null;
  try {
    const clean = b64.includes(",") ? b64.slice(b64.indexOf(",") + 1) : b64;
    const name = `${randomUUID()}.jpg`;
    writeFileSync(join(FACES_DIR, name), Buffer.from(clean, "base64"));
    return name;
  } catch {
    return null;
  }
}

export function deleteFile(name: string | null): void {
  if (!name) return;
  const path = join(FACES_DIR, name);
  if (existsSync(path)) {
    try {
      unlinkSync(path);
    } catch {
      /* arquivo ja sumiu, tudo bem */
    }
  }
}

export function fileUrl(name: string | null): string | null {
  return name ? `/files/${name}` : null;
}
