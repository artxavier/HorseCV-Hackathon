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

/** Media dos embeddings normalizados -- o "template" daquele lado da sessao. */
function template(set: number[][]): number[] | null {
  const dim = set[0]?.length ?? 0;
  if (!dim) return null;
  const acc = new Array<number>(dim).fill(0);
  let used = 0;
  for (const v of set) {
    if (v.length !== dim) continue;
    let n = 0;
    for (const x of v) n += x * x;
    n = Math.sqrt(n);
    if (n === 0) continue;
    for (let i = 0; i < dim; i++) acc[i]! += v[i]! / n;
    used++;
  }
  return used ? acc : null;
}

/** Similaridade entre os dois conjuntos de rostos da sessao: cosseno entre o
 *  template do deposito e o da retirada.
 *
 *  Substituiu o maximo par a par. Medido nos videos de samples/ (a_verdade x
 *  a_mentira, buffalo_l): o maximo separa genuinos de impostores por 0.214 e o
 *  template por 0.288. O maximo pega o melhor de ate 25 pares, entao um unico
 *  par com sorte puxa o impostor para cima; a media cancela o ruido de frame em
 *  vez de amplifica-lo -- e e ela que protege contra o frame ruim que o §6 do
 *  CLAUDE.md queria evitar.
 */
export function setSimilarity(a: number[][], b: number[][]): number | null {
  if (!a?.length || !b?.length) return null;
  const ta = template(a);
  const tb = template(b);
  if (!ta || !tb) return null;
  return cosine(ta, tb);
}

/** Maximo do cosseno entre todos os pares. Mantido para comparacao offline. */
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
