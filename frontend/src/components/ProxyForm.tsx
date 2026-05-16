import { Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type {
  Proxy,
  ProxyCreateInput,
  ProxyUpdateInput,
} from "../lib/proxy";

interface ProxyFormProps {
  proxy: Proxy | null; // null = create mode
  onSave: (data: ProxyCreateInput | ProxyUpdateInput) => Promise<void>;
  onDelete?: () => Promise<void>;
  onCancel: () => void;
}

interface FormState {
  name: string;
  type: string;
  host: string;
  port: string; // string so the input can be empty mid-edit
  username: string;
  password: string;
  provider: string;
}

const EMPTY: FormState = {
  name: "",
  type: "http",
  host: "",
  port: "",
  username: "",
  password: "",
  provider: "",
};

const PROXY_TYPES = ["http", "https", "socks4", "socks5"] as const;
const PROVIDERS = ["", "brightdata", "smartproxy", "oxylabs", "iproyal", "other"];

export function ProxyForm({ proxy, onSave, onDelete, onCancel }: ProxyFormProps) {
  const isEdit = proxy !== null;
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>({});

  useEffect(() => {
    if (proxy) {
      setForm({
        name: proxy.name,
        type: proxy.type,
        host: proxy.host,
        port: String(proxy.port),
        username: proxy.username ?? "",
        password: "", // never echo back the secret
        provider: proxy.provider ?? "",
      });
    } else {
      setForm(EMPTY);
    }
    setErrors({});
  }, [proxy?.id]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const validate = (): boolean => {
    const errs: Partial<Record<keyof FormState, string>> = {};
    if (!form.name.trim()) errs.name = "Name is required";
    if (!form.host.trim()) errs.host = "Host is required";
    const portNum = Number(form.port);
    if (!form.port || !Number.isInteger(portNum) || portNum < 1 || portNum > 65535) {
      errs.port = "Port must be 1-65535";
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setSaving(true);
    try {
      const payload: ProxyCreateInput = {
        name: form.name.trim(),
        type: form.type,
        host: form.host.trim(),
        port: Number(form.port),
      };
      if (form.username.trim()) payload.username = form.username.trim();
      if (form.password) payload.password = form.password;
      if (form.provider) payload.provider = form.provider;
      // On edit, omit password if untouched so the backend keeps the old one.
      if (isEdit && !form.password) {
        const { password: _omit, ...rest } = payload as ProxyCreateInput & {
          password?: string;
        };
        void _omit;
        await onSave(rest as ProxyUpdateInput);
      } else {
        await onSave(payload);
      }
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm("Delete this proxy?")) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="p-6 max-w-xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edit Proxy" : "New Proxy"}
          </h2>
          {isEdit && onDelete && (
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleting}
              className="btn-danger flex items-center gap-1.5"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span>{deleting ? "Deleting..." : "Delete"}</span>
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={onCancel} className="btn-secondary">
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="btn-primary flex items-center gap-1.5"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "Saving..." : isEdit ? "Save" : "Create"}</span>
          </button>
        </div>
      </div>

      <div className="space-y-5">
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Basic
          </h3>
          <div className="space-y-3">
            <div>
              <label className="label">Name</label>
              <input
                className="input"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="e.g. US Residential #1"
              />
              {errors.name && (
                <p className="text-xs text-red-400 mt-1">{errors.name}</p>
              )}
            </div>
            <div>
              <label className="label">Provider</label>
              <select
                className="input"
                value={form.provider}
                onChange={(e) => set("provider", e.target.value)}
              >
                {PROVIDERS.map((p) => (
                  <option key={p} value={p}>
                    {p === "" ? "(none)" : p}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Connection
          </h3>
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="label">Type</label>
                <select
                  className="input"
                  value={form.type}
                  onChange={(e) => set("type", e.target.value)}
                >
                  {PROXY_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-span-2">
                <label className="label">Host</label>
                <input
                  className="input"
                  value={form.host}
                  onChange={(e) => set("host", e.target.value)}
                  placeholder="proxy.example.com"
                />
                {errors.host && (
                  <p className="text-xs text-red-400 mt-1">{errors.host}</p>
                )}
              </div>
            </div>
            <div>
              <label className="label">Port</label>
              <input
                className="input no-spin"
                type="number"
                value={form.port}
                onChange={(e) => set("port", e.target.value)}
                placeholder="8080"
                min={1}
                max={65535}
              />
              {errors.port && (
                <p className="text-xs text-red-400 mt-1">{errors.port}</p>
              )}
            </div>
          </div>
        </section>

        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
            Authentication
          </h3>
          <div className="space-y-3">
            <div>
              <label className="label">Username</label>
              <input
                className="input"
                value={form.username}
                onChange={(e) => set("username", e.target.value)}
                placeholder="(optional)"
                autoComplete="off"
              />
            </div>
            <div>
              <label className="label">Password</label>
              <input
                className="input"
                type="password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
                placeholder={isEdit ? "(unchanged)" : "(optional)"}
                autoComplete="new-password"
              />
              {isEdit && (
                <p className="text-xs text-gray-500 mt-1">
                  Leave blank to keep the existing password.
                </p>
              )}
            </div>
          </div>
        </section>
      </div>
    </form>
  );
}
