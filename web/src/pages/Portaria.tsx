import { useState } from "react";
import { REASON_LABEL, api, fmtDateTime, usePolling, type Alert } from "../api.ts";

function Foto({ url, legenda }: { url: string | null; legenda: string }) {
  return (
    <figure className="flex-1">
      <div className="aspect-square overflow-hidden rounded-lg border border-slate-700 bg-slate-950">
        {url ? (
          <img src={url} alt={legenda} className="h-full w-full object-cover" />
        ) : (
          <div className="grid h-full place-items-center text-xs text-slate-500">sem foto</div>
        )}
      </div>
      <figcaption className="mt-1 text-center text-xs text-slate-400">{legenda}</figcaption>
    </figure>
  );
}

function Card({ alert, onAck }: { alert: Alert; onAck: (id: string) => void }) {
  const s = alert.session;
  return (
    <article className="rounded-xl border border-red-500/40 bg-slate-900 p-4">
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <span className="rounded bg-red-500/20 px-2 py-0.5 text-sm font-bold text-red-300">
          Vaga {s?.slot_id ?? "?"}
        </span>
        <span className="text-sm text-slate-300">{REASON_LABEL[alert.reason] ?? alert.reason}</span>
        <span className="ml-auto text-xs text-slate-400">{fmtDateTime(alert.ts)}</span>
      </header>

      <div className="flex gap-3">
        <Foto url={s?.deposit_face_url ?? null} legenda="deixou a bike" />
        <Foto url={s?.withdrawal_face_url ?? null} legenda="retirou a bike" />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-slate-400">
          similaridade:{" "}
          <b className="text-slate-100">{alert.similarity === null ? "-" : alert.similarity.toFixed(3)}</b>
        </span>
        {s?.deposit_ts && <span className="text-slate-400">deposito {fmtDateTime(s.deposit_ts)}</span>}
        <button
          type="button"
          onClick={() => onAck(alert.id)}
          className="ml-auto rounded-lg bg-emerald-500 px-4 py-2 font-semibold text-slate-950 hover:bg-emerald-400"
        >
          Verificado
        </button>
      </div>

      <p className="mt-3 text-[11px] text-slate-500">
        Isto e um pedido de verificacao, nao uma acusacao: confira as fotos antes de abordar.
      </p>
    </article>
  );
}

export default function Portaria() {
  const { data: alerts, refresh } = usePolling(() => api.alerts(true), 2000);
  const [busy, setBusy] = useState<string | null>(null);

  const ack = async (id: string) => {
    setBusy(id);
    try {
      await api.ackAlert(id);
      await refresh();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Portaria</h1>
      {!alerts?.length && (
        <p className="rounded-xl border border-slate-800 bg-slate-900 p-8 text-center text-slate-400">
          Nenhum alerta aberto.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {alerts?.map((a) => (
          <div key={a.id} className={busy === a.id ? "opacity-50" : ""}>
            <Card alert={a} onAck={ack} />
          </div>
        ))}
      </div>
    </div>
  );
}
