import { useMemo, useState } from "react";
import { CatalogTemplate, FlowEdge, FlowNode, Lang } from "./api";
import { menuNote } from "./MessageEditor";

const NODE_W = 250;
const NODE_H = 128;
const GAP_X = 320;
const GAP_Y = 182;
const PAD = 24;

const nx = (col: number) => PAD + col * GAP_X;
const ny = (row: number) => PAD + row * GAP_Y;

interface Props {
  nodes: FlowNode[];
  edges: FlowEdge[];
  templates: CatalogTemplate[];
  lang: Lang;
  labelOf: (key: string) => string;
  selected: string | null;
  onSelect: (key: string) => void;
}

/** The conversation drawn as a map: grey bubbles are what the customer sends,
 *  white bubbles are the bot's messages — click one to edit it. */
export default function FlowCanvas({ nodes, edges, templates, lang, labelOf, selected, onSelect }: Props) {
  const [zoom, setZoom] = useState(1);
  const byKey = useMemo(() => Object.fromEntries(templates.map((t) => [t.key, t])), [templates]);
  const pos = useMemo(() => Object.fromEntries(nodes.map((n) => [n.key, { x: nx(n.col), y: ny(n.row) }])), [nodes]);

  const maxCol = Math.max(...nodes.map((n) => n.col));
  const maxRow = Math.max(...nodes.map((n) => n.row));
  const W = PAD * 2 + maxCol * GAP_X + NODE_W;
  const H = PAD * 2 + maxRow * GAP_Y + NODE_H + 50;

  const paths = edges.map((e) => {
    const a = pos[e.from];
    const b = pos[e.to];
    if (!a || !b) return null;
    const forward = b.x > a.x;
    if (forward) {
      const sx = a.x + NODE_W;
      const sy = a.y + NODE_H / 2;
      const tx = b.x;
      const ty = b.y + NODE_H / 2;
      const c = Math.max(40, Math.min(90, (tx - sx) / 2 + 20));
      return { e, d: `M ${sx} ${sy} C ${sx + c} ${sy}, ${tx - c} ${ty}, ${tx} ${ty}`, lx: (sx + tx) / 2, ly: (sy + ty) / 2 - 8, back: false };
    }
    const sx = a.x + NODE_W / 2;
    const sy = a.y + NODE_H;
    const tx = b.x + NODE_W / 2;
    const ty = b.y + NODE_H;
    const lane = Math.max(a.y, b.y) + NODE_H + 42;
    return { e, d: `M ${sx} ${sy} C ${sx} ${lane}, ${tx} ${lane}, ${tx} ${ty}`, lx: (sx + tx) / 2, ly: lane - 6, back: true };
  });

  return (
    <div className="card p-0 overflow-auto relative" style={{ maxHeight: "72vh" }}>
      <div className="sticky top-0 left-0 z-20 flex items-center gap-2 px-3 py-1.5 bg-white/90 backdrop-blur border-b border-slate-200 text-xs">
        <span className="inline-flex items-center gap-1"><i className="inline-block w-3 h-3 rounded bg-slate-200 border border-slate-300" /> customer sends</span>
        <span className="inline-flex items-center gap-1"><i className="inline-block w-3 h-3 rounded bg-white border border-slate-300" /> bot replies — click to edit</span>
        <span className="inline-flex items-center gap-1"><i className="inline-block w-2 h-2 rounded-full bg-amber-500" /> edited</span>
        <span className="ml-auto flex items-center gap-1">
          <button className="btn-ghost px-2 py-0.5" onClick={() => setZoom((z) => Math.max(0.55, +(z - 0.15).toFixed(2)))}>−</button>
          <span className="w-10 text-center tabular-nums">{Math.round(zoom * 100)}%</span>
          <button className="btn-ghost px-2 py-0.5" onClick={() => setZoom((z) => Math.min(1.2, +(z + 0.15).toFixed(2)))}>+</button>
        </span>
      </div>
      <div style={{ width: W * zoom, height: H * zoom }}>
        <div style={{ width: W, height: H, transform: `scale(${zoom})`, transformOrigin: "top left", position: "relative" }}>
          <svg width={W} height={H} className="absolute inset-0 pointer-events-none">
            <defs>
              <marker id="fc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
              </marker>
            </defs>
            {paths.map((p, i) =>
              p ? (
                <g key={i}>
                  <path d={p.d} fill="none" stroke={p.back ? "#cbd5e1" : "#94a3b8"} strokeWidth={1.5} strokeDasharray={p.back ? "4 3" : undefined} markerEnd="url(#fc-arrow)" />
                  <text x={p.lx} y={p.ly} textAnchor="middle" className="fill-slate-500" style={{ fontSize: 10 }} paintOrder="stroke" stroke="#fff" strokeWidth={3.5}>
                    {p.e.label}
                  </text>
                </g>
              ) : null,
            )}
          </svg>

          {nodes.map((n) => {
            const p = pos[n.key];
            const t = byKey[n.key];
            const isBot = n.kind === "bot";
            const edited = !!t && (["en", "hi", "gu"] as Lang[]).some((l) => t.langs[l].overridden);
            const text = isBot && t ? t.langs[lang].text : n.text || "";
            const buttons = isBot && t ? t.buttons : [];
            const active = selected === n.key;
            return (
              <div
                key={n.key}
                onClick={() => isBot && onSelect(n.key)}
                role={isBot ? "button" : undefined}
                tabIndex={isBot ? 0 : undefined}
                onKeyDown={(ev) => { if (isBot && (ev.key === "Enter" || ev.key === " ")) { ev.preventDefault(); onSelect(n.key); } }}
                className={`absolute rounded-xl border p-2.5 text-left transition shadow-sm ${
                  isBot
                    ? `bg-white cursor-pointer hover:shadow-md ${active ? "border-brand-500 ring-2 ring-brand-200" : "border-slate-300"}`
                    : "bg-slate-100 border-slate-300 border-dashed"
                }`}
                style={{ left: p.x, top: p.y, width: NODE_W, height: NODE_H }}
              >
                <div className="flex items-center gap-1 mb-1">
                  <span className="text-[10px] uppercase tracking-wide text-slate-500 truncate">{isBot ? n.title : `👤 ${n.title}`}</span>
                  {edited && <span className="ml-auto w-2 h-2 rounded-full bg-amber-500 shrink-0" title="edited" />}
                </div>
                <div className={`text-[11px] leading-snug ${isBot ? "text-slate-700" : "text-slate-500 italic"}`} style={{ display: "-webkit-box", WebkitLineClamp: buttons.length ? 3 : 5, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                  {text}
                </div>
                {buttons.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {buttons.map((b) => (
                      <span key={b} className="text-[10px] rounded border border-sky-300 text-sky-700 px-1.5 py-0.5 bg-sky-50 truncate max-w-full">{labelOf(b)}</span>
                    ))}
                  </div>
                )}
                {isBot && t && t.menu && (
                  <div className="absolute bottom-1.5 right-2 text-[10px] text-slate-400">☰ {menuNote(t.menu)}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
