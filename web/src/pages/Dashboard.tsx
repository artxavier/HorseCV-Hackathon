import { useEffect, useState } from "react";
import { api, fmtTime, usePolling, type SlotState } from "../api.ts";

const CAMERA = "cam1";

/** Frame ao vivo: um <img> recarregando o jpeg com cache-buster (§8). */
function LiveFrame() {
  const [tick, setTick] = useState(Date.now());
  const [ok, setOk] = useState(true);

  useEffect(() => {
    const id = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-black">
      {/* eslint-disable-next-line jsx-a11y/img-redundant-alt */}
      <img
        src={`/api/cameras/${CAMERA}/frame.jpg?t=${tick}`}
        alt="Frame ao vivo do bicicletario"
        className="w-full object-contain"
        onLoad={() => setOk(true)}
        onError={() => setOk(false)}
      />
      {!ok && (
        <div className="absolute inset-0 grid place-items-center bg-slate-900/90 p-8 text-center text-sm text-slate-400">
          Sem frame ainda. Rode o agente:
          <br />
          <code className="mt-2 block text-emerald-300">python -m agent.main --source 0</code>
        </div>
      )}
    </div>
  );
}

function slotClass(state: string): string {
  if (state === "alert") return "border-red-500 bg-red-500/15 text-red-200";
  if (state === "occupied") return "border-sky-500 bg-sky-500/15 text-sky-200";
  return "border-emerald-600 bg-emerald-500/10 text-emerald-200";
}

export default function Dashboard() {
  const { data: slots } = usePolling(() => api.slots(CAMERA), 1500);
  const { data: config } = usePolling(() => api.config(), 3000);
  const { data: metrics } = usePolling(() => api.metrics(60), 3000);

  const byId = new Map<string, SlotState>((slots ?? []).map((s) => [s.slot_id, s]));
  const ids = [...new Set([...(config?.slot_ids ?? []), ...byId.keys()])].sort();

  const recent = metrics?.rows ?? [];
  const fps = recent.length > 1
    ? recent.length / Math.max(1, recent[recent.length - 1]!.ts - recent[0]!.ts)
    : 0;
  const lastMode = recent.length ? recent[recent.length - 1]!.mode : config?.mode;

  return (
    <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
      <section className="space-y-3">
        <h1 className="text-xl font-semibold">Bicicletario ao vivo</h1>
        <LiveFrame />
      </section>

      <section className="space-y-4">
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="text-xs text-slate-400">modo</div>
            <div className="text-lg font-bold uppercase">{lastMode ?? "-"}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="text-xs text-slate-400">FPS</div>
            <div className="text-lg font-bold">{fps ? fps.toFixed(1) : "-"}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
            <div className="text-xs text-slate-400">ocupadas</div>
            <div className="text-lg font-bold">
              {[...byId.values()].filter((s) => s.state !== "alert").length}/{ids.length}
            </div>
          </div>
        </div>

        <h2 className="text-sm font-semibold text-slate-300">Vagas</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {ids.map((id) => {
            const slot = byId.get(id);
            const state = slot?.state ?? "empty";
            return (
              <div key={id} className={`rounded-lg border p-3 ${slotClass(state)}`}>
                <div className="text-base font-bold">{id}</div>
                <div className="text-xs opacity-90">
                  {state === "alert" ? "ALERTA" : state === "occupied" ? "ocupada" : "vazia"}
                </div>
                {slot?.session && (
                  <div className="mt-1 text-[11px] opacity-75">desde {fmtTime(slot.session.deposit_ts)}</div>
                )}
              </div>
            );
          })}
          {ids.length === 0 && (
            <p className="col-span-full text-sm text-slate-400">
              Nenhuma vaga configurada. Ajuste <code>slot_ids</code> em Configuracoes.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
