import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, fmtBytes, usePolling, type MetricSummary } from "../api.ts";

const JANELAS = [
  { value: 120, label: "2 min" },
  { value: 600, label: "10 min" },
  { value: 3600, label: "1 h" },
];

const CORES: Record<string, string> = { edge: "#34d399", fog: "#60a5fa", cloud: "#f59e0b" };

/** FPS real: frames dividido pelo tempo que eles levaram. Nao confundir com 1000/rtt,
 *  que e o teto que a inferencia permitiria, nao o ritmo em que o agente captura. */
function fps(s: MetricSummary): string {
  const span = (s.last_ts ?? 0) - (s.first_ts ?? 0);
  if (!(span > 0) || s.frames < 2) return "-";
  return ((s.frames - 1) / span).toFixed(1);
}

export default function Metricas() {
  const [janela, setJanela] = useState(600);
  const { data } = usePolling(() => api.metrics(janela), 2000);

  // uma serie de latencia por modo: a troca ao vivo fica visivel no grafico
  const pontos = (data?.rows ?? []).map((r) => ({
    t: new Date(r.ts * 1000).toLocaleTimeString("pt-BR"),
    [`rtt_${r.mode}`]: r.rtt_ms,
    [`infer_${r.mode}`]: r.inference_ms,
  }));

  const modos = [...new Set((data?.rows ?? []).map((r) => r.mode))];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">Metricas</h1>
        <div className="flex gap-1">
          {JANELAS.map((j) => (
            <button
              key={j.value}
              type="button"
              onClick={() => setJanela(j.value)}
              className={`rounded px-3 py-1 text-sm ${
                janela === j.value ? "bg-emerald-500/20 text-emerald-300" : "bg-slate-800 text-slate-300"
              }`}
            >
              {j.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-slate-300">
          Latencia total (RTT, linha cheia) e de inferencia (tracejada)
        </h2>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={pontos}>
              <CartesianGrid stroke="#1e293b" />
              <XAxis dataKey="t" stroke="#64748b" fontSize={11} minTickGap={40} />
              <YAxis stroke="#64748b" fontSize={11} unit=" ms" />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
              <Legend />
              {modos.map((m) => (
                <Line
                  key={`rtt-${m}`}
                  type="monotone"
                  dataKey={`rtt_${m}`}
                  name={`rtt ${m}`}
                  stroke={CORES[m] ?? "#a78bfa"}
                  dot={false}
                  connectNulls
                  strokeWidth={2}
                />
              ))}
              {modos.map((m) => (
                <Line
                  key={`infer-${m}`}
                  type="monotone"
                  dataKey={`infer_${m}`}
                  name={`inferencia ${m}`}
                  stroke={CORES[m] ?? "#a78bfa"}
                  strokeDasharray="4 3"
                  dot={false}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-slate-400">
            <tr>
              <th className="px-3 py-2">Modo</th>
              <th className="px-3 py-2">Frames</th>
              <th className="px-3 py-2">Inferencia media</th>
              <th className="px-3 py-2">Latencia media</th>
              <th className="px-3 py-2">FPS</th>
              <th className="px-3 py-2">Bytes/frame</th>
              <th className="px-3 py-2">Total enviado</th>
              <th className="px-3 py-2">% fallback</th>
            </tr>
          </thead>
          <tbody>
            {data?.summary.map((s) => (
              <tr key={s.mode} className="border-t border-slate-800">
                <td className="px-3 py-2 font-semibold uppercase" style={{ color: CORES[s.mode] }}>
                  {s.mode}
                </td>
                <td className="px-3 py-2">{s.frames}</td>
                <td className="px-3 py-2">{s.avg_inference_ms?.toFixed(0) ?? "-"} ms</td>
                <td className="px-3 py-2">{s.avg_rtt_ms?.toFixed(0) ?? "-"} ms</td>
                <td className="px-3 py-2">{fps(s)}</td>
                <td className="px-3 py-2">{fmtBytes(s.avg_payload_bytes)}</td>
                <td className="px-3 py-2">{fmtBytes(s.total_bytes)}</td>
                <td className="px-3 py-2">{s.fallback_pct?.toFixed(1) ?? "0.0"}%</td>
              </tr>
            ))}
            {!data?.summary.length && (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-slate-400">
                  Sem metricas nesta janela. Rode o agente.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
