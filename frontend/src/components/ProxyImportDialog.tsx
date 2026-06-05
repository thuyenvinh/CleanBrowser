import { useMemo, useState } from "react";
import { Loader2, Upload, X } from "lucide-react";
import type { ProxyCreateInput } from "../lib/proxy";

interface ProxyImportDialogProps {
  onClose: () => void;
  onImport: (
    inputs: ProxyCreateInput[],
  ) => Promise<
    | { created: number; failed: { index: number; error: string }[] }
    | undefined
  >;
}

interface ParsedRow {
  row: ProxyCreateInput | null;
  error: string | null;
  raw: string;
}

const CSV_HEADERS = [
  "name",
  "type",
  "host",
  "port",
  "username",
  "password",
  "provider",
] as const;

function parseColonLine(line: string, idx: number): ParsedRow {
  // host:port:user:pass — user/pass optional. 2-4 colon-separated parts.
  const parts = line.split(":");
  if (parts.length < 2 || parts.length > 4) {
    return {
      row: null,
      raw: line,
      error: `Expected host:port[:user:pass], got ${parts.length} parts`,
    };
  }
  const [host, portStr, username, password] = parts;
  if (!host) {
    return { row: null, raw: line, error: "Missing host" };
  }
  if (!portStr) {
    return { row: null, raw: line, error: "Missing port" };
  }
  const port = Number(portStr);
  if (!Number.isInteger(port)) {
    return {
      row: null,
      raw: line,
      error: `Invalid port "${portStr}" (not a number)`,
    };
  }
  if (port < 1 || port > 65535) {
    return {
      row: null,
      raw: line,
      error: `Invalid port ${port} (must be 1-65535)`,
    };
  }
  return {
    raw: line,
    error: null,
    row: {
      name: `proxy-${idx + 1}`,
      type: "http",
      host,
      port,
      username: username || null,
      password: password || null,
      provider: "manual",
    },
  };
}

function parseCsvLine(
  line: string,
  header: string[],
  idx: number,
): ParsedRow {
  const cells = line.split(",").map((c) => c.trim());
  const obj: Record<string, string> = {};
  header.forEach((h, i) => {
    obj[h] = cells[i] ?? "";
  });
  const host = obj.host;
  if (!host) {
    return { row: null, raw: line, error: "Missing host" };
  }
  if (!obj.port) {
    return { row: null, raw: line, error: "Missing port" };
  }
  const port = Number(obj.port);
  if (!Number.isInteger(port)) {
    return {
      row: null,
      raw: line,
      error: `Invalid port "${obj.port}" (not a number)`,
    };
  }
  if (port < 1 || port > 65535) {
    return {
      row: null,
      raw: line,
      error: `Invalid port ${port} (must be 1-65535)`,
    };
  }
  const type = (obj.type || "http").toLowerCase();
  if (!["http", "https", "socks4", "socks5"].includes(type)) {
    return {
      row: null,
      raw: line,
      error: `Unsupported type "${obj.type}"`,
    };
  }
  return {
    raw: line,
    error: null,
    row: {
      name: obj.name || `proxy-${idx + 1}`,
      type,
      host,
      port,
      username: obj.username || null,
      password: obj.password || null,
      provider: obj.provider || "manual",
    },
  };
}

function detectMode(firstLine: string): "csv" | "colon" {
  const lower = firstLine.toLowerCase();
  const looksLikeHeader =
    CSV_HEADERS.some((h) => lower.includes(h)) && lower.includes(",");
  return looksLikeHeader ? "csv" : "colon";
}

function parseInput(
  text: string,
  override?: "csv" | "colon" | "auto",
): { rows: ParsedRow[]; mode: "csv" | "colon" } {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  const first = lines[0];
  if (!first) return { rows: [], mode: "colon" };

  const mode =
    override && override !== "auto" ? override : detectMode(first);

  if (mode === "csv") {
    const header = first.split(",").map((c) => c.trim().toLowerCase());
    const rows = lines
      .slice(1)
      .map((l, i) => parseCsvLine(l, header, i));
    return { rows, mode };
  }
  return {
    mode,
    rows: lines.map((l, i) => parseColonLine(l, i)),
  };
}

export function ProxyImportDialog({ onClose, onImport }: ProxyImportDialogProps) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"auto" | "csv" | "colon">("auto");
  const [importing, setImporting] = useState(false);
  const [summary, setSummary] = useState<
    | { created: number; failed: { index: number; error: string }[] }
    | null
  >(null);

  const parsed = useMemo(() => parseInput(text, mode), [text, mode]);
  const validRows = parsed.rows.filter((r) => r.row != null);
  const invalidCount = parsed.rows.length - validRows.length;

  const handleImport = async () => {
    if (validRows.length === 0) return;
    setImporting(true);
    try {
      const result = await onImport(
        validRows.map((r) => r.row as ProxyCreateInput),
      );
      if (result) setSummary(result);
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-surface-1 border border-border rounded-lg shadow-xl w-[680px] max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div className="flex items-center gap-2">
            <Upload className="h-4 w-4 text-gray-400" />
            <h3 className="text-sm font-semibold">Import Proxies</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-surface-3 text-gray-400"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-4 space-y-3 overflow-y-auto">
          <div className="flex items-center gap-3 text-xs">
            <label className="text-gray-400">Format:</label>
            {(["auto", "colon", "csv"] as const).map((m) => (
              <label key={m} className="flex items-center gap-1 cursor-pointer">
                <input
                  type="radio"
                  checked={mode === m}
                  onChange={() => setMode(m)}
                />
                <span>
                  {m === "auto"
                    ? "Auto-detect"
                    : m === "colon"
                      ? "host:port:user:pass"
                      : "CSV with header"}
                </span>
              </label>
            ))}
          </div>

          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setSummary(null);
            }}
            placeholder={
              "1.2.3.4:8080:user:pass\n5.6.7.8:1080\n\n# or CSV:\nname,type,host,port,username,password,provider\nus-1,http,1.2.3.4,8080,u,p,manual"
            }
            className="input font-mono text-xs h-40 w-full"
          />

          <div className="text-xs text-gray-400">
            Detected mode: <span className="font-mono">{parsed.mode}</span> ·{" "}
            <span className="text-emerald-400">{validRows.length} valid</span>
            {" · "}
            <span className="text-red-400">
              {parsed.rows.length - validRows.length} invalid
            </span>
            {" · "}
            <span className="text-gray-400">{parsed.rows.length} total</span>
          </div>

          {parsed.rows.length > 0 && (
            <div className="border border-border rounded max-h-56 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="text-gray-500 sticky top-0 bg-surface-2">
                  <tr className="text-left">
                    <th className="px-2 py-1.5">Line</th>
                    <th className="px-2 py-1.5">Name</th>
                    <th className="px-2 py-1.5">Host:Port</th>
                    <th className="px-2 py-1.5">User</th>
                    <th className="px-2 py-1.5">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {parsed.rows.map((r, i) => {
                    // M13: highlight invalid rows in red and surface the
                    // raw line + specific reason inline so users can spot
                    // and fix issues without scrolling between input and
                    // table. For CSV mode line numbers offset by +1 to
                    // account for the header row.
                    const lineNo =
                      parsed.mode === "csv" ? i + 2 : i + 1;
                    return (
                      <tr
                        key={i}
                        className={`border-t border-border/50 ${
                          r.error ? "bg-red-600/10" : ""
                        }`}
                      >
                        <td className="px-2 py-1 text-gray-500">{lineNo}</td>
                        <td className="px-2 py-1">{r.row?.name ?? "-"}</td>
                        <td className="px-2 py-1 font-mono">
                          {r.row ? `${r.row.host}:${r.row.port}` : (
                            <span
                              className="text-gray-500 italic"
                              title={r.raw}
                            >
                              {r.raw.length > 30
                                ? r.raw.slice(0, 30) + "…"
                                : r.raw || "(empty)"}
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-1 text-gray-400">
                          {r.row?.username ?? "-"}
                        </td>
                        <td className="px-2 py-1">
                          {r.error ? (
                            <span className="text-red-400 text-[10px] flex items-center gap-1">
                              <span aria-hidden>✗</span>
                              <span title={r.error}>{r.error}</span>
                            </span>
                          ) : (
                            <span className="text-emerald-400 text-[10px] flex items-center gap-1">
                              <span aria-hidden>✓</span>
                              <span>valid</span>
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {summary && (
            <div className="px-3 py-2 bg-surface-2 border border-border rounded text-xs">
              Imported{" "}
              <span className="text-emerald-400 font-semibold">
                {summary.created}
              </span>
              , failed{" "}
              <span className="text-red-400 font-semibold">
                {summary.failed.length}
              </span>
              .
              {summary.failed.length > 0 && (
                <ul className="mt-1 text-red-400/80">
                  {summary.failed.slice(0, 5).map((f) => (
                    <li key={f.index}>
                      row {f.index + 1}: {f.error}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 p-3 border-t border-border">
          <button onClick={onClose} className="btn-secondary text-xs">
            {summary ? "Close" : "Cancel"}
          </button>
          <button
            onClick={handleImport}
            disabled={importing || validRows.length === 0 || !!summary}
            className="btn-primary text-xs flex items-center gap-1.5"
            title={
              invalidCount > 0
                ? `Skip ${invalidCount} invalid line${invalidCount === 1 ? "" : "s"} and import the rest`
                : undefined
            }
          >
            {importing && <Loader2 className="h-3 w-3 animate-spin" />}
            {invalidCount > 0 && validRows.length > 0
              ? `Skip invalid & import ${validRows.length}`
              : `Import ${validRows.length} ${validRows.length === 1 ? "proxy" : "proxies"}`}
          </button>
        </div>
      </div>
    </div>
  );
}
