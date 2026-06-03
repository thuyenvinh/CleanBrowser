import { useMemo, useState } from "react";
import {
  Package,
  Download,
  Check,
  Loader2,
  Star,
  ExternalLink,
  Plus,
  Wallet,
  ShieldCheck,
} from "lucide-react";
import { useMarketplace } from "../hooks/useMarketplace";
import type { MarketplaceApp } from "../lib/marketplace";
import { MarketplaceSubmitDialog } from "./MarketplaceSubmitDialog";
import { MarketplaceCreatorDashboard } from "./MarketplaceCreatorDashboard";
import { AdminModerationPage } from "./AdminModerationPage";

interface MarketplacePageProps {
  currentWorkspaceId: string | null;
}

export function MarketplacePage({ currentWorkspaceId }: MarketplacePageProps) {
  const {
    apps,
    installs,
    category,
    setCategory,
    loading,
    error,
    install,
    uninstall,
    submit,
  } = useMarketplace(currentWorkspaceId);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [dashboardOpen, setDashboardOpen] = useState(false);
  // Moderation queue is shown unconditionally — the backend gates the route
  // on bare auth in Phase 6 (no platform-admin role yet). Multi-tenant SaaS
  // deploys should hide this button + add a super-admin gate before
  // exposing the queue to non-operators.
  const [moderationOpen, setModerationOpen] = useState(false);

  // Derive category chips from whatever the backend returned. Backend agent
  // PPP owns the canonical list; we only surface what actually exists so the
  // UI doesn't show empty filter chips.
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const a of apps) {
      if (a.category) set.add(a.category);
    }
    return Array.from(set).sort();
  }, [apps]);

  const installByAppId = useMemo(() => {
    const m = new Map<string, string>();
    for (const i of installs) m.set(i.app_id, i.id);
    return m;
  }, [installs]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-gray-500 text-sm flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading marketplace...
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {error && (
        <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
          {error}
        </div>
      )}

      <div className="px-6 py-4 border-b border-border bg-surface-1">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-lg font-medium text-gray-100 flex items-center gap-2">
              <Package className="h-5 w-5" />
              Marketplace
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Browse and install community flows and scripts.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setModerationOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-border text-gray-200 hover:bg-surface-2"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Moderation Queue
            </button>
            <button
              onClick={() => setDashboardOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-border text-gray-200 hover:bg-surface-2"
            >
              <Wallet className="h-3.5 w-3.5" />
              Creator Dashboard
            </button>
            <button
              onClick={() => setSubmitOpen(true)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-500"
            >
              <Plus className="h-3.5 w-3.5" />
              Submit your app
            </button>
          </div>
        </div>

        {/* Category filter chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setCategory(null)}
            className={`px-2.5 py-1 text-xs rounded-full border ${
              category === null
                ? "bg-surface-2 text-gray-100 border-border"
                : "text-gray-400 border-transparent hover:text-gray-200"
            }`}
          >
            All
          </button>
          {categories.map((c) => (
            <button
              key={c}
              onClick={() => setCategory(c)}
              className={`px-2.5 py-1 text-xs rounded-full border ${
                category === c
                  ? "bg-surface-2 text-gray-100 border-border"
                  : "text-gray-400 border-transparent hover:text-gray-200"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {apps.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Package className="h-12 w-12 text-gray-600 mb-3" />
            <p className="text-gray-400 text-sm mb-1">No apps available yet</p>
            <p className="text-gray-600 text-xs">
              Check back soon for community flows and scripts.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {apps.map((app) => (
              <AppCard
                key={app.id}
                app={app}
                installId={installByAppId.get(app.id) ?? null}
                onInstall={() => install(app.id)}
                onUninstall={(installId) => uninstall(installId)}
              />
            ))}
          </div>
        )}
      </div>

      {submitOpen && (
        <MarketplaceSubmitDialog
          onClose={() => setSubmitOpen(false)}
          onSubmit={submit}
        />
      )}

      {dashboardOpen && (
        <MarketplaceCreatorDashboard
          onClose={() => setDashboardOpen(false)}
        />
      )}

      {moderationOpen && (
        <AdminModerationPage onClose={() => setModerationOpen(false)} />
      )}
    </div>
  );
}

interface AppCardProps {
  app: MarketplaceApp;
  installId: string | null;
  onInstall: () => void;
  onUninstall: (installId: string) => void;
}

function AppCard({ app, installId, onInstall, onUninstall }: AppCardProps) {
  const installed = installId !== null;

  return (
    <div className="bg-surface-1 border border-border rounded-lg p-4 flex flex-col">
      <div className="flex items-start gap-3 mb-3">
        {app.icon_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={app.icon_url}
            alt=""
            className="h-10 w-10 rounded-md object-cover bg-surface-2"
          />
        ) : (
          <div className="h-10 w-10 rounded-md bg-surface-2 flex items-center justify-center text-gray-500">
            <Package className="h-5 w-5" />
          </div>
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <h3 className="text-sm font-medium text-gray-100 truncate">
              {app.name}
            </h3>
            {app.is_official && (
              <Star
                className="h-3.5 w-3.5 text-amber-400 flex-shrink-0"
                aria-label="Official"
              />
            )}
          </div>
          <p className="text-xs text-gray-500 truncate">
            {app.creator_name ?? "Unknown creator"} · v{app.version}
          </p>
        </div>
      </div>

      <p className="text-xs text-gray-400 mb-3 line-clamp-3 min-h-[3rem]">
        {app.description ?? "No description provided."}
      </p>

      <div className="flex items-center justify-between text-xs text-gray-500 mb-3">
        <span className="flex items-center gap-1">
          <Download className="h-3 w-3" />
          {app.install_count.toLocaleString()}
        </span>
        <span className="uppercase tracking-wide">{app.kind}</span>
      </div>

      <div className="mt-auto flex items-center gap-2">
        {installed ? (
          <button
            onClick={() => installId && onUninstall(installId)}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs rounded border border-border bg-surface-2 text-gray-200 hover:bg-surface-1"
          >
            <Check className="h-3.5 w-3.5" />
            Installed
          </button>
        ) : (
          <button
            onClick={onInstall}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-500"
          >
            <Download className="h-3.5 w-3.5" />
            Install
          </button>
        )}
        {app.creator_url && (
          <a
            href={app.creator_url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 text-gray-500 hover:text-gray-300"
            title="Visit creator"
          >
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </div>
    </div>
  );
}
