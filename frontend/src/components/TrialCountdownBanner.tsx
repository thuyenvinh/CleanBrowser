import { useEffect, useState } from "react";
import { Clock, X } from "lucide-react";
import { billing } from "../lib/billing";

export function TrialCountdownBanner() {
  const [daysLeft, setDaysLeft] = useState<number | null>(null);
  const [dismissed, setDismissed] = useState<boolean>(
    () => localStorage.getItem("trial_banner_dismissed_at") === new Date().toISOString().slice(0,10)
  );

  useEffect(() => {
    billing.getSubscription()
      .then(({subscription}) => {
        if (subscription?.status === 'trialing' && subscription.trial_end) {
          const end = new Date(subscription.trial_end).getTime();
          const now = Date.now();
          const days = Math.ceil((end - now) / (1000 * 60 * 60 * 24));
          setDaysLeft(days > 0 ? days : 0);
        }
      })
      .catch(() => {});
  }, []);

  if (dismissed || daysLeft === null) return null;
  if (daysLeft > 3) return null;  // chỉ show 3 ngày cuối

  return (
    <div className="bg-orange-500/10 border-b border-orange-500/30 px-4 py-2 text-orange-300 text-sm flex items-center justify-between">
      <span className="flex items-center gap-2">
        <Clock className="h-4 w-4" />
        {daysLeft === 0 ? "Your free trial ends today!" : `Your free trial ends in ${daysLeft} day${daysLeft === 1 ? '' : 's'}.`}
        {' '}<a href="/?billing=upgrade" className="underline ml-1">Upgrade now</a> to keep your data.
      </span>
      <button onClick={() => {
        setDismissed(true);
        localStorage.setItem("trial_banner_dismissed_at", new Date().toISOString().slice(0,10));
      }} className="text-orange-200 hover:text-orange-100">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
