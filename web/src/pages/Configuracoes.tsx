import { useEffect, useState } from "react";
import { api, type Config, type Mode } from "../api.ts";

const MODOS: { value: Mode; titulo: string; texto: string }[] = [
  { value: "edge", titulo: "EDGE", texto: "Inferencia no proprio dispositivo. Nenhuma imagem sai daqui." },
  { value: "fog", titulo: "FOG", texto: "Inferencia num PC da universidade, na mesma rede." },
  { value: "cloud", titulo: "CLOUD", texto: "Inferencia num container na nuvem." },
];

function Campo({
  label,
  value,
  onChange,
  step,
  hint,
}: {
  label: string;
  value: number | string;
  onChange: (v: string) => void;
  step?: string;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs text-slate-400">{label}</span>
      <input
        value={value}
        step={step}
        type={typeof value === "number" ? "number" : "text"}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm"
      />
      {hint && <span className="text-[11px] text-slate-500">{hint}</span>}
    </label>
  );
}

export default function Configuracoes() {
  const [cfg, setCfg] = useState<Config | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    void api.config().then(setCfg);
  }, []);

  if (!cfg) return <p className="text-slate-400">carregando...</p>;

  const patch = (p: Partial<Config>) => setCfg({ ...cfg, ...p });

  const salvar = async (p: Partial<Config>) => {
    const saved = await api.saveConfig(p);
    setCfg(saved);
    setMsg("salvo — o agente pega a mudanca no proximo polling (ate 5 s)");
    setTimeout(() => setMsg(""), 4000);
  };

  const num = (v: string, fallback: number) => (v === "" ? fallback : Number(v));

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-xl font-semibold">Modo de processamento</h1>
        <p className="mb-3 text-sm text-slate-400">
          Muda apenas onde a inferencia roda. Captura, ocupacao e eventos continuam no dispositivo.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {MODOS.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => void salvar({ mode: m.value })}
              className={`rounded-xl border-2 p-5 text-left transition ${
                cfg.mode === m.value
                  ? "border-emerald-400 bg-emerald-500/15"
                  : "border-slate-700 bg-slate-900 hover:border-slate-500"
              }`}
            >
              <div className="text-2xl font-black tracking-tight">{m.titulo}</div>
              <div className="mt-1 text-xs text-slate-400">{m.texto}</div>
              <div className="mt-2 truncate text-[11px] text-slate-500">{cfg.inference_urls[m.value]}</div>
              <div className="text-[11px] text-slate-500">detector: {cfg.detector[m.value]}</div>
            </button>
          ))}
        </div>
        {msg && <p className="mt-3 text-sm text-emerald-400">{msg}</p>}
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <h2 className="col-span-full text-sm font-semibold text-slate-300">URLs de inferencia</h2>
        {(["edge", "fog", "cloud"] as Mode[]).map((m) => (
          <Campo
            key={m}
            label={m}
            value={cfg.inference_urls[m]}
            onChange={(v) => patch({ inference_urls: { ...cfg.inference_urls, [m]: v } })}
          />
        ))}
        {(["edge", "fog", "cloud"] as Mode[]).map((m) => (
          <Campo
            key={`det-${m}`}
            label={`detector ${m}`}
            value={cfg.detector[m]}
            onChange={(v) => patch({ detector: { ...cfg.detector, [m]: v } })}
            hint="yolo26 | rfdetr"
          />
        ))}
      </section>

      <section className="grid gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <h2 className="col-span-full text-sm font-semibold text-slate-300">Limiares e captura</h2>
        <Campo label="target_fps" value={cfg.target_fps} onChange={(v) => patch({ target_fps: num(v, 3) })} />
        <Campo label="jpeg_quality" value={cfg.jpeg_quality} onChange={(v) => patch({ jpeg_quality: num(v, 75) })} />
        <Campo label="infer_width" value={cfg.infer_width} onChange={(v) => patch({ infer_width: num(v, 640) })} />
        <Campo label="timeout_ms" value={cfg.timeout_ms} onChange={(v) => patch({ timeout_ms: num(v, 2000) })} />
        <Campo
          label="similarity_threshold"
          value={cfg.similarity_threshold}
          step="0.01"
          onChange={(v) => patch({ similarity_threshold: num(v, 0.3) })}
          hint="calibre com scripts/calibrate.py"
        />
        <Campo
          label="occupancy_threshold"
          value={cfg.occupancy_threshold}
          step="0.01"
          onChange={(v) => patch({ occupancy_threshold: num(v, 0.25) })}
        />
        <Campo
          label="debounce_seconds"
          value={cfg.debounce_seconds}
          onChange={(v) => patch({ debounce_seconds: num(v, 3) })}
        />
        <Campo
          label="face_window_seconds"
          value={cfg.face_window_seconds}
          onChange={(v) => patch({ face_window_seconds: num(v, 15) })}
        />
        <Campo
          label="occupied_ratio"
          value={cfg.occupied_ratio}
          step="0.05"
          onChange={(v) => patch({ occupied_ratio: num(v, 0.7) })}
        />
        <Campo
          label="empty_ratio"
          value={cfg.empty_ratio}
          step="0.05"
          onChange={(v) => patch({ empty_ratio: num(v, 0.2) })}
        />
        <Campo label="top_k" value={cfg.top_k} onChange={(v) => patch({ top_k: num(v, 5) })} />
        <Campo
          label="retention_hours"
          value={cfg.retention_hours}
          onChange={(v) => patch({ retention_hours: num(v, 24) })}
        />
        <Campo
          label="roi (x1,y1,x2,y2)"
          value={cfg.roi.join(",")}
          onChange={(v) => patch({ roi: v.split(",").map((x) => Number(x.trim()) || 0) })}
        />
        <Campo
          label="slot_ids (grade do dashboard)"
          value={(cfg.slot_ids ?? []).join(",")}
          onChange={(v) => patch({ slot_ids: v.split(",").map((x) => x.trim()).filter(Boolean) })}
        />
      </section>

      <button
        type="button"
        onClick={() => void salvar(cfg)}
        className="rounded-lg bg-emerald-500 px-5 py-2 font-semibold text-slate-950 hover:bg-emerald-400"
      >
        Salvar tudo
      </button>
    </div>
  );
}
