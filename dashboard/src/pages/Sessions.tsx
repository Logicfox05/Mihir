import { useState } from "react";
import { api, SessionDetail } from "../api";
import MenuPreview from "../MenuPreview";
import { Badge, Empty, ErrorBox, OUTCOME_TONE, STEP_TONE, ago, fmt, usePoll } from "../ui";

export default function Sessions() {
  const { data, error, reload } = usePoll(() => api.sessions(), 5000);
  const [sel, setSel] = useState<string | null>(null);
  const detail = usePoll<SessionDetail | null>(() => (sel ? api.session(sel) : Promise.resolve(null)), 5000, [sel]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Sessions</h1>
      <ErrorBox msg={error} />
      <div className="grid lg:grid-cols-5 gap-4">
        <div className="card lg:col-span-3 overflow-auto p-0">
          {!data || data.length === 0 ? (
            <Empty>No sessions yet.</Empty>
          ) : (
            <table className="w-full">
              <thead><tr><th className="th">Phone</th><th className="th">Customer</th><th className="th">Step</th><th className="th">SO / FG</th><th className="th">Lang</th><th className="th">Updated</th></tr></thead>
              <tbody>
                {data.map((s) => (
                  <tr key={s.phone} onClick={() => setSel(s.phone)} className={`cursor-pointer hover:bg-slate-50 ${sel === s.phone ? "bg-brand-50" : ""}`}>
                    <td className="td font-mono">{s.phone}</td>
                    <td className="td">{s.customer_name || <span className="text-rose-600">unknown</span>}</td>
                    <td className="td"><Badge tone={STEP_TONE[s.step]}>{s.step}</Badge>{s.pending_value && <span className="text-xs text-slate-500 ml-1">? {s.pending_value}</span>}</td>
                    <td className="td font-mono text-xs">{s.so_no || "—"}{s.fg_code ? ` / ${s.fg_code}` : ""}{s.attempts ? <span className="text-amber-600 ml-1">({s.attempts} tries)</span> : null}</td>
                    <td className="td">{s.language}</td>
                    <td className="td text-xs text-slate-500" title={fmt(s.updated_at)}>{ago(s.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card lg:col-span-2">
          {!sel ? (
            <Empty>Select a session to see its details.</Empty>
          ) : !detail.data ? (
            <div className="text-slate-500 text-sm">Loading…</div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <div className="font-mono font-medium">{sel}</div>
                <div className="text-sm text-slate-500">{detail.data.customer?.name || "not a customer"}</div>
                <button className="btn-ghost ml-auto" onClick={async () => { await api.resetSession(sel); detail.reload(); reload(); }}>Reset</button>
              </div>
              {detail.data.session && (
                <div className="grid grid-cols-3 gap-2 text-xs">
                  {Object.entries(detail.data.session).filter(([k]) => !["phone", "customer_name"].includes(k)).map(([k, v]) => (
                    <div key={k} className="bg-slate-50 rounded p-1.5"><div className="text-slate-400">{k}</div><div className="font-mono break-all">{v === null || v === "" ? "—" : String(v)}</div></div>
                  ))}
                </div>
              )}
              <div className="text-sm font-medium">Last messages</div>
              <div className="space-y-1 max-h-96 overflow-auto">
                {detail.data.messages.map((m) => (
                  <div key={m.id} className={`text-sm rounded-lg px-3 py-2 max-w-[90%] ${m.direction === "in" ? "bg-slate-100" : "bg-brand-50 ml-auto"}`}>
                    <div className="whitespace-pre-wrap break-words">{m.text}</div>
                    {m.transcript && <div className="text-xs text-slate-500 mt-1">🎤 {m.transcript}</div>}
                    {m.options && <MenuPreview options={m.options} compact />}
                    <div className="text-[10px] text-slate-400 mt-1 flex gap-2">{fmt(m.created_at)}{m.outcome && <Badge tone={OUTCOME_TONE[m.outcome]}>{m.outcome}</Badge>}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
