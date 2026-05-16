import { useCallback, useEffect, useState } from "react";
import { billing, type Plan, type SubscriptionStatus } from "../lib/billing";

export function useBilling() {
  const [status, setStatus] = useState<SubscriptionStatus | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [s, p] = await Promise.all([billing.getSubscription(), billing.listPlans()]);
      setStatus(s); setPlans(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load billing");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const upgrade = useCallback(async (planId: string) => {
    try {
      const { url } = await billing.startCheckout(planId);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Checkout failed");
    }
  }, []);

  const managePortal = useCallback(async () => {
    try {
      const { url } = await billing.openPortal();
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Portal failed");
    }
  }, []);

  return { status, plans, loading, error, refresh, upgrade, managePortal };
}
