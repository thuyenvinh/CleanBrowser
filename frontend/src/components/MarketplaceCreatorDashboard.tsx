import { useEffect, useMemo, useState } from "react";
import {
  Wallet,
  Download,
  Package,
  Loader2,
  X,
  ArrowUpRight,
  Clock,
  CheckCircle2,
  Send,
} from "lucide-react";
import {
  marketplaceCreator,
  type CreatorApp,
  type CreatorEarningsResponse,
  type MarketplaceEarning,
  type MarketplaceEarningStatus,
} from "../lib/marketplace";

interface MarketplaceCreatorDashboardProps {
  onClose: () => void;
}

/**
 * Creator portal — earnings ledger + summary cards, rendered as a modal
 * overlay so the marketplace page can stay focused on browse/install.
 *
 * Data layer in :mod:`backend.db_marketplace.creator_summary` /
 * ``list_earnings_for_creator``; HTTP routes
 * ``GET /api/marketplace/creator/earnings`` and ``/creator/apps``.
 *
 * Phase 6 phase 3 ships read-only — the "Request payout" button is a
 * disabled stub. The actual Stripe Connect payout flow lands in Phase 8
 * once the platform Stripe Connect account is provisioned.
 */
export function MarketplaceCreatorDashboard({
  onClose,
}: MarketplaceCreatorDashboardProps) {
  const [data, setData] = useState<CreatorEarningsResponse | null>(null);
  const [apps, setApps] = useState<CreatorApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [earnings, myApps] = await Promise.all([
          marketplaceCreator.earnings(),
          marketplaceCreator.apps().catch(() => [] as CreatorApp[]),
        ]);
        if (cancelled) return;
        setData(earnings);
        setApps(myApps);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load creator dashboard",
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const summary = data?.summary;
  const earnings = data?.earnings ?? [];

  // Available > 0 enables the payout button (still stubbed this phase).
  const canRequestPayout = (summary?.available_cents ?? 0) > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-surface-1 border border-border rounded-lg w-full max-w-5xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h2 className="text-lg font-medium text-gray-100 flex items-center gap-2">
              <Wallet className="h-5 w-5" />
              Creator Dashboard
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Revenue share earnings from your published apps.
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-200 p-1"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-sm text-gray-500 gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading...
            </div>
          ) : error ? (
            <div className="px-4 py-3 bg-red-600/15 border border-red-600/30 text-red-400 text-sm rounded">
              {error}
            </div>
          ) : (
            <>
              <SummaryCards summary={summary} />

              <div className="mt-6 flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-200">
                  Earnings ledger
                </h3>
                <button
                  disabled={!canRequestPayout}
                  title={
                    canRequestPayout
                      ? "Payout flow ships in Phase 8 (Stripe Connect)"
                      : "No available balance yet"
                  }
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-blue-600/30 text-blue-300 border border-blue-600/40 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Send className="h-3.5 w-3.5" />
                  Request payout
                </button>
              </div>

              <EarningsTable rows={earnings} />

              {apps.length > 0 && (
                <div className="mt-8">
                  <h3 className="text-sm font-medium text-gray-200 mb-2">
                    My submissions
                  </h3>
                  <MyAppsTable apps={apps} />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

interface SummaryCardsProps {
  summary: CreatorEarningsResponse["summary"] | undefined;
}

function SummaryCards({ summary }: SummaryCardsProps) {
  const cards = [
    {
      label: "Apps published",
      value: (summary?.total_apps ?? 0).toLocaleString(),
      icon: <Package className="h-4 w-4" />,
      sub: `${(summary?.total_installs ?? 0).toLocaleString()} total installs`,
    },
    {
      label: "Pending (escrow)",
      value: formatCents(summary?.pending_cents ?? 0),
      icon: <Clock className="h-4 w-4" />,
      sub: "Released after 14-day refund window",
    },
    {
      label: "Available",
      value: formatCents(summary?.available_cents ?? 0),
      icon: <Wallet className="h-4 w-4" />,
      sub: "Eligible for payout",
    },
    {
      label: "Paid out",
      value: formatCents(summary?.paid_out_cents ?? 0),
      icon: <CheckCircle2 className="h-4 w-4" />,
      sub: "Lifetime payouts",
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((c) => (
        <div
          key={c.label}
          className="bg-surface-2 border border-border rounded-md p-4"
        >
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>{c.label}</span>
            <span className="text-gray-600">{c.icon}</span>
          </div>
          <div className="mt-2 text-xl font-medium text-gray-100">{c.value}</div>
          <div className="mt-1 text-[11px] text-gray-500">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}

interface EarningsTableProps {
  rows: MarketplaceEarning[];
}

function EarningsTable({ rows }: EarningsTableProps) {
  if (rows.length === 0) {
    return (
      <div className="mt-3 text-center py-10 border border-dashed border-border rounded text-sm text-gray-500">
        <Download className="h-6 w-6 mx-auto mb-2 text-gray-600" />
        No earnings yet. Earnings appear here when a buyer installs one of
        your paid apps.
      </div>
    );
  }
  return (
    <div className="mt-3 overflow-x-auto border border-border rounded-md">
      <table className="w-full text-xs">
        <thead className="bg-surface-2 text-gray-400">
          <tr>
            <th className="text-left px-3 py-2 font-medium">Date</th>
            <th className="text-left px-3 py-2 font-medium">App</th>
            <th className="text-right px-3 py-2 font-medium">Gross</th>
            <th className="text-right px-3 py-2 font-medium">Your share</th>
            <th className="text-left px-3 py-2 font-medium">Status</th>
            <th className="text-left px-3 py-2 font-medium">Available on</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border">
              <td className="px-3 py-2 text-gray-400">
                {formatDate(r.created_at)}
              </td>
              <td className="px-3 py-2 text-gray-200">
                {r.app_name ?? r.app_slug ?? r.app_id.slice(0, 8)}
              </td>
              <td className="px-3 py-2 text-right text-gray-400">
                {formatCents(r.gross_cents, r.currency)}
              </td>
              <td className="px-3 py-2 text-right text-gray-100 font-medium">
                {formatCents(r.creator_cents, r.currency)}
              </td>
              <td className="px-3 py-2">
                <StatusBadge status={r.status} />
              </td>
              <td className="px-3 py-2 text-gray-500">
                {r.available_at ? formatDate(r.available_at) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusBadge({ status }: { status: MarketplaceEarningStatus }) {
  const config: Record<MarketplaceEarningStatus, { label: string; cls: string }> = {
    pending: {
      label: "Pending",
      cls: "bg-amber-600/15 text-amber-300 border-amber-600/30",
    },
    available: {
      label: "Available",
      cls: "bg-emerald-600/15 text-emerald-300 border-emerald-600/30",
    },
    paid_out: {
      label: "Paid out",
      cls: "bg-blue-600/15 text-blue-300 border-blue-600/30",
    },
    refunded: {
      label: "Refunded",
      cls: "bg-red-600/15 text-red-300 border-red-600/30",
    },
  };
  const c = config[status] ?? config.pending;
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full border text-[11px] ${c.cls}`}
    >
      {c.label}
    </span>
  );
}

interface MyAppsTableProps {
  apps: CreatorApp[];
}

function MyAppsTable({ apps }: MyAppsTableProps) {
  const sorted = useMemo(
    () => [...apps].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [apps],
  );
  return (
    <div className="overflow-x-auto border border-border rounded-md">
      <table className="w-full text-xs">
        <thead className="bg-surface-2 text-gray-400">
          <tr>
            <th className="text-left px-3 py-2 font-medium">App</th>
            <th className="text-left px-3 py-2 font-medium">Status</th>
            <th className="text-right px-3 py-2 font-medium">Price</th>
            <th className="text-right px-3 py-2 font-medium">Installs</th>
            <th className="text-right px-3 py-2 font-medium">Your %</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((a) => (
            <tr key={a.id} className="border-t border-border">
              <td className="px-3 py-2 text-gray-200">
                <div className="flex items-center gap-1">
                  {a.name}
                  {a.is_public && (
                    <ArrowUpRight className="h-3 w-3 text-gray-500" />
                  )}
                </div>
                <div className="text-[11px] text-gray-500">{a.slug}</div>
              </td>
              <td className="px-3 py-2">
                <ModerationBadge status={a.moderation_status} />
                {a.moderation_status === "rejected" && a.moderation_notes && (
                  <div className="text-[11px] text-red-300/80 mt-0.5">
                    {a.moderation_notes}
                  </div>
                )}
              </td>
              <td className="px-3 py-2 text-right text-gray-300">
                {a.price_cents > 0 ? formatCents(a.price_cents) : "Free"}
              </td>
              <td className="px-3 py-2 text-right text-gray-300">
                {a.install_count.toLocaleString()}
              </td>
              <td className="px-3 py-2 text-right text-gray-300">
                {a.revenue_share_pct}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModerationBadge({
  status,
}: {
  status: CreatorApp["moderation_status"];
}) {
  const config: Record<CreatorApp["moderation_status"], string> = {
    approved: "bg-emerald-600/15 text-emerald-300 border-emerald-600/30",
    pending: "bg-amber-600/15 text-amber-300 border-amber-600/30",
    rejected: "bg-red-600/15 text-red-300 border-red-600/30",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-full border text-[11px] ${config[status]}`}
    >
      {status}
    </span>
  );
}

function formatCents(cents: number, currency: string = "usd"): string {
  const value = (cents || 0) / 100;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: currency.toUpperCase(),
    }).format(value);
  } catch {
    // Some currency codes (or older browsers) trip Intl — fall back to a
    // basic formatter so the dashboard still renders.
    return `${value.toFixed(2)} ${currency.toUpperCase()}`;
  }
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
