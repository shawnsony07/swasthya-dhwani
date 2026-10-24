"use client";

import { useEffect, useState } from "react";

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const now = Date.now();
  const diffSeconds = Math.round((now - then) / 1000);

  const divisions: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.345, "week"],
    [12, "month"],
    [Infinity, "year"],
  ];

  let duration = diffSeconds;
  let unit: Intl.RelativeTimeFormatUnit = "second";
  for (const [amount, u] of divisions) {
    if (Math.abs(duration) < amount) {
      unit = u;
      break;
    }
    duration = Math.round(duration / amount);
    unit = u;
  }

  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  return rtf.format(-duration, unit);
}

/** Renders a relative time ("3 minutes ago") that ticks on an interval,
 * with the absolute timestamp in a `title` tooltip for precision.
 *
 * `label` is derived fresh on every render from `iso` (a pure, cheap
 * computation) rather than synchronized into state from an effect --
 * `tick` exists only to force a re-render every 15s, and is updated from
 * the timer callback itself, not synchronously in the effect body. */
export default function RelativeTime({ iso }: { iso: string }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 15_000);
    return () => clearInterval(id);
  }, []);

  return (
    <time dateTime={iso} title={new Date(iso).toLocaleString()}>
      {formatRelative(iso)}
    </time>
  );
}
