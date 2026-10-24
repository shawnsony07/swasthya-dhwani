"use client";

import { useT } from "@/lib/i18n";
import type { TaskState, Tier } from "@/lib/types";

/**
 * Every state gets a distinct label + color (never color alone --
 * architecture.md section 12 accessibility rule). auto_escalated and
 * human_handoff are visually louder (bold border + icon) than the
 * routine awaiting_approval/approved states, per the same section.
 */
const STATE_STYLES: Record<
  TaskState,
  { icon: string; className: string; loud?: boolean }
> = {
  working: { icon: "⏳", className: "bg-slate-100 text-slate-700 border-slate-300" },
  awaiting_approval: {
    icon: "\u{1F550}",
    className: "bg-amber-100 text-amber-800 border-amber-300",
  },
  human_handoff: {
    icon: "\u{1F6A8}",
    className: "bg-red-100 text-red-800 border-red-400 font-bold ring-2 ring-red-300",
    loud: true,
  },
  approved: {
    icon: "✅",
    className: "bg-green-100 text-green-800 border-green-300",
  },
  rejected: { icon: "❌", className: "bg-gray-100 text-gray-700 border-gray-300" },
  auto_escalated: {
    icon: "⚠️",
    className: "bg-orange-100 text-orange-900 border-orange-400 font-bold ring-2 ring-orange-300",
    loud: true,
  },
};

export function StateBadge({ state }: { state: TaskState }) {
  const { t } = useT();
  const style = STATE_STYLES[state];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-sm ${style.className}`}
    >
      <span aria-hidden="true">{style.icon}</span>
      <span>{t(`state.${state}`)}</span>
    </span>
  );
}

const TIER_STYLES: Record<Tier, string> = {
  A: "bg-sky-100 text-sky-800 border-sky-300",
  B: "bg-indigo-100 text-indigo-800 border-indigo-300",
  C1: "bg-rose-100 text-rose-800 border-rose-300",
  C2: "bg-purple-100 text-purple-800 border-purple-300",
};

export function TierBadge({ tier }: { tier: Tier | null }) {
  const { t } = useT();
  if (!tier) {
    return (
      <span className="inline-flex items-center rounded-full border border-gray-300 bg-gray-100 px-2.5 py-1 text-sm text-gray-600">
        No tier
      </span>
    );
  }
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-sm font-medium ${TIER_STYLES[tier]}`}
    >
      {t(`tier.${tier}`)}
    </span>
  );
}

export function TimeCriticalBadge() {
  const { t } = useT();
  return (
    <span className="inline-flex items-center gap-1 rounded-full border-2 border-red-500 bg-red-50 px-2.5 py-1 text-sm font-bold text-red-700 ring-2 ring-red-200">
      <span aria-hidden="true">{"\u{1F6D1}"}</span>
      <span>{t("badge.timeCritical")}</span>
    </span>
  );
}
