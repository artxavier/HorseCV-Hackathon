import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, usePolling } from "./api.ts";
import Configuracoes from "./pages/Configuracoes.tsx";
import Dashboard from "./pages/Dashboard.tsx";
import Eventos from "./pages/Eventos.tsx";
import Metricas from "./pages/Metricas.tsx";
import Portaria from "./pages/Portaria.tsx";

const LINKS = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/portaria", label: "Portaria" },
  { to: "/eventos", label: "Eventos" },
  { to: "/metricas", label: "Metricas" },
  { to: "/config", label: "Configuracoes" },
];

export default function App() {
  const { data: alerts } = usePolling(() => api.alerts(true), 3000);
  const { data: config } = usePolling(() => api.config(), 3000);
  const open = alerts?.length ?? 0;

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-10">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3">
          <span className="text-lg font-bold tracking-tight">
            Bike<span className="text-emerald-400">Guard</span>
          </span>
          <nav className="flex flex-wrap gap-1">
            {LINKS.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                className={({ isActive }) =>
                  `rounded px-3 py-1.5 text-sm transition ${
                    isActive ? "bg-emerald-500/15 text-emerald-300" : "text-slate-300 hover:bg-slate-800"
                  }`
                }
              >
                {l.label}
                {l.to === "/portaria" && open > 0 && (
                  <span className="ml-2 rounded-full bg-red-500 px-1.5 text-xs font-bold text-white">{open}</span>
                )}
              </NavLink>
            ))}
          </nav>
          <span className="ml-auto text-xs text-slate-400">
            modo <b className="text-slate-200 uppercase">{config?.mode ?? "?"}</b>
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/portaria" element={<Portaria />} />
          <Route path="/eventos" element={<Eventos />} />
          <Route path="/metricas" element={<Metricas />} />
          <Route path="/config" element={<Configuracoes />} />
        </Routes>
      </main>
    </div>
  );
}
