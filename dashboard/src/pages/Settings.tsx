import { useState } from "react";
import { api, Preview } from "../api";
import { Badge, ErrorBox, fmt, usePoll } from "../ui";

export default function Settings() {
  const { data, error, reload } = usePoll(() => api.ordersSource(), 0);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);

  const test = async () => {
    setBusy(true);
    try {
      setPreview(await api.testFetch());
      reload();
    } finally {
      setBusy(false);
    }
  };
  const p = preview || data?.last_preview || null;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Settings · Orders source</h1>
      <p className="text-sm text-slate-500">All values come from the backend <code>.env</code>. Change them there and restart. Use "Test fetch" to verify the endpoint, API key and column map without touching the cache.</p>
      <ErrorBox msg={error} />
      {data && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div className="card space-y-2 text-sm">
            <div className="font-medium">Current configuration</div>
            <Row k="ORDERS_SOURCE" v={data.source} />
            <Row k="ORDERS_FORMAT" v={data.format} />
            {data.source === "file" && <Row k="ORDERS_FILE_PATH" v={data.file_path || ""} />}
            {data.source === "http" && (<>
              <Row k="ORDERS_API_URL" v={data.api_url || "(empty!)"} />
              <Row k="ORDERS_API_METHOD" v={data.api_method} />
              <Row k="ORDERS_API_KEY" v={data.api_key_set ? "•••• (set)" : "(empty)"} />
              <Row k="ORDERS_API_KEY_IN" v={`${data.api_key_in} (${data.api_key_name})`} />
            </>)}
            {data.source === "sql" && <Row k="ORDERS_SQL_URL" v={data.sql_url_set ? "(set)" : "(empty!)"} />}
            <div className="font-medium pt-2">Column map (internal field → header in the table)</div>
            <table className="w-full">
              <tbody>
                {Object.entries(data.column_map).map(([k, v]) => (
                  <tr key={k}><td className="td font-mono text-xs w-40">{k}</td><td className="td font-mono text-xs">"{v}"</td>
                    <td className="td text-xs">{p?.resolved?.[k] ? (p.resolved[k] === v ? <Badge tone="green">found</Badge> : <Badge tone="amber">≈ "{p.resolved[k]}"</Badge>) : p ? <Badge tone={["so_no", "customer_name", "real_status"].includes(k) ? "red" : "slate"}>missing</Badge> : null}</td></tr>
                ))}
              </tbody>
            </table>
            <button className="btn-primary mt-2" disabled={busy} onClick={test}>{busy ? "Fetching…" : "Test fetch"}</button>
          </div>
          <div className="card space-y-2 text-sm">
            <div className="font-medium flex items-center gap-2">Last test fetch {p && <Badge tone={p.ok ? "green" : "red"}>{p.ok ? "ok" : "failed"}</Badge>}<span className="ml-auto text-xs text-slate-400">{p ? fmt(p.at) : ""}</span></div>
            {!p ? <div className="text-slate-500">Run "Test fetch".</div> : (
              <>
                <div className="text-xs text-slate-500 break-all">{p.source}</div>
                {p.error && <div className="text-rose-700">{p.error}</div>}
                {p.warnings.length > 0 && <div className="text-amber-700 text-xs">{p.warnings.join(" · ")}</div>}
                <div>Raw rows: <b>{p.total_raw}</b> · mapped: <b>{p.mapped}</b></div>
                <div className="text-xs text-slate-500">Headers seen: {p.headers.join(" | ") || "—"}</div>
                {p.sample.length > 0 && (
                  <div className="overflow-auto">
                    <table className="w-full">
                      <thead><tr>{Object.keys(p.sample[0]).map((k) => <th key={k} className="th">{k}</th>)}</tr></thead>
                      <tbody>{p.sample.map((r, i) => <tr key={i}>{Object.values(r).map((v, j) => <td key={j} className="td font-mono text-xs">{v === null ? "—" : `"${v}"`}</td>)}</tr>)}</tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
      <div className="card text-sm space-y-1">
        <div className="font-medium">Go to production checklist</div>
        <ol className="list-decimal ml-5 space-y-1 text-slate-600">
          <li>WATI → Settings → API Docs: copy tenant URL + token into <code>WATI_BASE_URL</code> / <code>WATI_TOKEN</code>.</li>
          <li>Set a long random <code>WATI_WEBHOOK_TOKEN</code>; in WATI → Webhooks add <code>https://&lt;domain&gt;/webhook/wati?token=&lt;that&gt;</code> for "Message received".</li>
          <li>Disable every WATI chatbot flow / default reply so nothing intercepts messages.</li>
          <li>Set <code>ORDERS_SOURCE=http</code>, <code>ORDERS_API_URL</code>, <code>ORDERS_API_KEY</code>, <code>ORDERS_API_KEY_IN</code>, <code>ORDERS_COLUMN_MAP</code>; press "Test fetch" until it is green.</li>
          <li>Dropbox app key/secret/refresh token + <code>DROPBOX_FILE_PATH</code>; run "Import customers now"; check rejected rows in Imports.</li>
          <li>Optional: <code>GROQ_API_KEY</code> (voice notes), <code>OPENAI_API_KEY</code> (better intent/language), <code>ALERT_SLACK_WEBHOOK</code>.</li>
          <li>Set <code>APP_MODE=prod</code>, <code>ADMIN_KEY</code>, <code>SUPPORT_CONTACT</code>, MySQL <code>DATABASE_URL</code>. Restart. Message the number from your own phone.</li>
        </ol>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex gap-2"><span className="font-mono text-xs text-slate-500 w-44 shrink-0">{k}</span><span className="font-mono text-xs break-all">{v}</span></div>;
}
