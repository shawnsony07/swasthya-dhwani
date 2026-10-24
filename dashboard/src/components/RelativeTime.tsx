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
 * with the absolute timestamp in a `title` tooltip for precision. */
export default function RelativeTime({ iso }: { iso: string }) {
  const [label, setLabel] = useState(() => formatRelative(iso));

  useEffect(() => {
    setLabel(formatRelative(iso));
    const id = setInterval(() => setLabel(formatRelative(iso)), 15_000);
    return () => clearInterval(id);
  }, [iso]);

  return (
    <time dateTime={iso} title={new Date(iso).toLocaleString()}>
      {label}
    </time>
  );
}
