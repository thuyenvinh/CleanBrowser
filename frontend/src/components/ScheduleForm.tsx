/**
 * Inline form to create or edit an automation schedule (cron + timezone).
 *
 * TEMP LOCAL TYPES: ``Schedule``, ``ScheduleCreateInput`` and
 * ``ScheduleUpdateInput`` are duplicated here because Agent JJ has not yet
 * landed ``lib/automation.ts``. Once that module exists, replace the local
 * declarations with:
 *
 *     import type {
 *       Schedule,
 *       ScheduleCreateInput,
 *       ScheduleUpdateInput,
 *     } from "../lib/automation";
 *
 * and delete the local versions.
 */
import { Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

// --- TEMP LOCAL TYPES (replace with import from "../lib/automation") --------
export interface Schedule {
  id: string;
  automation_id: string;
  profile_id?: string | null;
  cron: string;
  timezone: string;
  enabled: boolean;
  next_fire_at?: string | null;
  last_fire_at?: string | null;
  created_at: string;
}

export interface ScheduleCreateInput {
  cron: string;
  profile_id?: string | null;
  timezone?: string;
  enabled?: boolean;
}

export type ScheduleUpdateInput = Partial<ScheduleCreateInput>;
// ---------------------------------------------------------------------------

interface ScheduleFormProps {
  automationId: string;
  schedule: Schedule | null; // null = create
  profiles: { id: string; name: string }[];
  onSave: (input: ScheduleCreateInput | ScheduleUpdateInput) => Promise<void>;
  onDelete?: () => Promise<void>;
  onCancel: () => void;
}

// Curated list of ~30 common IANA timezones. UTC is first so it's the default.
const TIMEZONES = [
  "UTC",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Africa/Lagos",
  "America/Anchorage",
  "America/Argentina/Buenos_Aires",
  "America/Chicago",
  "America/Denver",
  "America/Halifax",
  "America/Los_Angeles",
  "America/Mexico_City",
  "America/New_York",
  "America/Phoenix",
  "America/Sao_Paulo",
  "America/Toronto",
  "Asia/Bangkok",
  "Asia/Dubai",
  "Asia/Hong_Kong",
  "Asia/Jakarta",
  "Asia/Kolkata",
  "Asia/Seoul",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Melbourne",
  "Australia/Sydney",
  "Europe/Amsterdam",
  "Europe/Berlin",
  "Europe/London",
  "Europe/Madrid",
  "Europe/Moscow",
  "Europe/Paris",
  "Pacific/Auckland",
];

interface FormState {
  cron: string;
  timezone: string;
  profile_id: string; // "" = none
  enabled: boolean;
}

const EMPTY: FormState = {
  cron: "",
  timezone: "UTC",
  profile_id: "",
  enabled: true,
};

/**
 * Very loose client-side cron validation. We accept 5- or 6-field cron
 * expressions (5 classic, 6 = leading seconds). Each field is a non-empty
 * token. The backend does the authoritative parsing.
 */
function validateCron(expr: string): string | null {
  const trimmed = expr.trim();
  if (!trimmed) return "Cron expression is required";
  const parts = trimmed.split(/\s+/);
  if (parts.length !== 5 && parts.length !== 6) {
    return "Cron must have 5 or 6 space-separated fields";
  }
  if (parts.some((p) => p.length === 0)) {
    return "Cron fields must not be empty";
  }
  return null;
}

export function ScheduleForm({
  schedule,
  profiles,
  onSave,
  onDelete,
  onCancel,
}: ScheduleFormProps) {
  const isEdit = schedule !== null;
  const [form, setForm] = useState<FormState>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [errors, setErrors] = useState<Partial<Record<keyof FormState, string>>>(
    {},
  );

  useEffect(() => {
    if (schedule) {
      setForm({
        cron: schedule.cron,
        timezone: schedule.timezone || "UTC",
        profile_id: schedule.profile_id ?? "",
        enabled: schedule.enabled,
      });
    } else {
      setForm(EMPTY);
    }
    setErrors({});
  }, [schedule?.id]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const validate = (): boolean => {
    const errs: Partial<Record<keyof FormState, string>> = {};
    const cronErr = validateCron(form.cron);
    if (cronErr) errs.cron = cronErr;
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;
    setSaving(true);
    try {
      const payload: ScheduleCreateInput = {
        cron: form.cron.trim(),
        timezone: form.timezone,
        enabled: form.enabled,
      };
      if (form.profile_id) {
        payload.profile_id = form.profile_id;
      } else {
        // Explicit null clears any existing profile on update.
        payload.profile_id = null;
      }
      await onSave(payload);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!onDelete) return;
    if (!confirm("Delete this schedule?")) return;
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-surface-0 border border-border rounded p-4"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold">
          {isEdit ? "Edit Schedule" : "New Schedule"}
        </h3>
        <div className="flex items-center gap-2">
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

      <div className="space-y-3">
        <div>
          <label className="label">Cron expression</label>
          <input
            className="input font-mono"
            value={form.cron}
            onChange={(e) => set("cron", e.target.value)}
            placeholder="0 9 * * *"
            autoComplete="off"
          />
          {errors.cron ? (
            <p className="text-xs text-red-400 mt-1">{errors.cron}</p>
          ) : (
            <p className="text-xs text-gray-500 mt-1">
              5 fields (min hour dom mon dow) or 6 fields (with seconds).
            </p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label">Timezone</label>
            <select
              className="input"
              value={form.timezone}
              onChange={(e) => set("timezone", e.target.value)}
            >
              {TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Profile</label>
            <select
              className="input"
              value={form.profile_id}
              onChange={(e) => set("profile_id", e.target.value)}
            >
              <option value="">(any / unassigned)</option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="inline-flex items-center gap-2 text-sm cursor-pointer select-none">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
            />
            <span>Enabled</span>
          </label>
        </div>
      </div>
    </form>
  );
}
