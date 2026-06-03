import { useEffect, useState } from "react";
import { Check, Sparkles } from "lucide-react";
import { billing, type Plan } from "../lib/billing";

interface PricingPageProps {
  /** Called when the user clicks "Start trial" on a paid plan. Forwards
      the chosen plan id so the signup screen can show the trial banner. */
  onStartTrial: (planId: string) => void;
  /** Called when the user clicks the footer "Log in" link. */
  onLogin: () => void;
}

function formatPrice(cents: number, interval: string): string {
  if (cents === 0) return "Free";
  return `$${(cents / 100).toFixed(0)}/${interval.replace("month", "mo").replace("year", "yr")}`;
}

export function PricingPage({ onStartTrial, onLogin }: PricingPageProps) {
  const [plans, setPlans] = useState<Plan[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    billing
      .listPublicPlans()
      .then((p) => setPlans(p))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load plans"));
  }, []);

  return (
    <div className="min-h-screen bg-surface-0 py-12 px-4 overflow-y-auto">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-10">
          <div className="inline-flex items-center gap-1.5 text-xs uppercase tracking-wide text-accent mb-2">
            <Sparkles className="h-3.5 w-3.5" />
            Pricing
          </div>
          <h1 className="text-3xl font-bold text-gray-100 mb-2">
            Pick a plan, start free for 14 days
          </h1>
          <p className="text-sm text-gray-500 max-w-xl mx-auto">
            Every new account gets a 14-day Pro trial. No credit card required.
            You can downgrade or cancel any time from the Billing tab.
          </p>
        </div>

        {error && (
          <div className="max-w-md mx-auto bg-red-600/15 border border-red-600/30 text-red-400 px-4 py-3 rounded text-sm mb-6">
            {error}
          </div>
        )}

        {!plans && !error && (
          <div className="text-center text-gray-500 text-sm">Loading plans...</div>
        )}

        {plans && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {plans.map((p) => {
              const isFree = p.price_cents === 0;
              const isPro = p.id === "pro";
              return (
                <div
                  key={p.id}
                  data-plan={p.id}
                  className={`border rounded-lg p-5 flex flex-col ${
                    isPro
                      ? "border-accent/60 bg-accent/5"
                      : "border-border bg-surface-1"
                  }`}
                >
                  {isPro && (
                    <div className="text-[10px] uppercase tracking-wide text-accent mb-1">
                      Recommended
                    </div>
                  )}
                  <div className="text-base font-semibold">{p.name}</div>
                  <div className="text-3xl font-bold mt-1">
                    {formatPrice(p.price_cents, p.interval)}
                  </div>
                  <p className="text-xs text-gray-500 mt-1 mb-4 min-h-[2.5em]">
                    {p.description}
                  </p>
                  <ul className="text-xs space-y-1.5 text-gray-400 mb-5 flex-1">
                    <li>
                      <Check className="h-3 w-3 inline text-emerald-500 mr-1.5" />
                      {p.max_profiles ?? "Unlimited"} profiles
                    </li>
                    <li>
                      <Check className="h-3 w-3 inline text-emerald-500 mr-1.5" />
                      {p.max_concurrent_runs ?? "Unlimited"} concurrent runs
                    </li>
                    <li>
                      <Check className="h-3 w-3 inline text-emerald-500 mr-1.5" />
                      {p.max_workspace_members ?? "Unlimited"} workspace members
                    </li>
                    <li>
                      <Check className="h-3 w-3 inline text-emerald-500 mr-1.5" />
                      {p.max_automation_minutes ?? "Unlimited"} automation min/mo
                    </li>
                    <li>
                      <Check className="h-3 w-3 inline text-emerald-500 mr-1.5" />
                      Regions: {p.allow_regions.join(", ")}
                    </li>
                  </ul>
                  {isFree ? (
                    <button
                      type="button"
                      onClick={() => onStartTrial(p.id)}
                      className="w-full px-3 py-2 bg-surface-2 hover:bg-surface-3 text-gray-200 rounded text-xs"
                    >
                      Sign up free
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onStartTrial(p.id)}
                      className={`w-full px-3 py-2 rounded text-xs ${
                        isPro
                          ? "bg-accent hover:bg-accent/90 text-white"
                          : "bg-emerald-600 hover:bg-emerald-500 text-white"
                      }`}
                    >
                      Start 14-day free trial
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <p className="text-xs text-gray-500 mt-8 text-center">
          Already have an account?{" "}
          <button
            type="button"
            onClick={onLogin}
            className="text-accent hover:underline"
          >
            Log in
          </button>
        </p>
      </div>
    </div>
  );
}
