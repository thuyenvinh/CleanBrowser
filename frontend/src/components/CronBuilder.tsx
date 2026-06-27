import { useEffect, useMemo, useState } from "react";

/**
 * Visual cron-expression builder.
 *
 * Most users scheduling an automation don't think in cron syntax — they
 * think "every day at 9am" or "every Monday and Thursday at 14:30". This
 * component lets them express that intent with dropdowns and generates the
 * 5-field cron string the backend expects. A raw-text "Advanced" escape
 * hatch stays available for power users who already know cron.
 *
 * Output is ALWAYS a 5-field cron (min hour dom mon dow). The component is
 * controlled: it accepts the current cron string and emits a new one via
 * ``onChange`` whenever the user edits any control.
 */

export type CronFrequency =
  | "minutes"
  | "hourly"
  | "daily"
  | "weekly"
  | "monthly";

interface CronBuilderProps {
  value: string;
  onChange: (cron: string) => void;
}

const WEEKDAYS: { value: number; label: string }[] = [
  { value: 1, label: "Mon" },
  { value: 2, label: "Tue" },
  { value: 3, label: "Wed" },
  { value: 4, label: "Thu" },
  { value: 5, label: "Fri" },
  { value: 6, label: "Sat" },
  { value: 0, label: "Sun" },
];

const MINUTE_INTERVALS = [1, 2, 5, 10, 15, 20, 30];

export interface BuilderState {
  frequency: CronFrequency;
  everyMinutes: number; // for "minutes"
  minute: number; // 0-59, for hourly/daily/weekly/monthly
  hour: number; // 0-23, for daily/weekly/monthly
  weekdays: number[]; // for weekly (0-6, 0=Sun)
  dayOfMonth: number; // 1-31, for monthly
}

const DEFAULT_STATE: BuilderState = {
  frequency: "daily",
  everyMinutes: 15,
  minute: 0,
  hour: 9,
  weekdays: [1],
  dayOfMonth: 1,
};

/** Build a 5-field cron string from the builder state. */
export function stateToCron(s: BuilderState): string {
  switch (s.frequency) {
    case "minutes":
      return `*/${s.everyMinutes} * * * *`;
    case "hourly":
      return `${s.minute} * * * *`;
    case "daily":
      return `${s.minute} ${s.hour} * * *`;
    case "weekly": {
      const days = s.weekdays.length ? [...s.weekdays].sort((a, b) => a - b).join(",") : "*";
      return `${s.minute} ${s.hour} * * ${days}`;
    }
    case "monthly":
      return `${s.minute} ${s.hour} ${s.dayOfMonth} * *`;
    default:
      return "0 9 * * *";
  }
}

/**
 * Best-effort parse of a cron string back into builder state so editing an
 * existing schedule pre-fills the controls. Falls back to ``null`` for any
 * pattern the simple builder can't represent (the caller then shows the
 * advanced raw editor instead).
 */
export function cronToState(cron: string): BuilderState | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const min = parts[0] ?? "";
  const hr = parts[1] ?? "";
  const dom = parts[2] ?? "";
  const mon = parts[3] ?? "";
  const dow = parts[4] ?? "";

  // every N minutes: "*/N * * * *"
  const everyMin = min.match(/^\*\/(\d+)$/);
  if (everyMin && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    return { ...DEFAULT_STATE, frequency: "minutes", everyMinutes: Number(everyMin[1]) };
  }

  // Only support plain integer fields beyond this point.
  const isInt = (v: string) => /^\d+$/.test(v);

  // hourly: "M * * * *"
  if (isInt(min) && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    return { ...DEFAULT_STATE, frequency: "hourly", minute: Number(min) };
  }
  // daily: "M H * * *"
  if (isInt(min) && isInt(hr) && dom === "*" && mon === "*" && dow === "*") {
    return { ...DEFAULT_STATE, frequency: "daily", minute: Number(min), hour: Number(hr) };
  }
  // weekly: "M H * * D[,D...]"
  if (isInt(min) && isInt(hr) && dom === "*" && mon === "*" && dow !== "*") {
    const days = dow.split(",").map(Number).filter((n) => n >= 0 && n <= 6);
    if (days.length && days.every((n) => Number.isInteger(n))) {
      return {
        ...DEFAULT_STATE,
        frequency: "weekly",
        minute: Number(min),
        hour: Number(hr),
        weekdays: days,
      };
    }
  }
  // monthly: "M H DOM * *"
  if (isInt(min) && isInt(hr) && isInt(dom) && mon === "*" && dow === "*") {
    return {
      ...DEFAULT_STATE,
      frequency: "monthly",
      minute: Number(min),
      hour: Number(hr),
      dayOfMonth: Number(dom),
    };
  }
  return null;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** Human-readable summary of the generated cron. */
function describe(s: BuilderState): string {
  const at = `${pad2(s.hour)}:${pad2(s.minute)}`;
  switch (s.frequency) {
    case "minutes":
      return `Every ${s.everyMinutes} minute${s.everyMinutes === 1 ? "" : "s"}`;
    case "hourly":
      return `Every hour at minute ${s.minute}`;
    case "daily":
      return `Every day at ${at}`;
    case "weekly": {
      const names = WEEKDAYS.filter((d) => s.weekdays.includes(d.value)).map((d) => d.label);
      return `Every ${names.join(", ") || "(no day)"} at ${at}`;
    }
    case "monthly":
      return `On day ${s.dayOfMonth} of every month at ${at}`;
    default:
      return "";
  }
}

export function CronBuilder({ value, onChange }: CronBuilderProps) {
  // Detect whether the incoming cron is representable by the simple
  // builder. If not (advanced ranges, lists in hour, etc.) we start in
  // advanced mode so we never silently rewrite the user's expression.
  const parsed = useMemo(() => cronToState(value), [value]);
  const [advanced, setAdvanced] = useState(value !== "" && parsed === null);
  const [state, setState] = useState<BuilderState>(parsed ?? DEFAULT_STATE);

  // When we have a state and we're in builder mode, push the generated cron
  // upward. Guard against echoing back an identical value.
  useEffect(() => {
    if (advanced) return;
    const next = stateToCron(state);
    if (next !== value) onChange(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, advanced]);

  // Seed a sensible default when the parent starts empty.
  useEffect(() => {
    if (value === "" && !advanced) {
      onChange(stateToCron(DEFAULT_STATE));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = (p: Partial<BuilderState>) => setState((s) => ({ ...s, ...p }));

  const toggleWeekday = (d: number) =>
    setState((s) => ({
      ...s,
      weekdays: s.weekdays.includes(d)
        ? s.weekdays.filter((x) => x !== d)
        : [...s.weekdays, d],
    }));

  if (advanced) {
    return (
      <div className="space-y-2">
        <input
          className="input font-mono"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="0 9 * * *"
          autoComplete="off"
          aria-label="Cron expression"
        />
        <button
          type="button"
          onClick={() => {
            const reparsed = cronToState(value);
            if (reparsed) setState(reparsed);
            setAdvanced(false);
          }}
          className="text-xs text-accent hover:underline"
        >
          ← Back to visual builder
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Frequency picker */}
      <div className="flex flex-wrap gap-1">
        {(
          [
            ["minutes", "Every N min"],
            ["hourly", "Hourly"],
            ["daily", "Daily"],
            ["weekly", "Weekly"],
            ["monthly", "Monthly"],
          ] as [CronFrequency, string][]
        ).map(([f, label]) => (
          <button
            key={f}
            type="button"
            onClick={() => patch({ frequency: f })}
            className={`px-2.5 py-1 text-xs rounded border transition-colors ${
              state.frequency === f
                ? "bg-accent/15 text-accent border-accent/40"
                : "bg-surface-2 text-gray-400 border-border hover:border-border-hover"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Frequency-specific controls */}
      {state.frequency === "minutes" && (
        <label className="flex items-center gap-2 text-xs text-gray-400">
          Run every
          <select
            className="input w-auto py-1"
            value={state.everyMinutes}
            onChange={(e) => patch({ everyMinutes: Number(e.target.value) })}
          >
            {MINUTE_INTERVALS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          minutes
        </label>
      )}

      {state.frequency === "hourly" && (
        <label className="flex items-center gap-2 text-xs text-gray-400">
          At minute
          <input
            type="number"
            min={0}
            max={59}
            className="input w-20 py-1"
            value={state.minute}
            onChange={(e) =>
              patch({ minute: Math.min(59, Math.max(0, Number(e.target.value) || 0)) })
            }
          />
          of every hour
        </label>
      )}

      {(state.frequency === "daily" ||
        state.frequency === "weekly" ||
        state.frequency === "monthly") && (
        <div className="flex items-center gap-2 text-xs text-gray-400">
          At
          <input
            type="time"
            className="input w-auto py-1"
            value={`${pad2(state.hour)}:${pad2(state.minute)}`}
            onChange={(e) => {
              const segs = e.target.value.split(":").map(Number);
              patch({ hour: segs[0] || 0, minute: segs[1] || 0 });
            }}
          />
        </div>
      )}

      {state.frequency === "weekly" && (
        <div className="flex flex-wrap gap-1">
          {WEEKDAYS.map((d) => (
            <button
              key={d.value}
              type="button"
              onClick={() => toggleWeekday(d.value)}
              className={`w-10 py-1 text-xs rounded border transition-colors ${
                state.weekdays.includes(d.value)
                  ? "bg-accent/15 text-accent border-accent/40"
                  : "bg-surface-2 text-gray-400 border-border hover:border-border-hover"
              }`}
            >
              {d.label}
            </button>
          ))}
        </div>
      )}

      {state.frequency === "monthly" && (
        <label className="flex items-center gap-2 text-xs text-gray-400">
          On day
          <input
            type="number"
            min={1}
            max={31}
            className="input w-20 py-1"
            value={state.dayOfMonth}
            onChange={(e) =>
              patch({ dayOfMonth: Math.min(31, Math.max(1, Number(e.target.value) || 1)) })
            }
          />
          of the month
        </label>
      )}

      {/* Preview + advanced toggle */}
      <div className="flex items-center justify-between pt-1 border-t border-border">
        <div className="text-xs">
          <span className="text-gray-500">{describe(state)}</span>
          <span className="font-mono text-gray-400 ml-2">({stateToCron(state)})</span>
        </div>
        <button
          type="button"
          onClick={() => setAdvanced(true)}
          className="text-xs text-gray-500 hover:text-gray-300"
        >
          Advanced
        </button>
      </div>
    </div>
  );
}

export default CronBuilder;
