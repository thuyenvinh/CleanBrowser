import { useEffect, useState, useCallback } from "react";
import {
  fetchPublicStatus,
  type PublicStatus,
  type ServiceStatus,
  type OverallStatus,
} from "../lib/status";

/**
 * Public status page rendered at ``/status``.
 *
 * Mounted from ``App.tsx`` *before* the auth check so unauthenticated
 * visitors can reach it. Refreshes on its own clock every
 * ``REFRESH_INTERVAL_MS`` because StatusPage is the kind of page users
 * leave open in a tab during an incident.
 */

const REFRESH_INTERVAL_MS = 60_000;

const SERVICE_LABELS: Record<string, string> = {
  api: "Core API",
  auth: "Authentication",
  browser_launch: "Browser Launch",
};

const OVERALL_COPY: Record<OverallStatus, { text: string; cls: string }> = {
  operational: {
    text: "All systems operational",
    cls: "bg-emerald-600/20 border-emerald-500/40 text-emerald-300",
  },
  degraded: {
    text: "Some systems are degraded",
    cls: "bg-amber-600/20 border-amber-500/40 text-amber-300",
  },
  major_outage: {
    text: "Major outage in progress",
    cls: "bg-red-600/20 border-red-500/40 text-red-300",
  },
};

const PILL_COPY: Record<ServiceStatus, { text: string; cls: string }> = {
  operational: {
    text: "Operational",
    cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  },
  degraded: {
    text: "Degraded",
    cls: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  },
  major_outage: {
    text: "Outage",
    cls: "bg-red-500/15 text-red-300 border-red-500/40",
  },
};

function formatUptime(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  // Two decimals for >= 99 %, one for everything else — gives an
  // SLA-style ``99.95 %`` for healthy services without the noise of
  // ``87.32 %`` when something is on fire.
  const digits = value >= 99 ? 2 : 1;
  return `${value.toFixed(digits)}%`;
}

function formatIncidentRange(startedAt: string, endedAt: string): string {
  try {
    const start = new Date(startedAt);
    const end = new Date(endedAt);
    const sameDay = start.toDateString() === end.toDateString();
    const dateFmt: Intl.DateTimeFormatOptions = {
      month: "short",
      day: "numeric",
    };
    const timeFmt: Intl.DateTimeFormatOptions = {
      hour: "2-digit",
      minute: "2-digit",
    };
    if (sameDay) {
      return `${start.toLocaleDateString(undefined, dateFmt)} · ${start.toLocaleTimeString(
        undefined,
        timeFmt,
      )} – ${end.toLocaleTimeString(undefined, timeFmt)}`;
    }
    return `${start.toLocaleDateString(undefined, dateFmt)} ${start.toLocaleTimeString(
      undefined,
      timeFmt,
    )} – ${end.toLocaleDateString(undefined, dateFmt)} ${end.toLocaleTimeString(
      undefined,
      timeFmt,
    )}`;
  } catch {
    return `${startedAt} – ${endedAt}`;
  }
}

export function StatusPage() {
  const [data, setData] = useState<PublicStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchPublicStatus();
      setData(next);
      setError(null);
      setLastRefreshedAt(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const handle = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(handle);
  }, [refresh]);

  if (loading && !data) {
    return (
      <div className="min-h-screen bg-surface-0 text-gray-200 flex items-center justify-center">
        <div className="text-sm text-gray-500">Loading status…</div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="min-h-screen bg-surface-0 text-gray-200 flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-red-400 mb-2">Unable to load status: {error}</p>
          <button
            type="button"
            onClick={() => {
              setLoading(true);
              refresh();
            }}
            className="text-xs text-gray-400 hover:text-gray-200 underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const status = data!;
  const overall = OVERALL_COPY[status.overall];
  const serviceNames = Object.keys(status.services);

  return (
    <div className="min-h-screen bg-surface-0 text-gray-200">
      <div className="max-w-3xl mx-auto px-6 py-10">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold mb-1">CloakBrowser Status</h1>
          <p className="text-xs text-gray-500">
            Live uptime feed · auto-refreshes every {REFRESH_INTERVAL_MS / 1000}s
            {lastRefreshedAt && (
              <>
                {" "}· last updated {lastRefreshedAt.toLocaleTimeString()}
              </>
            )}
          </p>
        </header>

        {/* Overall badge */}
        <div
          className={`rounded-md border px-5 py-4 mb-8 ${overall.cls}`}
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center gap-3">
            <span
              className={`inline-flex h-3 w-3 rounded-full ${
                status.overall === "operational"
                  ? "bg-emerald-400"
                  : status.overall === "degraded"
                    ? "bg-amber-400"
                    : "bg-red-400"
              }`}
            />
            <p className="text-base font-medium">{overall.text}</p>
          </div>
        </div>

        {/* Per-service rows */}
        <section className="mb-8">
          <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-3">
            Services
          </h2>
          <div className="border border-border rounded-md divide-y divide-border bg-surface-1">
            {serviceNames.length === 0 && (
              <div className="px-4 py-6 text-sm text-gray-500 text-center">
                No services reporting yet.
              </div>
            )}
            {serviceNames.map((svc) => {
              const svcStatus = status.services[svc] ?? "operational";
              const pill = PILL_COPY[svcStatus];
              return (
                <div
                  key={svc}
                  className="px-4 py-3 flex items-center justify-between gap-4"
                >
                  <div>
                    <p className="text-sm font-medium">
                      {SERVICE_LABELS[svc] ?? svc}
                    </p>
                    <p className="text-[11px] text-gray-500 font-mono">{svc}</p>
                  </div>
                  <div className="flex items-center gap-6 text-right">
                    <div className="hidden sm:block">
                      <p className="text-[10px] uppercase tracking-wider text-gray-500">
                        24h
                      </p>
                      <p className="text-xs font-mono">
                        {formatUptime(status.uptime_24h[svc])}
                      </p>
                    </div>
                    <div className="hidden sm:block">
                      <p className="text-[10px] uppercase tracking-wider text-gray-500">
                        7d
                      </p>
                      <p className="text-xs font-mono">
                        {formatUptime(status.uptime_7d[svc])}
                      </p>
                    </div>
                    <div className="hidden sm:block">
                      <p className="text-[10px] uppercase tracking-wider text-gray-500">
                        30d
                      </p>
                      <p className="text-xs font-mono">
                        {formatUptime(status.uptime_30d[svc])}
                      </p>
                    </div>
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] border ${pill.cls}`}
                    >
                      {pill.text}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Recent incidents */}
        <section>
          <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-3">
            Incidents — last 7 days
          </h2>
          {status.recent_incidents.length === 0 ? (
            <div className="border border-border rounded-md bg-surface-1 px-4 py-6 text-sm text-gray-500 text-center">
              No incidents reported.
            </div>
          ) : (
            <ul className="space-y-2">
              {status.recent_incidents.map((inc, idx) => {
                const pill = PILL_COPY[inc.status as ServiceStatus] ?? PILL_COPY.degraded;
                return (
                  <li
                    key={`${inc.service_name}-${inc.started_at}-${idx}`}
                    className="border border-border rounded-md bg-surface-1 px-4 py-3"
                  >
                    <div className="flex items-center justify-between gap-3 mb-1">
                      <p className="text-sm font-medium">
                        {SERVICE_LABELS[inc.service_name] ?? inc.service_name}
                      </p>
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] border ${pill.cls}`}
                      >
                        {pill.text}
                      </span>
                    </div>
                    <p className="text-[11px] text-gray-500 mb-1">
                      {formatIncidentRange(inc.started_at, inc.ended_at)} · {inc.count}{" "}
                      failed check{inc.count === 1 ? "" : "s"}
                    </p>
                    {inc.error_message && (
                      <p className="text-[11px] font-mono text-gray-400 truncate">
                        {inc.error_message}
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <footer className="mt-10 text-center text-[11px] text-gray-600">
          Self-hosted uptime tracker · no external monitoring required.
        </footer>
      </div>
    </div>
  );
}

export default StatusPage;
