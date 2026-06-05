import { CreditCard, ExternalLink, Check } from "lucide-react";
import { useBilling } from "../hooks/useBilling";
import { InvoiceList } from "./InvoiceList";

function formatPrice(cents: number, interval: string): string {
  if (cents === 0) return "Free";
  return `$${(cents / 100).toFixed(0)}/${interval.replace("month","mo").replace("year","yr")}`;
}

function UsageBar({ label, used, max }: { label: string; used: number; max: number | null }) {
  const pct = max == null ? 0 : Math.min(100, (used / max) * 100);
  const overLimit = max != null && used >= max;
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-400">{label}</span>
        <span className={overLimit ? "text-red-400" : "text-gray-300"}>
          {used}{max == null ? " / ∞" : ` / ${max}`}
        </span>
      </div>
      <div
        className="h-1.5 bg-surface-2 rounded overflow-hidden"
        role="progressbar"
        aria-label={`${label} usage`}
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={max ?? undefined}
      >
        {max != null && (
          <div className={`h-full ${overLimit ? "bg-red-500" : pct > 80 ? "bg-yellow-500" : "bg-emerald-500"}`}
               style={{ width: `${pct}%` }} />
        )}
      </div>
    </div>
  );
}

export function BillingPage() {
  const { status, plans, invoices, loading, error, upgrade, managePortal, refresh, payVnpay } = useBilling();

  if (loading) {
    return <div className="p-8 text-center text-gray-500 text-sm">Loading billing...</div>;
  }
  if (error) {
    return <div className="p-8">
      <div className="bg-red-600/15 border border-red-600/30 text-red-400 px-4 py-3 rounded text-sm">{error}</div>
      <button onClick={refresh} className="mt-3 text-xs text-gray-400 hover:text-gray-200 underline">Retry</button>
    </div>;
  }
  if (!status) return null;

  const { subscription, plan, usage } = status;
  const isStripe = subscription?.payment_provider === "stripe";

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Current plan */}
      <section className="border border-border rounded-lg p-5 bg-surface-1">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <CreditCard className="h-5 w-5 text-gray-400" /> Current plan
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              {plan.name} · {formatPrice(plan.price_cents, plan.interval)}
              {subscription?.status && ` · ${subscription.status}`}
            </p>
          </div>
          {isStripe && (
            <button onClick={managePortal} className="flex items-center gap-1 px-3 py-1.5 bg-surface-2 hover:bg-surface-3 rounded text-xs">
              Manage <ExternalLink className="h-3 w-3" />
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 gap-x-8 gap-y-3">
          <UsageBar label="Profiles" used={usage.profile_count} max={plan.max_profiles} />
          <UsageBar label="Concurrent runs (peak)" used={usage.concurrent_runs_peak} max={plan.max_concurrent_runs} />
          <UsageBar label="Workspace members" used={usage.workspace_members_count} max={plan.max_workspace_members} />
          <UsageBar label="Automation minutes" used={usage.automation_minutes_used} max={plan.max_automation_minutes} />
          <UsageBar label="Storage (GB)" used={Math.round(usage.storage_gb_used)} max={plan.max_storage_gb} />
        </div>
      </section>

      {/* Plans grid */}
      <section>
        <h3 className="text-sm font-semibold mb-3">Plans</h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          {plans.map(p => {
            const current = p.id === plan.id;
            return (
              <div key={p.id} className={`border rounded-lg p-4 ${current ? "border-emerald-500/50 bg-emerald-500/5" : "border-border bg-surface-1"}`}>
                <div className="text-sm font-semibold">{p.name}</div>
                <div className="text-2xl font-bold mt-1">{formatPrice(p.price_cents, p.interval)}</div>
                <p className="text-xs text-gray-500 mt-1 mb-3">{p.description}</p>
                <ul className="text-xs space-y-1 text-gray-400 mb-3">
                  <li><Check className="h-3 w-3 inline text-emerald-500 mr-1" />{p.max_profiles ?? "∞"} profiles</li>
                  <li><Check className="h-3 w-3 inline text-emerald-500 mr-1" />{p.max_concurrent_runs ?? "∞"} concurrent runs</li>
                  <li><Check className="h-3 w-3 inline text-emerald-500 mr-1" />{p.max_workspace_members ?? "∞"} members</li>
                  <li><Check className="h-3 w-3 inline text-emerald-500 mr-1" />{p.max_automation_minutes ?? "∞"} automation min/mo</li>
                  <li><Check className="h-3 w-3 inline text-emerald-500 mr-1" />Regions: {p.allow_regions.join(", ")}</li>
                </ul>
                {current ? (
                  <div className="text-xs text-emerald-400 text-center py-1.5">Current plan</div>
                ) : p.price_cents === 0 ? (
                  <button onClick={() => upgrade(p.id)} className="w-full px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs">
                    Switch
                  </button>
                ) : (
                  <div className="flex gap-1.5">
                    <button onClick={() => upgrade(p.id)} className="flex-1 px-2 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs">
                      Stripe
                    </button>
                    <button onClick={() => payVnpay(p.id)} className="flex-1 px-2 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs">
                      VNPay
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Invoices */}
      <section>
        <h3 className="text-sm font-semibold mb-3">Invoices</h3>
        <InvoiceList invoices={invoices} />
      </section>
    </div>
  );
}
