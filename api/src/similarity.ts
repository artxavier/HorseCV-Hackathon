/** Similaridade de cosseno entre embeddings faciais.
 *
 * Os embeddings ja chegam L2-normalizados do servidor de inferencia, mas
 * normalizamos de novo aqui -- e barato e evita depender disso.
 */

export function cosine(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  if (n === 0) return 0;
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < n; i++) {
    dot += a[i]! * b[i]!;
    na += a[i]! * a[i]!;
    nb += b[i]! * b[i]!;
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/** Maximo do cosseno entre todos os pares (deposito x retirada).
 *
 * Com varios rostos de cada lado, um unico frame ruim (cabeca baixa, borrado)
 * nao gera alerta falso (CLAUDE.md §6).
 */
export function maxPairwise(a: number[][], b: number[][]): number | null {
  if (!a?.length || !b?.length) return null;
  let best = -1;
  for (const x of a) {
    for (const y of b) {
      const s = cosine(x, y);
      if (s > best) best = s;
    }
  }
  return best === -1 ? null : best;
}
