import { api } from "../api";
import { Diff, Empty, ErrorBox, fmt, usePoll } from "../ui";

function reason(a: string, b: string): string {
  if (a === b) return "identical?";
  if (a.trim() === b.trim()) return "leading/trailing whitespace";
  if (a.toLowerCase() === b.toLowerCase()) return "letter case";
  if (a.replace(/\s+/g, " ") === b.replace(/\s+/g, " ")) return "inner whitespace";
  if (a.normalize("NFKC") === b.normalize("NFKC")) return "unicode form (NBSP / composed chars)";
  return "different text";
}

export default function Mismatches() {
  const { data, error } = usePoll(() => api.mismatches(), 10000);
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Name mismatches</h1>
        <p className="text-sm text-slate-500">A customer asked for an SO that exists, but the API's customer name is not byte-identical to the Excel name. The customer got the verification-failed message. Fix the name in SAP or the API source.</p>
      </div>
      <ErrorBox msg={error} />
      <div className="card p-0 overflow-auto">
        {!data || data.length === 0 ? (
          <Empty>No mismatches logged. 🎉</Empty>
        ) : (
          <table className="w-full">
            <thead><tr><th className="th">When</th><th className="th">Phone</th><th className="th">SO</th><th className="th">Excel vs API name</th><th className="th">Likely cause</th></tr></thead>
            <tbody>
              {data.map((m) => (
                <tr key={m.id}>
                  <td className="td text-xs text-slate-500 whitespace-nowrap">{fmt(m.created_at)}</td>
                  <td className="td font-mono text-xs">{m.phone}</td>
                  <td className="td font-mono text-xs">{m.so_no}</td>
                  <td className="td"><Diff a={m.excel_name || ""} b={m.api_name || ""} /></td>
                  <td className="td text-sm">{reason(m.excel_name || "", m.api_name || "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
