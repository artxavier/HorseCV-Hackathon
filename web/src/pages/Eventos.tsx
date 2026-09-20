import { useState } from "react";
import { api, fmtDateTime, usePolling, type Session } from "../api.ts";

const FILTROS = [
  { value: "", label: "todas" },
  { value: "parked", label: "estacionadas" },
  { value: "ok", label: "ok" },
  { value: "alert", label: "alerta" },
  { value: "orphan", label: "orfas" },
];

const BADGE: Record<string, string> = {
  parked: "bg-sky-500/20 text-sky-300",
  ok: "bg-emerald-500/20 text-emerald-300",
  alert: "bg-red-500/20 text-red-300",
  orphan: "bg-amber-500/20 text-amber-300",
};

export default function Eventos() {
  const [status, setStatus] = useState("");
  const { data: sessions } = usePolling<Session[]>(() => api.sessions(status || undefined), 2000);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Eventos</h1>
        <div className="flex gap-1">
          {FILTROS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatus(f.value)}
              className={`rounded px-3 py-1 text-sm ${
                status === f.value ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-800 text-slate-300"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-slate-400">
            <tr>
              <th className="px-3 py-2">Vaga</th>
              <th className="px-3 py-2">Deposito</th>
              <th className="px-3 py-2">Retirada</th>
              <th className="px-3 py-2">Similaridade</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Fotos</th>
            </tr>
          </thead>
          <tbody>
            {sessions?.map((s) => (
              <tr key={s.id} className="border-t border-slate-800">
                <td className="px-3 py-2 font-semibold">{s.slot_id}</td>
                <td className="px-3 py-2 text-slate-300">{fmtDateTime(s.deposit_ts)}</td>
                <td className="px-3 py-2 text-slate-300">{fmtDateTime(s.withdrawal_ts)}</td>
                <td className="px-3 py-2">{s.similarity === null ? "-" : s.similarity.toFixed(3)}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-2 py-0.5 text-xs font-semibold ${BADGE[s.status] ?? ""}`}>
                    {s.status}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    {[s.deposit_face_url, s.withdrawal_face_url].map(
                      (url, i) =>
                        url && (
                          <img
                            key={i}
                            src={url}
                            alt={i === 0 ? "deposito" : "retirada"}
                            className="h-10 w-10 rounded object-cover"
                          />
                        ),
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!sessions?.length && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-400">
                  Nenhuma sessao ainda.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
