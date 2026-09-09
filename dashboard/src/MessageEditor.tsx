import { useEffect, useMemo, useRef, useState } from "react";
import { api, Catalog, CatalogLabel, CatalogTemplate, Lang, MenuOptions, TestSendResult } from "./api";
import MenuPreview from "./MenuPreview";
import { Badge, fmt } from "./ui";

const LANGS: Lang[] = ["en", "hi", "gu"];
const PHONE_KEY = "test_send_phone";

/** Text of a menu label in one language, with {so}/{n} filled in for the preview. */
export function labelText(cat: Catalog, key: string, lang: Lang, vars: Record<string, string> = {}): string {
  const l = cat.labels.find((x) => x.key === key);
  let t = l ? l.langs[lang].text : key;
  for (const [k, v] of Object.entries(vars)) t = t.split(`{${k}}`).join(v);
  return t;
}

/** The menu that will hang under this message, using the real (edited) labels and sample data. */
export function previewOptions(cat: Catalog, menu: string, buttons: string[], lang: Lang): MenuOptions | null {
  const mk = (kind: "buttons" | "list", items: { title: string; description: string }[], extra: Partial<MenuOptions> = {}): MenuOptions => ({
    kind, items, button_text: "", section_title: "", header: "", footer: "", ...extra,
  });
  const asButtons = cat.so_menu_style !== "list";  // Settings -> Conversation: buttons when 3 or fewer, else a list
  if (menu === "language")
    return mk("buttons", ["lang_en", "lang_hi", "lang_gu"].map((k) => ({ title: labelText(cat, k, lang), description: "" })));
  if (menu === "so_options")
    return asButtons
      ? mk("buttons", [{ title: "SO 45240", description: "" }, { title: "SO 45231", description: "" }])
      : mk("list", [
        { title: "SO 45240", description: `${labelText(cat, "n_items", lang, { n: "3" })} · PO PO-8801` },
        { title: "SO 45231", description: `${labelText(cat, "one_item", lang)} · PO PO-7781` },
      ], { button_text: labelText(cat, "select_so", lang), section_title: labelText(cat, "your_orders", lang) });
  if (menu === "fg_options") {
    const codes = ["FG-2001", "FG-2002", "FG-2003"].map((t) => ({ title: t, description: "" }));
    return asButtons ? mk("buttons", codes) : mk("list", codes, {
      button_text: labelText(cat, "select_item", lang), section_title: labelText(cat, "items_of_so", lang, { so: "45240" }), footer: labelText(cat, "type_hint", lang),
    });
  }
  if (menu === "confirm")
    return mk("buttons", [{ title: labelText(cat, "yes", lang), description: "" }, { title: labelText(cat, "no", lang), description: "" }]);
  if (buttons.length) return mk("buttons", buttons.map((b) => ({ title: labelText(cat, b, lang), description: "" })));
  return null;
}

/** Explains the menu under a message in plain words (for the flow map and the editor). */
export function menuNote(menu: string, cat?: Catalog): string {
  const list = cat?.so_menu_style === "list";
  if (menu === "language") return "language buttons";
  if (menu === "so_options") return list ? "order list" : "order buttons / list";
  if (menu === "fg_options") return list ? "item list" : "item buttons / list";
  if (menu === "confirm") return "Yes / No";
  return "";
}

interface Props {
  kind: "template" | "label";
  item: CatalogTemplate | CatalogLabel;
  catalog: Catalog;
  onSaved: () => void;
}

export default function MessageEditor({ kind, item, catalog, onSaved }: Props) {
  const tpl = kind === "template" ? (item as CatalogTemplate) : null;
  const lbl = kind === "label" ? (item as CatalogLabel) : null;

  const neutral = !!tpl?.neutral;  // one text for everyone (sent before the language is known)
  const [lang, setLang] = useState<Lang>("en");
  const [baseline, setBaseline] = useState<Record<Lang, string>>({ en: item.langs.en.text, hi: item.langs.hi.text, gu: item.langs.gu.text });
  const [texts, setTexts] = useState<Record<Lang, string>>(baseline);
  const [buttons, setButtons] = useState<string[]>(tpl?.buttons ?? []);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [hist, setHist] = useState<{ id: number; lang: string; text: string | null; action: string; changed_at: string }[] | null>(null);
  const [phone, setPhone] = useState(() => { try { return localStorage.getItem(PHONE_KEY) || ""; } catch { return ""; } });
  const [test, setTest] = useState<TestSendResult | null>(null);
  const ta = useRef<HTMLTextAreaElement>(null);

  // live validation + rendered preview from the server (debounced, stale responses discarded)
  const [preview, setPreview] = useState<{ rendered: string; errors: string[] }>({ rendered: "", errors: [] });
  const seq = useRef(0);
  useEffect(() => {
    const mine = ++seq.current;
    const t = window.setTimeout(() => {
      api.templatePreview({ kind, key: item.key, lang, text: texts[lang] })
        .then((r) => { if (mine === seq.current) setPreview(r); })
        .catch(() => { if (mine === seq.current) setPreview({ rendered: texts[lang], errors: [] }); });
    }, 250);
    return () => window.clearTimeout(t);
  }, [kind, item.key, lang, texts]);

  const placeholders = tpl ? tpl.allowed : lbl!.placeholders;
  const maxLen = tpl ? tpl.max_len : lbl!.max_len;
  const textDirty = LANGS.some((l) => texts[l] !== baseline[l]);
  const buttonsDirty = !!tpl && JSON.stringify(buttons) !== JSON.stringify(tpl.buttons);
  const opts = useMemo(() => (tpl ? previewOptions(catalog, tpl.menu, buttons, lang) : null), [catalog, tpl, buttons, lang]);

  const insert = (ph: string) => {
    const el = ta.current;
    const token = `{${ph}}`;
    if (!el) return setTexts({ ...texts, [lang]: texts[lang] + token });
    const s = el.selectionStart ?? texts[lang].length;
    const e = el.selectionEnd ?? s;
    setTexts({ ...texts, [lang]: texts[lang].slice(0, s) + token + texts[lang].slice(e) });
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(s + token.length, s + token.length); });
  };

  const save = async () => {
    setBusy(true); setMsg(null); setTest(null);
    try {
      const next: Record<Lang, string> = { ...texts };
      if (kind === "label") LANGS.forEach((l) => { next[l] = next[l].trim(); });
      if (neutral) { next.hi = next.en; next.gu = next.en; }  // one text for everyone
      const changed: Record<string, string> = {};
      LANGS.forEach((l) => { if (next[l] !== baseline[l]) changed[l] = next[l]; });
      let ok = true;
      if (Object.keys(changed).length) {
        const r = await api.templateSave(kind, item.key, changed);
        setErrors(r.errors || {});
        ok = r.ok;
        if (r.ok) { setTexts(next); setBaseline(next); }
      } else setErrors({});
      if (ok && buttonsDirty) {
        const rb = await api.templateButtons(item.key, buttons);
        if (!rb.ok) { setMsg(rb.errors.join("; ")); ok = false; }
      }
      if (ok) { setMsg("Saved - customers see this from the next message."); onSaved(); }
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };

  const restore = async () => {
    if (!confirm("Restore the built-in text for all three languages?")) return;
    setBusy(true); setMsg(null);
    try {
      await api.templateReset(kind, item.key);
      if (tpl?.buttons_editable && tpl.buttons_overridden) await api.templateReset("buttons", item.key);
      const def: Record<Lang, string> = { en: item.langs.en.default, hi: item.langs.hi.default, gu: item.langs.gu.default };
      setTexts(def); setBaseline(def); setErrors({});
      if (tpl) setButtons(tpl.buttons_default);
      setMsg("Restored the built-in text.");
      onSaved();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };

  const sendTest = async () => {
    setBusy(true); setMsg(null); setTest(null);
    try { localStorage.setItem(PHONE_KEY, phone); } catch { /* private mode */ }
    try {
      setTest(await api.templateTestSend({ kind: "template", key: item.key, lang, phone, text: texts[lang] }));
    } catch (e) { setTest({ ok: false, detail: (e as Error).message }); } finally { setBusy(false); }
  };

  const shownErrors = errors[lang]?.length ? errors[lang] : preview.errors;
  const otherLangErrors = LANGS.filter((l) => l !== lang && errors[l]?.length);

  return (
    <div className="space-y-3">
      <div>
        <div className="font-semibold">{item.title}</div>
        <div className="text-sm text-slate-500">{item.when}</div>
        {tpl?.trilingual && <div className="text-xs text-amber-700 mt-1">Always sent in all three languages together.</div>}
        {neutral && <div className="text-xs text-amber-700 mt-1">Sent before the customer has chosen a language, so this one text goes to everyone. Mix languages freely.</div>}
        {tpl?.menu === "so_options" && <div className="text-xs text-slate-500 mt-1">Shown with the customer's own SO numbers: as buttons when there are 3 or fewer, otherwise as a list. Change this under Settings → Conversation.</div>}
        {tpl?.menu === "fg_options" && <div className="text-xs text-slate-500 mt-1">Shown with the items of the chosen SO: as buttons when there are 3 or fewer, otherwise as a list.</div>}
        {lbl?.intent && <div className="text-xs text-slate-500 mt-1">When a customer taps this button the bot reads it as <b>{lbl.intent}</b>. Rename it freely - the bot follows the new name.</div>}
      </div>

      <div className="flex gap-1">
        {(neutral ? (["en"] as Lang[]) : LANGS).map((l) => (
          <button key={l} onClick={() => setLang(l)} className={`btn ${lang === l ? "bg-brand-600 text-white border-brand-600" : "bg-white border-slate-300"}`}>
            {neutral ? "All customers" : catalog.languages[l]}
            {item.langs[l].overridden && <span className="ml-1 text-[10px] opacity-80">&#9679;</span>}
            {errors[l]?.length ? <span className="ml-1 text-rose-500">!</span> : null}
          </button>
        ))}
      </div>

      <textarea ref={ta} className="input w-full font-sans text-sm" rows={kind === "template" ? 6 : 2} dir="auto"
        value={texts[lang]} onChange={(e) => setTexts({ ...texts, [lang]: e.target.value })} />

      <div className="flex flex-wrap items-center gap-1 text-xs">
        {placeholders.length > 0 && <span className="text-slate-500">Insert:</span>}
        {placeholders.map((p) => (
          <button key={p} className="btn-ghost text-xs px-2 py-0.5" onClick={() => insert(p)}
            title={`Puts the real value in the message. Sample: ${catalog.sample[p] ?? p}`}>
            + {catalog.placeholder_labels[p] || p}{tpl?.required.includes(p) ? " *" : ""}
          </button>
        ))}
        <span className={`ml-auto ${texts[lang].length > maxLen ? "text-rose-600" : "text-slate-400"}`}>{texts[lang].length} / {maxLen}</span>
      </div>

      {tpl?.buttons_editable && (
        <div>
          <div className="text-sm font-medium mb-1">Buttons under this message <span className="text-xs font-normal text-slate-500">(max 3)</span></div>
          <div className="flex flex-wrap gap-2">
            {catalog.button_choices.map((c) => {
              const on = buttons.includes(c.key);
              return (
                <button key={c.key} onClick={() => setButtons(on ? buttons.filter((b) => b !== c.key) : buttons.length >= 3 ? buttons : [...buttons, c.key])}
                  disabled={!on && buttons.length >= 3}
                  className={`btn text-sm ${on ? "bg-sky-50 border-sky-400 text-sky-700" : "bg-white border-slate-300 text-slate-600"}`}>
                  {on ? "✓ " : "+ "}{labelText(catalog, c.key, lang)}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {tpl && !tpl.buttons_editable && tpl.menu === "confirm" && (
        <div className="text-xs text-slate-500">The Yes / No buttons are required here so the bot can understand the answer. You can rename them under "Menu buttons &amp; labels".</div>
      )}
      {tpl && !tpl.buttons_editable && tpl.menu === "language" && (
        <div className="text-xs text-slate-500">The three language buttons are fixed here. You can rename them under "Menu buttons &amp; labels".</div>
      )}

      <div>
        <div className="text-sm font-medium mb-1">What the customer sees</div>
        <div className="rounded-lg bg-[#efeae2] p-3">
          <div className="bg-white rounded-lg px-3 py-2 text-sm shadow-sm max-w-[92%]">
            <div className="whitespace-pre-wrap break-words">{preview.rendered || texts[lang] || "…"}</div>
            {opts && <MenuPreview options={opts} compact />}
          </div>
        </div>
        <div className="text-[11px] text-slate-500 mt-1">Sample values are shown here; real orders appear in the real message.</div>
      </div>

      {shownErrors.length > 0 && (
        <ul className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 list-disc ml-4">
          {shownErrors.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
      {!neutral && otherLangErrors.length > 0 && (
        <div className="text-sm text-amber-700">Also fix: {otherLangErrors.map((l) => catalog.languages[l]).join(", ")}.</div>
      )}

      <div className="flex flex-wrap gap-2 items-center">
        <button className="btn-primary" disabled={busy || (!textDirty && !buttonsDirty) || preview.errors.length > 0} onClick={save}>Save</button>
        <button className="btn-ghost" disabled={busy || !(LANGS.some((l) => item.langs[l].overridden) || tpl?.buttons_overridden)} onClick={restore}>Restore built-in</button>
        <button className="btn-ghost" onClick={async () => { try { setHist(await api.templateHistory(kind, item.key)); } catch (e) { setMsg((e as Error).message); } }}>History</button>
        {msg && <span className="text-sm text-slate-600">{msg}</span>}
      </div>

      {kind === "template" && (
        <div className="border-t border-slate-100 pt-3">
          <div className="text-sm font-medium mb-1">Send this to a WhatsApp number to check it</div>
          <div className="flex flex-wrap gap-2 items-center">
            <input className="input font-mono" placeholder="91XXXXXXXXXX" value={phone} onChange={(e) => setPhone(e.target.value)} />
            <button className="btn-ghost" disabled={busy || !phone.trim()} onClick={sendTest}>Send test</button>
            <span className="text-xs text-slate-500">Sends exactly what you see above, including unsaved edits.</span>
          </div>
          {test && (
            <div className={`mt-2 text-sm rounded-lg px-3 py-2 ${test.ok ? (test.mocked ? "bg-amber-50 text-amber-800 border border-amber-200" : "bg-emerald-50 text-emerald-800 border border-emerald-200") : "bg-rose-50 text-rose-700 border border-rose-200"}`}>
              {test.detail}
            </div>
          )}
        </div>
      )}

      {hist && (
        <div className="border-t border-slate-100 pt-2 space-y-1 max-h-56 overflow-auto">
          {hist.length === 0 && <div className="text-xs text-slate-400">No changes yet.</div>}
          {hist.map((h) => (
            <div key={h.id} className="text-xs flex gap-2 items-start">
              <span className="text-slate-400 whitespace-nowrap">{fmt(h.changed_at)}</span>
              <Badge>{h.action}</Badge><Badge tone="blue">{h.lang}</Badge>
              <span className="whitespace-pre-wrap break-words flex-1">{h.text ?? "(built-in)"}</span>
              {h.text && LANGS.includes(h.lang as Lang) && (
                <button className="btn-ghost text-xs" onClick={() => { setLang(h.lang as Lang); setTexts({ ...texts, [h.lang]: h.text! }); }}>Load</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
