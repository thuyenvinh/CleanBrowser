import { ExternalLink, FileText } from "lucide-react";
import type { Invoice } from "../lib/billing";

interface Props { invoices: Invoice[]; }

const STATUS_CLASS: Record<string, string> = {
  paid: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  open: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  failed: "bg-red-500/15 text-red-400 border-red-500/30",
  void: "bg-gray-500/15 text-gray-400 border-gray-500/30",
  uncollectible: "bg-red-500/15 text-red-400 border-red-500/30",
  draft: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

function formatAmount(cents: number, currency: string): string {
  const major = cents / 100;
  const upper = currency.toUpperCase();
  if (upper === "VND") return `${cents.toLocaleString("vi-VN")} ₫`;
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: upper }).format(major);
  } catch {
    return `${major.toFixed(2)} ${upper}`;
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
}

export function InvoiceList({ invoices }: Props) {
  if (invoices.length === 0) {
    return (
      <div className="text-xs text-gray-500 py-3 border border-dashed border-border rounded text-center">
        No invoices yet. They will appear here once your provider sends webhook events.
      </div>
    );
  }
  return (
    <div className="border border-border rounded overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-surface-2 text-gray-400 uppercase tracking-wider">
          <tr>
            <th className="text-left px-3 py-2">Date</th>
            <th className="text-left px-3 py-2">Number</th>
            <th className="text-right px-3 py-2">Amount</th>
            <th className="text-center px-3 py-2">Status</th>
            <th className="text-right px-3 py-2">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {invoices.map((inv) => {
            const statusClass = STATUS_CLASS[inv.status] ?? STATUS_CLASS.draft;
            return (
              <tr key={inv.id} className="hover:bg-surface-2/40">
                <td className="px-3 py-2 text-gray-300">{formatDate(inv.paid_at ?? inv.created_at)}</td>
                <td className="px-3 py-2 font-mono text-gray-400">{inv.number ?? inv.provider_invoice_id.slice(0, 14)}</td>
                <td className="px-3 py-2 text-right text-gray-300">{formatAmount(inv.amount_cents, inv.currency)}</td>
                <td className="px-3 py-2 text-center">
                  <span className={`inline-block text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded border ${statusClass}`}>
                    {inv.status}
                  </span>
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="flex justify-end gap-2">
                    {inv.invoice_pdf_url && (
                      <a href={inv.invoice_pdf_url} target="_blank" rel="noreferrer"
                         className="inline-flex items-center gap-1 text-gray-400 hover:text-gray-200"
                         title="Download PDF">
                        <FileText className="h-3 w-3" /> PDF
                      </a>
                    )}
                    {inv.hosted_invoice_url && (
                      <a href={inv.hosted_invoice_url} target="_blank" rel="noreferrer"
                         className="inline-flex items-center gap-1 text-gray-400 hover:text-gray-200"
                         title="View hosted invoice">
                        View <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
