import { useCallback, useEffect, useState } from "react";
import { billing, type Invoice, type Plan, type SubscriptionStatus } from "../lib/billing";

export function useBilling() {
  const [status, setStatus] = useState<SubscriptionStatus | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [s, p, i] = await Promise.all([
        billing.getSubscription(),
        billing.listPlans(),
        // Invoices may 404 on older servers — swallow rather than fail the whole page.
        billing.listInvoices().catch(() => [] as Invoice[]),
      ]);
      setStatus(s); setPlans(p); setInvoices(i);
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

  const payVnpay = useCallback(async (planId: string) => {
    try {
      const {url} = await billing.startVnpayCheckout(planId);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "VNPay failed");
    }
  }, []);

  return { status, plans, invoices, loading, error, refresh, upgrade, managePortal, payVnpay };
}
