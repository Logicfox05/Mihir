import { useRef, useState } from "react";
import { api } from "../api";
import { Badge, Empty, ErrorBox, fmt, usePoll } from "../ui";

export default function Imports() {
  const [kind, setKind] = useState("");
  const { data, error, reload } = usePoll(() => api.imports(kind || undefined), 10000, [kind]);
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const upload = async () => {
    const f = file.current?.files?.[0];
    if (!f) return;
    setBusy(true);
    try {
      const r = await api.importCustomers(f);
      setOpen(r.id);
      reload();
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">Imports & refreshes</h1>
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All</option><option value="customers">Customers</option><option value="orders">Orders</option>
        </select>
        <div className="ml-auto flex items-center gap-2">
          <input ref={file} type="file" accept=".xlsx,.xls" className="text-sm" />
          <button className="btn-primary" disabled={busy} onClick={upload}>{busy ? "Importing…" : "Upload customer Excel"}</button>
        </div>
      </div>
      <ErrorBox msg={error} />
      <div className="card p-0 overflow-auto">
        {!data || data.length === 0 ? (
          <Empty>No runs yet.</Empty>
        ) : (
          <table className="w-full">
            <thead><tr><th className="th">Finished</th><th className="th">Kind</th><th className="th">Result</th><th className="th">Source</th><th className="th">Rows</th><th className="th">Accepted</th><th className="th">Rejected</th><th className="th"></th></tr></thead>
            <tbody>
              {data.map((r) => (
                <>
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="td text-xs whitespace-nowrap">{fmt(r.finished_at)}</td>
                    <td className="td capitalize">{r.kind}</td>
                    <td className="td"><Badge tone={r.ok ? "green" : "red"}>{r.ok ? "ok" : "failed"}</Badge></td>
                    <td className="td text-xs break-all max-w-xs">{r.source}</td>
                    <td className="td">{r.total_rows}</td>
                    <td className="td">{r.accepted}</td>
                    <td className="td">{r.rejected ? <span className="text-amber-600 font-medium">{r.rejected}</span> : 0}</td>
                    <td className="td"><button className="btn-ghost" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? "Hide" : "Details"}</button></td>
                  </tr>
                  {open === r.id && (
                    <tr key={`${r.id}-d`}>
                      <td className="td bg-slate-50" colSpan={8}>
                        {r.error && <div className="text-rose-700 text-sm mb-2">Error: {r.error}</div>}
                        {r.warnings.length > 0 && <div className="text-amber-700 text-sm mb-2">Warnings: {r.warnings.join(" · ")}</div>}
                        <div className="text-xs text-slate-500 mb-2">Headers seen: {r.raw_headers.join(" | ") || "—"}</div>
                        {r.rejected_rows.length > 0 ? (
                          <table className="w-full bg-white">
                            <thead><tr>{Object.keys(r.rejected_rows[0]).map((k) => <th key={k} className="th">{k}</th>)}</tr></thead>
                            <tbody>{r.rejected_rows.map((row, i) => <tr key={i}>{Object.values(row).map((v, j) => <td key={j} className="td text-xs">{String(v ?? "")}</td>)}</tr>)}</tbody>
                          </table>
                        ) : <div className="text-sm text-slate-500">No rejected rows.</div>}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
