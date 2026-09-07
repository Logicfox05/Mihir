import { useState } from "react";
import { api } from "../api";
import { Empty, ErrorBox, fmt, usePoll } from "../ui";

export default function Data() {
  const [tab, setTab] = useState<"customers" | "orders" | "outbox" | "queue">("customers");
  const [q, setQ] = useState("");
  const customers = usePoll(() => api.customers(q), 10000, [q, tab]);
  const orders = usePoll(() => api.orders(q), 10000, [q, tab]);
  const outbox = usePoll(() => api.outbox(), 5000, [tab]);
  const queue = usePoll(() => api.queue(), 5000, [tab]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">Data</h1>
        <div className="flex gap-1 ml-2">
          {(["customers", "orders", "outbox", "queue"] as const).map((t) => (
            <button key={t} className={`btn ${tab === t ? "bg-brand-600 text-white border-brand-600" : "bg-white border-slate-300"}`} onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
        {(tab === "customers" || tab === "orders") && <input className="input ml-auto" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />}
      </div>
      <ErrorBox msg={customers.error || orders.error || outbox.error || queue.error} />
      <div className="card p-0 overflow-auto">
        {tab === "customers" && (!customers.data?.length ? <Empty>No customers.</Empty> : (
          <table className="w-full">
            <thead><tr><th className="th">Phone (waId)</th><th className="th">Code</th><th className="th">Name (exact)</th><th className="th">Raw contact</th><th className="th">Matching SOs</th><th className="th">Imported</th></tr></thead>
            <tbody>{customers.data.map((c) => (
              <tr key={c.phone}><td className="td font-mono">{c.phone}</td><td className="td">{c.code}</td><td className="td font-mono text-xs">"{c.name}"</td><td className="td font-mono text-xs">{c.raw_contact}</td>
                <td className="td text-xs">{c.so_numbers.join(", ") || <span className="text-slate-400">none</span>}</td><td className="td text-xs text-slate-500">{fmt(c.imported_at)}</td></tr>
            ))}</tbody>
          </table>
        ))}
        {tab === "orders" && (!orders.data?.length ? <Empty>No orders cached.</Empty> : (
          <table className="w-full">
            <thead><tr><th className="th">SO</th><th className="th">PO</th><th className="th">FG item</th><th className="th">Customer name (exact)</th><th className="th">Real status (sent)</th><th className="th">Connection status (internal)</th><th className="th">Fetched</th></tr></thead>
            <tbody>{orders.data.map((o) => (
              <tr key={o.id}><td className="td font-mono">{o.so_no}</td><td className="td font-mono text-xs">{o.po_no}</td><td className="td font-mono text-xs">{o.fg_item_code}</td><td className="td font-mono text-xs">"{o.customer_name}"</td>
                <td className="td">{o.real_status}</td><td className="td text-xs text-slate-400">{o.connection_status}</td><td className="td text-xs text-slate-500">{fmt(o.fetched_at)}</td></tr>
            ))}</tbody>
          </table>
        ))}
        {tab === "outbox" && (!outbox.data?.length ? <Empty>Nothing sent yet (in-memory, resets on restart).</Empty> : (
          <table className="w-full">
            <thead><tr><th className="th">At</th><th className="th">Phone</th><th className="th">Kind</th><th className="th">Text</th></tr></thead>
            <tbody>{[...outbox.data].reverse().map((o, i) => (
              <tr key={i}><td className="td text-xs whitespace-nowrap">{fmt(o.at)}</td><td className="td font-mono text-xs">{o.phone}</td><td className="td text-xs">{o.kind}{o.options ? ` [${o.options.items.map((x) => x.title).join(" / ")}]` : ""}{o.sent ? " · sent" : " · mock"}</td><td className="td whitespace-pre-wrap text-sm">{o.text}</td></tr>
            ))}</tbody>
          </table>
        ))}
        {tab === "queue" && (!queue.data?.length ? <Empty>Queue is empty.</Empty> : (
          <table className="w-full">
            <thead><tr><th className="th">Id</th><th className="th">Phone</th><th className="th">Status</th><th className="th">Attempts</th><th className="th">Error</th><th className="th">Updated</th></tr></thead>
            <tbody>{queue.data.map((r) => (
              <tr key={r.id}><td className="td">{r.id}</td><td className="td font-mono text-xs">{r.phone}</td><td className="td text-xs">{r.status}</td><td className="td">{r.attempts}</td><td className="td text-xs text-rose-700">{r.error}</td><td className="td text-xs text-slate-500">{fmt(r.updated_at)}</td></tr>
            ))}</tbody>
          </table>
        ))}
      </div>
    </div>
  );
}
