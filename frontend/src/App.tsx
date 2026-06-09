import { useState, useCallback, useEffect } from "react";
import { Lock, PanelLeftClose, PanelLeft, Server, Globe, Workflow, CreditCard, Package, Shield } from "lucide-react";
import { useProfiles } from "./hooks/useProfiles";
import { useAuth } from "./hooks/useAuth";
import { api, setOnUnauthorized, type BulkProfileResult, type ProfileCreateData } from "./lib/api";
import { automation as automationApi, type Automation } from "./lib/automation";
import { ProfileList } from "./components/ProfileList";
import {
  BulkResizeModal,
  BulkRunAutomationModal,
  BulkResultBanner,
} from "./components/BulkOpsModals";
import { ProfileForm } from "./components/ProfileForm";
import { ProfileViewer } from "./components/ProfileViewer";
import { LaunchButton } from "./components/LaunchButton";
import { StatusIndicator } from "./components/StatusIndicator";
import { LoginPage } from "./components/LoginPage";
import { SignupPage } from "./components/SignupPage";
import { ForgotPasswordPage } from "./components/ForgotPasswordPage";
import { ResetPasswordPage } from "./components/ResetPasswordPage";
import { PricingPage } from "./components/PricingPage";
import { WorkspaceSelector } from "./components/WorkspaceSelector";
import { ProxyPage } from "./components/ProxyPage";
import { AutomationPage } from "./components/AutomationPage";
import { BillingPage } from "./components/BillingPage";
import { MarketplacePage } from "./components/MarketplacePage";
import { EmailVerificationBanner } from "./components/EmailVerificationBanner";
import { TrialCountdownBanner } from "./components/TrialCountdownBanner";
import { StatusPage } from "./components/StatusPage";
import { ApiKeysPage } from "./components/ApiKeysPage";

type AuthState = "checking" | "required" | "ok" | "error";
type View = "empty" | "create" | "edit" | "view";
type AuthView = "login" | "signup" | "pricing" | "forgot";
type Tab = "profiles" | "proxies" | "automations" | "marketplace" | "billing" | "apikeys";

// Public ``/status`` route is evaluated once at module-load before any
// hooks run — keeps unauthenticated visitors out of the auth state
// machine entirely and complies with the rules-of-hooks (we cannot
// early-return from ``App`` after the first ``useState`` call).
const IS_PUBLIC_STATUS_ROUTE =
  typeof window !== "undefined" && window.location.pathname === "/status";

// Same trick for the reset-password landing page: the email link points at
// ``/reset-password?token=…`` and must render BEFORE any auth state machine
// runs — otherwise an unauthenticated user clicking the link gets bounced
// to /login instead of the reset form. We accept either the path
// ``/reset-password`` OR the query flag ``?reset=1`` so static hosts that
// can't add an SPA fallback route still work.
const RESET_PASSWORD_TOKEN: string | null = (() => {
  if (typeof window === "undefined") return null;
  try {
    const onPath = window.location.pathname === "/reset-password";
    const params = new URLSearchParams(window.location.search);
    const flag = params.get("reset") === "1";
    if (!onPath && !flag) return null;
    return params.get("token") ?? "";
  } catch {
    return null;
  }
})();

export default function App() {
  if (IS_PUBLIC_STATUS_ROUTE) {
    return <StatusPage />;
  }

  if (RESET_PASSWORD_TOKEN !== null) {
    const leaveResetFlow = () => {
      try {
        window.history.replaceState({}, "", "/");
      } catch {
        /* no-op in non-browser test envs */
      }
      // Hard navigation so the App component re-evaluates the module-level
      // ``RESET_PASSWORD_TOKEN`` snapshot against the cleaned URL.
      window.location.assign("/");
    };
    return (
      <ResetPasswordPage
        token={RESET_PASSWORD_TOKEN}
        onSuccess={leaveResetFlow}
        onCancel={leaveResetFlow}
      />
    );
  }

  const [authState, setAuthState] = useState<AuthState>("checking");
  const [authRequired, setAuthRequired] = useState(false);
  // Initial auth view: if the URL carries ``?pricing=1`` show the marketing
  // pricing page first; otherwise default to the login form.
  const [authView, setAuthView] = useState<AuthView>(() => {
    try {
      return new URLSearchParams(window.location.search).get("pricing")
        ? "pricing"
        : "login";
    } catch {
      return "login";
    }
  });
  const authCtx = useAuth();

  useEffect(() => {
    setOnUnauthorized(() => setAuthState("required"));

    api.authStatus()
      .then(({ auth_required, authenticated }) => {
        setAuthRequired(auth_required);
        if (!auth_required || authenticated) {
          setAuthState("ok");
        } else {
          setAuthState("required");
        }
      })
      .catch((err) => {
        console.warn("[auth] status check failed:", err);
        setAuthState("error");
      });

    return () => setOnUnauthorized(null);
  }, []);

  // When useAuth confirms a multi-tenant session, mark auth ok.
  useEffect(() => {
    if (authCtx.user) setAuthState("ok");
  }, [authCtx.user]);

  if (authState === "checking") {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading...</div>
      </div>
    );
  }

  if (authState === "error") {
    return (
      <div className="h-screen flex items-center justify-center bg-surface-0">
        <div className="text-center">
          <p className="text-red-400 text-sm mb-2">Unable to reach the server</p>
          <button
            onClick={() => {
              setAuthState("checking");
              api.authStatus()
                .then(({ auth_required, authenticated }) => {
                  setAuthRequired(auth_required);
                  setAuthState(!auth_required || authenticated ? "ok" : "required");
                })
                .catch(() => setAuthState("error"));
            }}
            className="text-xs text-gray-400 hover:text-gray-200 underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (authState === "required") {
    if (authView === "pricing") {
      return (
        <PricingPage
          onStartTrial={(planId) => {
            // Update URL so SignupPage can read ``?plan=`` for the banner.
            try {
              const url = new URL(window.location.href);
              url.searchParams.set("plan", planId);
              url.searchParams.delete("pricing");
              window.history.replaceState({}, "", url.toString());
            } catch {
              /* no-op in non-browser test envs */
            }
            setAuthView("signup");
          }}
          onLogin={() => setAuthView("login")}
        />
      );
    }
    if (authView === "signup") {
      return (
        <SignupPage
          onSuccess={() => {
            // SignupPage calls /api/auth/signup directly. Pull the freshly
            // issued session into useAuth so workspaces + the API client
            // header are populated before we render AppContent.
            authCtx.refresh();
            setAuthState("ok");
          }}
          onSwitchToLogin={() => setAuthView("login")}
        />
      );
    }
    if (authView === "forgot") {
      return (
        <ForgotPasswordPage onSwitchToLogin={() => setAuthView("login")} />
      );
    }
    return (
      <LoginPage
        onSuccess={() => {
          authCtx.refresh();
          setAuthState("ok");
        }}
        onLegacySuccess={() => setAuthState("ok")}
        onSwitchToSignup={() => setAuthView("signup")}
        onSwitchToForgot={() => setAuthView("forgot")}
      />
    );
  }

  return (
    <AppContent
      authRequired={authRequired}
      workspaces={authCtx.workspaces}
      currentWorkspaceId={authCtx.currentWorkspaceId}
      onSwitchWorkspace={authCtx.switchWorkspace}
      userEmail={authCtx.user?.email ?? null}
      userEmailVerified={authCtx.user?.email_verified_at ?? null}
      onLogout={async () => {
        await authCtx.logout();
        try { await api.logout(); } catch { /* legacy endpoint may not exist */ }
        setAuthView("login");
        setAuthState("required");
      }}
    />
  );
}

interface AppContentProps {
  authRequired: boolean;
  workspaces: { id: string; name: string }[];
  currentWorkspaceId: string | null;
  onSwitchWorkspace: (id: string) => void;
  userEmail: string | null;
  userEmailVerified: string | null;
  onLogout: () => void;
}

function AppContent({ authRequired, workspaces, currentWorkspaceId, onSwitchWorkspace, userEmail, userEmailVerified, onLogout }: AppContentProps) {
  // Pass ``currentWorkspaceId`` so useProfiles refetches whenever the user
  // switches workspace (the header injection happens in lib/api).
  const { profiles, loading, error, create, update, remove, launch, stop, refresh: refreshProfiles } =
    useProfiles(currentWorkspaceId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("empty");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [tab, setTab] = useState<Tab>("profiles");

  // ── Bulk operations state ───────────────────────────────────────────────
  // Lifted here (above ProfileList) so the resize / run-automation modals
  // can stay rendered when the sidebar is hidden. The pending ids are
  // captured at click time so a status refresh between click and
  // confirm doesn't change what we operate on.
  const [bulkResizeIds, setBulkResizeIds] = useState<string[] | null>(null);
  const [bulkRunIds, setBulkRunIds] = useState<string[] | null>(null);
  const [bulkAutomations, setBulkAutomations] = useState<Automation[]>([]);
  const [bulkResult, setBulkResult] = useState<
    { title: string; result: BulkProfileResult } | null
  >(null);

  const handleBulkLaunch = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return;
    try {
      const res = await api.bulkLaunch(ids);
      setBulkResult({ title: `Launch ${ids.length} profile${ids.length === 1 ? "" : "s"}`, result: res });
      refreshProfiles();
    } catch (err) {
      setBulkResult({
        title: "Launch failed",
        result: {
          succeeded: 0,
          failed: ids.length,
          results: ids.map((id) => ({ profile_id: id, ok: false, error: String(err) })),
        },
      });
    }
  }, [refreshProfiles]);

  const handleBulkStop = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return;
    try {
      const res = await api.bulkStop(ids);
      setBulkResult({ title: `Stop ${ids.length} profile${ids.length === 1 ? "" : "s"}`, result: res });
      refreshProfiles();
    } catch (err) {
      setBulkResult({
        title: "Stop failed",
        result: {
          succeeded: 0,
          failed: ids.length,
          results: ids.map((id) => ({ profile_id: id, ok: false, error: String(err) })),
        },
      });
    }
  }, [refreshProfiles]);

  const handleBulkResizeApply = useCallback(
    async (ids: string[], width: number, height: number) => {
      try {
        const res = await api.bulkResize(ids, width, height);
        setBulkResult({
          title: `Resize ${ids.length} → ${width}×${height}`,
          result: res,
        });
        refreshProfiles();
      } catch (err) {
        setBulkResult({
          title: "Resize failed",
          result: {
            succeeded: 0,
            failed: ids.length,
            results: ids.map((id) => ({ profile_id: id, ok: false, error: String(err) })),
          },
        });
      }
    },
    [refreshProfiles],
  );

  const openBulkRunModal = useCallback(async (ids: string[]) => {
    setBulkRunIds(ids);
    try {
      const list = await automationApi.list();
      setBulkAutomations(list);
    } catch {
      setBulkAutomations([]);
    }
  }, []);

  const handleBulkRunConfirm = useCallback(
    async (ids: string[], automationId: string) => {
      try {
        const res = await api.bulkRunAutomation(automationId, ids);
        setBulkResult({
          title: `Run automation on ${ids.length} profile${ids.length === 1 ? "" : "s"}`,
          result: res,
        });
      } catch (err) {
        setBulkResult({
          title: "Bulk run failed",
          result: {
            succeeded: 0,
            failed: ids.length,
            results: ids.map((id) => ({ profile_id: id, ok: false, error: String(err) })),
          },
        });
      }
    },
    [],
  );

  const selected = profiles.find((p) => p.id === selectedId) ?? null;

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
    const profile = profiles.find((p) => p.id === id);
    setView(profile?.status === "running" ? "view" : "edit");
  }, [profiles]);

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setView("create");
  }, []);

  const handleCreate = useCallback(async (data: ProfileCreateData) => {
    const profile = await create(data);
    if (profile) {
      setSelectedId(profile.id);
      setView("edit");
    }
  }, [create]);

  const handleUpdate = useCallback(async (data: ProfileCreateData) => {
    if (!selectedId) return;
    await update(selectedId, data);
  }, [selectedId, update]);

  const handleDelete = useCallback(async () => {
    if (!selectedId) return;
    await remove(selectedId);
    setSelectedId(null);
    setView("empty");
  }, [selectedId, remove]);

  const handleLaunch = useCallback(async () => {
    if (!selectedId) return;
    const result = await launch(selectedId);
    if (result) setView("view");
  }, [selectedId, launch]);

  const handleStop = useCallback(async () => {
    if (!selectedId) return;
    await stop(selectedId);
    setView("edit");
  }, [selectedId, stop]);

  const handleVncDisconnect = useCallback(() => {
    setView("edit");
  }, []);

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="text-gray-500 text-sm">Loading...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      {/* Profile sidebar (only on profiles tab) */}
      {tab === "profiles" && sidebarOpen && (
        <div className="w-64 border-r border-border bg-surface-1 flex-shrink-0">
          <ProfileList
            profiles={profiles}
            selectedId={selectedId}
            onSelect={handleSelect}
            onNew={handleNew}
            onBulkLaunch={handleBulkLaunch}
            onBulkStop={handleBulkStop}
            onBulkResize={(ids) => setBulkResizeIds(ids)}
            onBulkRunAutomation={openBulkRunModal}
          />
        </div>
      )}

      {/* Main panel */}
      <div className="flex-1 flex flex-col min-w-0">
        <TrialCountdownBanner />
        {/* Email verification nag — only when the multi-tenant session is
            present AND the user hasn't verified yet. */}
        {userEmail && !userEmailVerified && (
          <EmailVerificationBanner email={userEmail} />
        )}
        {/* Top bar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface-1">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-gray-500 hover:text-gray-300 p-1"
              title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
            >
              {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeft className="h-4 w-4" />}
            </button>
            {selected && (
              <div className="flex items-center gap-2">
                <StatusIndicator status={selected.status} size="md" />
                <span className="text-sm font-medium">{selected.name}</span>
                <span className="text-xs text-gray-500 capitalize">{selected.platform}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 mr-2">
              <button
                onClick={() => setTab("profiles")}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${tab === "profiles" ? "bg-surface-2 text-gray-200" : "text-gray-500 hover:text-gray-300"}`}
                title="Profiles"
              >
                <Server className="h-3.5 w-3.5" />
                Profiles
              </button>
              <button
                onClick={() => setTab("proxies")}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${tab === "proxies" ? "bg-surface-2 text-gray-200" : "text-gray-500 hover:text-gray-300"}`}
                title="Proxies"
              >
                <Globe className="h-3.5 w-3.5" />
                Proxies
              </button>
              <button
                onClick={() => setTab("automations")}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${tab === "automations" ? "bg-surface-2 text-gray-200" : "text-gray-500 hover:text-gray-300"}`}
                title="Automations"
              >
                <Workflow className="h-3.5 w-3.5" />
                Automations
              </button>
              <button
                onClick={() => setTab("marketplace")}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${tab === "marketplace" ? "bg-surface-2 text-gray-200" : "text-gray-500 hover:text-gray-300"}`}
                title="Marketplace"
              >
                <Package className="h-3.5 w-3.5" />
                Marketplace
              </button>
              <button
                onClick={() => setTab("billing")}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${tab === "billing" ? "bg-surface-2 text-gray-200" : "text-gray-500 hover:text-gray-300"}`}
                title="Billing"
              >
                <CreditCard className="h-3.5 w-3.5" />
                Billing
              </button>
              <button
                onClick={() => setTab("apikeys")}
                className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${tab === "apikeys" ? "bg-surface-2 text-gray-200" : "text-gray-500 hover:text-gray-300"}`}
                title="Security (MFA + API keys)"
              >
                <Shield className="h-3.5 w-3.5" />
                Security
              </button>
            </div>
            {tab === "profiles" && selected && (
              <LaunchButton
                status={selected.status}
                onLaunch={handleLaunch}
                onStop={handleStop}
              />
            )}
            <WorkspaceSelector
              workspaces={workspaces}
              currentWorkspaceId={currentWorkspaceId}
              onSwitch={onSwitchWorkspace}
            />
            {authRequired && (
              <button
                onClick={onLogout}
                className="text-gray-500 hover:text-gray-300 p-1"
                title="Log out"
              >
                <Lock className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-600/15 border-b border-red-600/30 text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* Content */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {tab === "proxies" && (
            <ProxyPage currentWorkspaceId={currentWorkspaceId} />
          )}
          {tab === "automations" && (
            <AutomationPage currentWorkspaceId={currentWorkspaceId} />
          )}
          {tab === "marketplace" && (
            <MarketplacePage currentWorkspaceId={currentWorkspaceId} />
          )}
          {tab === "billing" && <BillingPage />}
          {tab === "apikeys" && <ApiKeysPage />}
          {tab === "profiles" && view === "empty" && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <p className="text-gray-500 text-sm">Select a profile or create a new one</p>
              </div>
            </div>
          )}

          {tab === "profiles" && view === "create" && (
            <ProfileForm
              profile={null}
              onSave={handleCreate}
              onCancel={() => setView("empty")}
            />
          )}

          {tab === "profiles" && view === "edit" && selected && (
            <ProfileForm
              profile={selected}
              onSave={handleUpdate}
              onDelete={handleDelete}
              onCancel={() => {
                setSelectedId(null);
                setView("empty");
              }}
            />
          )}

          {tab === "profiles" && view === "view" && selected && selected.status === "running" && (
            <ProfileViewer
              key={selected.id}
              profileId={selected.id}
              cdpUrl={selected.cdp_url}
              clipboardSync={selected.clipboard_sync}
              onDisconnect={handleVncDisconnect}
            />
          )}
        </div>
      </div>

      {/* ── Bulk operations modals + result toast ──────────────────────── */}
      {bulkResizeIds && (
        <BulkResizeModal
          count={bulkResizeIds.length}
          onClose={() => setBulkResizeIds(null)}
          onConfirm={(w, h) => {
            const ids = bulkResizeIds;
            setBulkResizeIds(null);
            handleBulkResizeApply(ids, w, h);
          }}
        />
      )}
      {bulkRunIds && (
        <BulkRunAutomationModal
          count={bulkRunIds.length}
          automations={bulkAutomations}
          onClose={() => setBulkRunIds(null)}
          onConfirm={(autoId) => {
            const ids = bulkRunIds;
            setBulkRunIds(null);
            handleBulkRunConfirm(ids, autoId);
          }}
        />
      )}
      {bulkResult && (
        <BulkResultBanner
          title={bulkResult.title}
          result={bulkResult.result}
          onDismiss={() => setBulkResult(null)}
        />
      )}
    </div>
  );
}
