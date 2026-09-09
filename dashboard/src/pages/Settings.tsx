import { useEffect, useState } from "react";
import { api, Connections, Preview } from "../api";
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
      <h1 className="text-xl font-semibold">Settings</h1>
      <ConversationCard />
      <h2 className="text-lg font-semibold pt-2">Orders source</h2>
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

/** How the conversation behaves: the silence that starts a new window, and how SO / item choices are shown. */
function ConversationCard() {
  const { data, error, reload } = usePoll<Connections>(() => api.connections(), 0);
  const [timeout, setTimeoutMin] = useState<number>(30);
  const [style, setStyle] = useState<"auto" | "list">("auto");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!data) return;
    setTimeoutMin(Number(data.fields.session_timeout_min?.value ?? 30));
    setStyle((data.fields.so_menu_style?.value as "auto" | "list") || "auto");
  }, [data]);

  const saved = data ? { timeout: Number(data.fields.session_timeout_min?.value ?? 30), style: String(data.fields.so_menu_style?.value || "auto") } : null;
  const dirty = !!saved && (saved.timeout !== timeout || saved.style !== style);

  const save = async () => {
    setBusy(true); setMsg(null); setErrors({});
    try {
      const values: Record<string, unknown> = {};
      if (saved?.timeout !== timeout) values.session_timeout_min = timeout;
      if (saved?.style !== style) values.so_menu_style = style;
      const r = await api.saveConnections(values);
      if (r.ok) { setMsg("Saved. The bot uses this from the next message."); await reload(); }
      else { setErrors(r.errors); setMsg("Please fix the marked field."); }
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card space-y-3 text-sm">
      <div>
        <div className="font-medium">Conversation</div>
        <div className="text-xs text-slate-500">How a chat starts and how choices are shown. Saved in the database — no restart needed.</div>
      </div>
      <ErrorBox msg={error} />
      <div className="grid md:grid-cols-2 gap-4">
        <label className="block">
          <div className="font-medium text-slate-700">New conversation after (minutes of silence)</div>
          <input type="number" min={1} max={1440} className={`input w-28 ${errors.session_timeout_min ? "border-rose-400" : ""}`} value={timeout} onChange={(e) => setTimeoutMin(Number(e.target.value))} />
          {errors.session_timeout_min && <div className="text-xs text-rose-600 mt-0.5">{errors.session_timeout_min}</div>}
          <div className="text-xs text-slate-500 mt-0.5">When a customer writes after this much silence, the bot sends the greeting and asks for the language again. Within the window it continues where they left off.</div>
        </label>
        <label className="block">
          <div className="font-medium text-slate-700">How SO numbers and items are offered</div>
          <select className="input w-full" value={style} onChange={(e) => setStyle(e.target.value as "auto" | "list")}>
            <option value="auto">Tap buttons when 3 or fewer, otherwise a list (recommended)</option>
            <option value="list">Always a list (the "Select" button opens it)</option>
          </select>
          <div className="text-xs text-slate-500 mt-0.5">WhatsApp allows at most 3 buttons or 10 list rows per message. Either way the customer just taps once.</div>
        </label>
      </div>
      <div className="flex items-center gap-2">
        <button className="btn-primary" disabled={busy || !dirty} onClick={save}>Save</button>
        {msg && <span className="text-slate-600">{msg}</span>}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex gap-2"><span className="font-mono text-xs text-slate-500 w-44 shrink-0">{k}</span><span className="font-mono text-xs break-all">{v}</span></div>;
}
