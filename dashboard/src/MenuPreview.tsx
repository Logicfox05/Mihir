import { MenuOptions, Selection } from "./api";

/** Renders the interactive options exactly as WhatsApp would: reply buttons under the bubble, or a
 *  "list" button that expands into rows. onPick simulates the customer tapping one. */
export default function MenuPreview({ options, onPick, disabled, compact }: { options: MenuOptions; onPick?: (s: Selection) => void; disabled?: boolean; compact?: boolean }) {
  if (!options || !options.items?.length) return null;
  const pick = (title: string, description = "") => onPick && onPick({ kind: options.kind, title, description });
  if (options.kind === "buttons") {
    return (
      <div className={`flex flex-wrap gap-1 ${compact ? "mt-1" : "mt-2"}`}>
        {options.items.map((o) => (
          <button key={o.title} type="button" disabled={disabled || !onPick} onClick={() => pick(o.title)}
            className={`rounded-lg border border-sky-300 bg-white text-sky-700 font-medium ${compact ? "text-[11px] px-2 py-0.5" : "text-sm px-3 py-1.5"} hover:bg-sky-50 disabled:opacity-60`}>
            {o.title}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className={compact ? "mt-1" : "mt-2"}>
      <div className={`text-sky-700 font-medium ${compact ? "text-[11px]" : "text-sm"}`}>☰ {options.button_text}</div>
      {options.section_title && <div className="text-[10px] uppercase tracking-wide text-slate-400 mt-1">{options.section_title}</div>}
      <div className="divide-y divide-slate-100 border border-slate-200 rounded-lg mt-1 bg-white">
        {options.items.map((o) => (
          <button key={o.title} type="button" disabled={disabled || !onPick} onClick={() => pick(o.title, o.description)}
            className={`w-full text-left ${compact ? "px-2 py-1" : "px-3 py-2"} hover:bg-sky-50 disabled:opacity-60`}>
            <div className={`font-medium ${compact ? "text-[11px]" : "text-sm"}`}>{o.title}</div>
            {o.description && <div className="text-[11px] text-slate-500">{o.description}</div>}
          </button>
        ))}
      </div>
      {options.footer && <div className="text-[10px] text-slate-400 mt-1">{options.footer}</div>}
    </div>
  );
}
