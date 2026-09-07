import { useEffect, useMemo, useRef, useState } from "react";
import { api, Catalog, CatalogLabel, CatalogTemplate, CustomReply, Lang } from "../api";
import MenuPreview from "../MenuPreview";
import { Badge, ErrorBox, fmt, usePoll } from "../ui";

const LANGS: Lang[] = ["en", "hi", "gu"];

type Sel = { kind: "template"; key: string } | { kind: "label"; key: string } | { kind: "custom"; key: string } | { kind: "new-custom" };

const SAMPLE_MENUS: Record<string, { kind: "buttons" | "list"; items: { title: string; description: string }[]; button_text: string; section_title: string; header: string; footer: string }> = {
  so_list: { kind: "list", items: [{ title: "SO 45240", description: "3 items · PO PO-8801" }, { title: "SO 45231", description: "1 item · PO PO-7781" }], button_text: "Select SO", section_title: "Your orders", header: "", footer: "" },
  fg_list: { kind: "list", items: [{ title: "FG-2001", description: "" }, { title: "FG-2002", description: "" }, { title: "FG-2003", description: "" }], button_text: "Select item", section_title: "Items in SO 45240", header: "", footer: "Or type the code." },
  confirm: { kind: "buttons", items: [{ title: "Yes", description: "" }, { title: "No", description: "" }], button_text: "", section_title: "", header: "", footer: "" },
  after_result: { kind: "buttons", items: [{ title: "Check another SO", description: "" }, { title: "Done", description: "" }], button_text: "", section_title: "", header: "", footer: "" },
  not_found: { kind: "buttons", items: [{ title: "Show my orders", description: "" }, { title: "Done", description: "" }], button_text: "", section_title: "", header: "", footer: "" },
};

export default function Templates() {
  const { data, error, reload } = usePoll<Catalog>(() => api.templates(), 0);
  const [sel, setSel] = useState<Sel | null>(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!sel && data) setSel({ kind: "template", key: data.templates[0].key });
  }, [data, sel]);

  const match = (s: string) => s.toLowerCase().includes(filter.toLowerCase());

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Templates</h1>
        <p className="text-sm text-slate-500">Every word the customer sees, in English / Hindi / Gujarati. Changes go live immediately (no restart). Placeholders in braces are filled by the bot; the editor refuses edits that would break a message or exceed a WhatsApp limit.</p>
      </div>
      <ErrorBox msg={error} />
      {data && (
        <div className="grid lg:grid-cols-4 gap-4">
          <div className="card p-2 space-y-2 lg:max-h-[80vh] lg:overflow-auto">
            <input className="input w-full" placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
            <Group title="Conversation messages">
              {data.templates.filter((t) => match(t.title + t.key)).map((t) => (
                <Item key={t.key} active={sel?.kind === "template" && sel.key === t.key} onClick={() => setSel({ kind: "template", key: t.key })} title={t.title} edited={LANGS.some((l) => t.langs[l].overridden)} />
              ))}
            </Group>
            <Group title="Menu buttons & labels">
              {data.labels.filter((t) => match(t.title + t.key)).map((t) => (
                <Item key={t.key} active={sel?.kind === "label" && sel.key === t.key} onClick={() => setSel({ kind: "label", key: t.key })} title={t.title} edited={LANGS.some((l) => t.langs[l].overridden)} />
              ))}
            </Group>
            <Group title="Custom keyword replies" action={<button className="btn-ghost text-xs" onClick={() => setSel({ kind: "new-custom" })}>+ New</button>}>
              {data.custom.length === 0 && <div className="text-xs text-slate-400 px-2 py-1">None yet. Example: "timing" → office hours.</div>}
              {data.custom.filter((c) => match(c.title + c.key + c.triggers.join(" "))).map((c) => (
                <Item key={c.key} active={sel?.kind === "custom" && sel.key === c.key} onClick={() => setSel({ kind: "custom", key: c.key })} title={c.title} sub={c.triggers.join(", ")} edited={false} disabled={!c.enabled} />
              ))}
            </Group>
          </div>
          <div className="lg:col-span-3">
            {sel?.kind === "template" && <TextEditor key={"t-" + sel.key} kind="template" item={data.templates.find((t) => t.key === sel.key)!} catalog={data} onSaved={reload} />}
            {sel?.kind === "label" && <TextEditor key={"l-" + sel.key} kind="label" item={data.labels.find((t) => t.key === sel.key)!} catalog={data} onSaved={reload} />}
            {sel?.kind === "custom" && <CustomEditor key={"c-" + sel.key} initial={data.custom.find((c) => c.key === sel.key)!} catalog={data} onSaved={reload} onDeleted={() => { setSel(null); reload(); }} />}
            {sel?.kind === "new-custom" && <CustomEditor key="c-new" initial={null} catalog={data} onSaved={(k) => { reload(); setSel({ kind: "custom", key: k }); }} onDeleted={() => setSel(null)} />}
          </div>
        </div>
      )}
    </div>
  );
}

function Group({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center px-2 pt-2 pb-1 text-[11px] uppercase tracking-wide text-slate-400"><span>{title}</span><span className="ml-auto">{action}</span></div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Item({ title, sub, active, edited, disabled, onClick }: { title: string; sub?: string; active: boolean; edited: boolean; disabled?: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={`w-full text-left rounded-lg px-2 py-1.5 text-sm ${active ? "bg-brand-50 text-brand-700" : "hover:bg-slate-50"} ${disabled ? "opacity-50" : ""}`}>
      <div className="flex items-center gap-1"><span className="truncate">{title}</span>{edited && <span className="ml-auto text-[10px] text-amber-600">edited</span>}</div>
      {sub && <div className="text-[11px] text-slate-400 truncate">{sub}</div>}
    </button>
  );
}

function useDebouncedPreview(kind: string, key: string, lang: string, text: string) {
  const [out, setOut] = useState<{ rendered: string; errors: string[] }>({ rendered: "", errors: [] });
  const t = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(t.current);
    t.current = window.setTimeout(() => {
      api.templatePreview({ kind, key, lang, text }).then(setOut).catch(() => {});
    }, 250);
    return () => window.clearTimeout(t.current);
  }, [kind, key, lang, text]);
  return out;
}

function TextEditor({ kind, item, catalog, onSaved }: { kind: "template" | "label"; item: CatalogTemplate | CatalogLabel; catalog: Catalog; onSaved: () => void }) {
  const [lang, setLang] = useState<Lang>("en");
  const [texts, setTexts] = useState<Record<Lang, string>>({ en: item.langs.en.text, hi: item.langs.hi.text, gu: item.langs.gu.text });
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [hist, setHist] = useState<{ id: number; lang: string; text: string | null; action: string; changed_at: string }[] | null>(null);
  const ta = useRef<HTMLTextAreaElement>(null);
  const preview = useDebouncedPreview(kind, item.key, lang, texts[lang]);
  const tpl = kind === "template" ? (item as CatalogTemplate) : null;
  const lbl = kind === "label" ? (item as CatalogLabel) : null;
  const placeholders = tpl ? tpl.allowed : lbl!.placeholders;
  const dirty = LANGS.some((l) => texts[l] !== item.langs[l].text);
  const maxLen = tpl ? tpl.max_len : lbl!.max_len;

  const insert = (ph: string) => {
    const el = ta.current;
    const token = `{${ph}}`;
    if (!el) return setTexts({ ...texts, [lang]: texts[lang] + token });
    const s = el.selectionStart ?? texts[lang].length;
    const e = el.selectionEnd ?? s;
    const next = texts[lang].slice(0, s) + token + texts[lang].slice(e);
    setTexts({ ...texts, [lang]: next });
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(s + token.length, s + token.length); });
  };

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const changed: Record<string, string> = {};
      LANGS.forEach((l) => { if (texts[l] !== item.langs[l].text) changed[l] = texts[l]; });
      const r = await api.templateSave(kind, item.key, changed);
      setErrors(r.errors || {});
      if (r.ok) { setMsg("Saved. Live now."); onSaved(); }
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };
  const reset = async () => {
    if (!confirm("Restore the built-in default text for all three languages?")) return;
    setBusy(true);
    try { await api.templateReset(kind, item.key); setTexts({ en: item.langs.en.default, hi: item.langs.hi.default, gu: item.langs.gu.default }); setErrors({}); setMsg("Restored defaults."); onSaved(); } finally { setBusy(false); }
  };
  const loadHistory = async () => setHist(await api.templateHistory(kind, item.key));

  return (
    <div className="grid xl:grid-cols-5 gap-4">
      <div className="card xl:col-span-3 space-y-3">
        <div>
          <div className="font-semibold">{item.title} <span className="font-mono text-xs text-slate-400 ml-1">{item.key}</span></div>
          <div className="text-sm text-slate-500">{item.when}</div>
          {tpl?.trilingual && <div className="text-xs text-amber-700 mt-1">This message is always sent in all three languages stacked together.</div>}
          {lbl?.intent && <div className="text-xs text-slate-500 mt-1">The bot must still recognise this label as <b>{lbl.intent}</b>; the editor checks that.</div>}
        </div>
        <div className="flex gap-1">
          {LANGS.map((l) => (
            <button key={l} onClick={() => setLang(l)} className={`btn ${lang === l ? "bg-brand-600 text-white border-brand-600" : "bg-white border-slate-300"}`}>
              {catalog.languages[l]}{item.langs[l].overridden && <span className="ml-1 text-[10px] opacity-80">●</span>}{errors[l]?.length ? <span className="ml-1 text-rose-300">!</span> : null}
            </button>
          ))}
        </div>
        <textarea ref={ta} className="input w-full font-mono text-sm" rows={kind === "template" ? 7 : 2} value={texts[lang]} onChange={(e) => setTexts({ ...texts, [lang]: e.target.value })} dir="auto" />
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <span className="text-slate-500">Placeholders:</span>
          {placeholders.map((p) => (
            <button key={p} className="btn-ghost text-xs px-2 py-0.5 font-mono" onClick={() => insert(p)} title={tpl?.required.includes(p) ? "required" : "optional"}>{`{${p}}`}{tpl?.required.includes(p) ? "*" : ""}</button>
          ))}
          {placeholders.length === 0 && <span className="text-slate-400">none</span>}
          <span className={`ml-auto ${texts[lang].length > maxLen ? "text-rose-600" : "text-slate-400"}`}>{texts[lang].length} / {maxLen}</span>
        </div>
        {(errors[lang] || preview.errors).length > 0 && (
          <ul className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 list-disc ml-4">
            {(errors[lang]?.length ? errors[lang] : preview.errors).map((e, i) => <li key={i}>{e}</li>)}
          </ul>
        )}
        <div className="flex flex-wrap gap-2 items-center">
          <button className="btn-primary" disabled={busy || !dirty || preview.errors.length > 0} onClick={save}>Save</button>
          <button className="btn-ghost" disabled={busy || !LANGS.some((l) => item.langs[l].overridden)} onClick={reset}>Restore default</button>
          <button className="btn-ghost" onClick={loadHistory}>History</button>
          {msg && <span className="text-sm text-slate-600">{msg}</span>}
        </div>
        {hist && (
          <div className="border-t border-slate-100 pt-2 space-y-1 max-h-60 overflow-auto">
            {hist.length === 0 && <div className="text-xs text-slate-400">No history.</div>}
            {hist.map((h) => (
              <div key={h.id} className="text-xs flex gap-2 items-start">
                <span className="text-slate-400 whitespace-nowrap">{fmt(h.changed_at)}</span>
                <Badge>{h.action}</Badge><Badge tone="blue">{h.lang}</Badge>
                <span className="font-mono whitespace-pre-wrap break-words flex-1">{h.text ?? "(default)"}</span>
                {h.text && <button className="btn-ghost text-xs" onClick={() => { setLang(h.lang as Lang); setTexts({ ...texts, [h.lang]: h.text! }); }}>Load</button>}
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="card xl:col-span-2">
        <div className="text-sm font-medium mb-2">Preview ({catalog.languages[lang]}, sample values)</div>
        <div className="rounded-lg bg-[#efeae2] p-3">
          <div className="bg-white rounded-lg px-3 py-2 text-sm shadow-sm max-w-[92%]">
            <div className="whitespace-pre-wrap break-words">{kind === "label" ? <span className="text-slate-500">label → </span> : null}{preview.rendered || "…"}</div>
            {tpl?.menu && SAMPLE_MENUS[tpl.menu] && <MenuPreview options={SAMPLE_MENUS[tpl.menu]} compact />}
          </div>
        </div>
        <div className="text-xs text-slate-500 mt-2">Sample values: {Object.entries(catalog.sample).map(([k, v]) => `{${k}}=${v}`).join("  ")}</div>
        <div className="mt-3 text-xs text-slate-500">
          <div className="font-medium text-slate-700 mb-1">Default text ({catalog.languages[lang]})</div>
          <div className="font-mono whitespace-pre-wrap break-words bg-slate-50 rounded p-2">{item.langs[lang].default}</div>
        </div>
      </div>
    </div>
  );
}

function CustomEditor({ initial, catalog, onSaved, onDeleted }: { initial: CustomReply | null; catalog: Catalog; onSaved: (key: string) => void; onDeleted: () => void }) {
  const [key, setKey] = useState(initial?.key || "");
  const [title, setTitle] = useState(initial?.title || "");
  const [triggers, setTriggers] = useState((initial?.triggers || []).join(", "));
  const [texts, setTexts] = useState<Record<Lang, string>>({ en: initial?.texts.en || "", hi: initial?.texts.hi || "", gu: initial?.texts.gu || "" });
  const [buttons, setButtons] = useState<string[]>(initial?.buttons || []);
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [lang, setLang] = useState<Lang>("en");
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<string | null>(null);

  useEffect(() => {
    if (!initial && title && !key) setKey(title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40));
  }, [title, initial, key]);

  const previewOptions = useMemo(() => buttons.length ? { kind: "buttons" as const, items: buttons.map((b) => ({ title: catalog.button_choices.find((c) => c.key === b)?.label || b, description: "" })), button_text: "", section_title: "", header: "", footer: "" } : null, [buttons, catalog]);

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.customSave({ key, title, triggers: triggers.split(",").map((s) => s.trim()).filter(Boolean), texts, buttons, enabled });
      setErrors(r.errors || []);
      if (r.ok) { setMsg("Saved. Live now."); onSaved(key); }
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };
  const del = async () => {
    if (!initial || !confirm(`Delete custom reply "${initial.title}"?`)) return;
    await api.templateReset("custom", initial.key);
    onDeleted();
  };
  const test = async () => {
    const r = await api.customTest(testText);
    setTestResult(r.match ? `→ "${r.match.title}" would reply` : "→ no custom reply matches (normal flow)");
  };

  return (
    <div className="grid xl:grid-cols-5 gap-4">
      <div className="card xl:col-span-3 space-y-3">
        <div className="font-semibold">{initial ? "Custom reply" : "New custom reply"}</div>
        <p className="text-sm text-slate-500">When a verified customer sends one of the trigger words (and no SO / item code), the bot answers with this text instead of the normal flow. The session is not changed. Checked before greetings and menu words, never before a Yes / No answer or a code.</p>
        <div className="grid sm:grid-cols-2 gap-2">
          <label className="text-sm">Title<input className="input w-full" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Office hours" /></label>
          <label className="text-sm">Key<input className="input w-full font-mono" value={key} disabled={!!initial} onChange={(e) => setKey(e.target.value)} placeholder="office-hours" /></label>
        </div>
        <label className="text-sm block">Trigger words (comma-separated, any language)<input className="input w-full" value={triggers} onChange={(e) => setTriggers(e.target.value)} placeholder="timing, office hours, समय, સમય" /></label>
        <div className="flex gap-1">
          {LANGS.map((l) => <button key={l} onClick={() => setLang(l)} className={`btn ${lang === l ? "bg-brand-600 text-white border-brand-600" : "bg-white border-slate-300"}`}>{catalog.languages[l]}{texts[l] ? "" : <span className="ml-1 text-[10px] opacity-70">(empty)</span>}</button>)}
        </div>
        <textarea className="input w-full font-mono text-sm" rows={5} value={texts[lang]} onChange={(e) => setTexts({ ...texts, [lang]: e.target.value })} dir="auto" placeholder="Our office is open Mon–Sat 9:00–18:00. For urgent help call {support}." />
        <div className="text-xs text-slate-500">Only <span className="font-mono">{"{support}"}</span> is available as a placeholder. Empty languages fall back to English.</div>
        <div className="text-sm">
          <div className="font-medium mb-1">Buttons under the reply (max 3)</div>
          <div className="flex flex-wrap gap-2">
            {catalog.button_choices.map((c) => (
              <label key={c.key} className="flex items-center gap-1 text-sm"><input type="checkbox" checked={buttons.includes(c.key)} onChange={(e) => setButtons(e.target.checked ? [...buttons, c.key].slice(0, 3) : buttons.filter((b) => b !== c.key))} />{c.label}</label>
            ))}
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />Enabled</label>
        {errors.length > 0 && <ul className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 list-disc ml-4">{errors.map((e, i) => <li key={i}>{e}</li>)}</ul>}
        <div className="flex flex-wrap gap-2 items-center">
          <button className="btn-primary" disabled={busy} onClick={save}>Save</button>
          {initial && <button className="btn-ghost text-rose-700" disabled={busy} onClick={del}>Delete</button>}
          {msg && <span className="text-sm text-slate-600">{msg}</span>}
        </div>
        {initial && (
          <div className="border-t border-slate-100 pt-2 flex gap-2 items-center">
            <input className="input flex-1" placeholder="Type a customer message to test the triggers…" value={testText} onChange={(e) => setTestText(e.target.value)} />
            <button className="btn-ghost" onClick={test}>Test</button>
            {testResult && <span className="text-xs text-slate-600">{testResult}</span>}
          </div>
        )}
      </div>
      <div className="card xl:col-span-2">
        <div className="text-sm font-medium mb-2">Preview ({catalog.languages[lang]})</div>
        <div className="rounded-lg bg-[#efeae2] p-3">
          <div className="bg-white rounded-lg px-3 py-2 text-sm shadow-sm max-w-[92%]">
            <div className="whitespace-pre-wrap break-words">{(texts[lang] || texts.en || "…").replace("{support}", String(catalog.sample.support))}</div>
            {previewOptions && <MenuPreview options={previewOptions} compact />}
          </div>
        </div>
      </div>
    </div>
  );
}
