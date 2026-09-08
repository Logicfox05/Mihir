import { ReactNode, useState } from "react";
import { ConnField } from "./api";

/** Small building blocks shared by the two connection forms. */

export function Row({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <div className="font-medium text-slate-700">{label}</div>
      {children}
      {hint && <div className="text-xs text-slate-500 mt-0.5">{hint}</div>}
    </label>
  );
}

export function Text({ value, onChange, placeholder, mono, error }: { value: string; onChange: (v: string) => void; placeholder?: string; mono?: boolean; error?: string }) {
  return (
    <>
      <input className={`input w-full ${mono ? "font-mono text-xs" : ""} ${error ? "border-rose-400" : ""}`} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      {error && <div className="text-xs text-rose-600 mt-0.5">{error}</div>}
    </>
  );
}

export function Num({ value, onChange, error }: { value: number; onChange: (v: number) => void; error?: string }) {
  return (
    <>
      <input type="number" className={`input w-28 ${error ? "border-rose-400" : ""}`} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      {error && <div className="text-xs text-rose-600 mt-0.5">{error}</div>}
    </>
  );
}

export function Choice({ value, choices, onChange, labels }: { value: string; choices: string[]; onChange: (v: string) => void; labels?: Record<string, string> }) {
  return (
    <select className="input w-full" value={value} onChange={(e) => onChange(e.target.value)}>
      {choices.map((c) => <option key={c} value={c}>{labels?.[c] || c}</option>)}
    </select>
  );
}

/** A stored password: shown as dots until the user chooses to replace it. */
export function Secret({ field, value, onChange, placeholder }: { field: ConnField | undefined; value: string | null; onChange: (v: string | null) => void; placeholder?: string }) {
  const [editing, setEditing] = useState(false);
  const isSet = !!field?.is_set;
  if (!editing && isSet && value === null) {
    return (
      <div className="flex items-center gap-2">
        <input className="input flex-1 font-mono text-xs" value={String(field?.value ?? "••••")} disabled />
        <button type="button" className="btn-ghost text-xs" onClick={() => { setEditing(true); onChange(""); }}>Change</button>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <input type="password" className="input flex-1" autoComplete="new-password" placeholder={placeholder || (isSet ? "enter the new value" : "")}
        value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
      {isSet && <button type="button" className="btn-ghost text-xs" onClick={() => { setEditing(false); onChange(null); }}>Keep saved</button>}
    </div>
  );
}

/** Pick a column name from the ones found in the file, or type one. */
export function ColumnPicker({ value, headers, onChange, required, error }: { value: string; headers: string[]; onChange: (v: string) => void; required?: boolean; error?: string }) {
  const id = "cols-" + Math.abs(headers.join("|").split("").reduce((a, c) => a + c.charCodeAt(0), 0));
  return (
    <>
      <input className={`input w-full text-sm ${error || (required && !value) ? "border-rose-400" : ""}`} list={id} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={headers.length ? "choose or type the column name" : "column name in the file"} />
      <datalist id={id}>{headers.map((h) => <option key={h} value={h} />)}</datalist>
      {error && <div className="text-xs text-rose-600 mt-0.5">{error}</div>}
    </>
  );
}

export function SourceCard({ active, title, note, onClick }: { active: boolean; title: string; note: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className={`text-left rounded-xl border p-3 transition ${active ? "border-brand-500 bg-brand-50 ring-2 ring-brand-200" : "border-slate-300 bg-white hover:bg-slate-50"}`}>
      <div className="font-medium text-sm">{title}</div>
      <div className="text-xs text-slate-500 mt-0.5">{note}</div>
    </button>
  );
}

export function ResultBox({ ok, children }: { ok: boolean | null; children: ReactNode }) {
  if (ok === null) return null;
  return (
    <div className={`rounded-lg border px-3 py-2 text-sm ${ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-rose-50 border-rose-200 text-rose-700"}`}>
      {children}
    </div>
  );
}
