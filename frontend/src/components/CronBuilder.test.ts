import { describe, it, expect } from "vitest";
import { stateToCron, cronToState, type BuilderState } from "./CronBuilder";

const base: BuilderState = {
  frequency: "daily",
  everyMinutes: 15,
  minute: 0,
  hour: 9,
  weekdays: [1],
  dayOfMonth: 1,
};

describe("stateToCron", () => {
  it("every N minutes", () => {
    expect(stateToCron({ ...base, frequency: "minutes", everyMinutes: 5 })).toBe(
      "*/5 * * * *",
    );
  });
  it("hourly at minute", () => {
    expect(stateToCron({ ...base, frequency: "hourly", minute: 30 })).toBe(
      "30 * * * *",
    );
  });
  it("daily at HH:MM", () => {
    expect(stateToCron({ ...base, frequency: "daily", hour: 9, minute: 0 })).toBe(
      "0 9 * * *",
    );
  });
  it("weekly sorts + joins selected days", () => {
    expect(
      stateToCron({ ...base, frequency: "weekly", hour: 14, minute: 30, weekdays: [4, 1] }),
    ).toBe("30 14 * * 1,4");
  });
  it("monthly on day of month", () => {
    expect(
      stateToCron({ ...base, frequency: "monthly", hour: 8, minute: 0, dayOfMonth: 15 }),
    ).toBe("0 8 15 * *");
  });
});

describe("cronToState round-trip", () => {
  const cases = [
    "*/10 * * * *",
    "30 * * * *",
    "0 9 * * *",
    "30 14 * * 1,4",
    "0 8 15 * *",
  ];
  for (const cron of cases) {
    it(`re-emits ${cron}`, () => {
      const st = cronToState(cron);
      expect(st).not.toBeNull();
      expect(stateToCron(st!)).toBe(cron);
    });
  }

  it("returns null for patterns the simple builder can't represent", () => {
    // Range in hour field — beyond the builder's vocabulary.
    expect(cronToState("0 9-17 * * *")).toBeNull();
    // 6-field (with seconds) — builder only emits 5-field.
    expect(cronToState("0 0 9 * * *")).toBeNull();
  });
});
