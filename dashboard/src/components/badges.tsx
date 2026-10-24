"use client";

import { useT } from "@/lib/i18n";
import type { TaskState, Tier } from "@/lib/types";

/**
 * Every state gets a distinct label + color (never color alone --
 * architecture.md section 12 accessibility rule). auto_escalated and
 * human_handoff are visually louder (bold border + icon) than the
 * routine awaiting_approval/approved states, per the same section.
 */
const STATE_CSS: Record<string, string> = {
  working: "st-working",
  awaiting_approval: "st-awaiting_approval",
  human_handoff: "st-human_handoff badge-loud",
  approved: "st-approved",
  completed: "st-completed",
  rejected: "st-rejected",
  canceled: "st-canceled",
  failed: "st-failed",
  auto_escalated: "st-auto_escalated badge-loud",
  awaiting_hospital: "st-awaiting_hospital",
  ambulance_requested: "st-ambulance_requested",
  follow_up: "st-follow_up",
};

const STATE_ICON: Record<string, string> = {
  working: "⏳",
  awaiting_approval: "🕐",
  human_handoff: "🚨",
  approved: "✅",
  completed: "✅",
  rejected: "✕",
  canceled: "✕",
  failed: "✗",
  auto_escalated: "⚠",
  awaiting_hospital: "🏥",
  ambulance_requested: "🚑",
  follow_up: "📋",
};

export function StateBadge({ state }: { state: TaskState }) {
  const { t } = useT();
  const css = STATE_CSS[state] ?? "";
  const icon = STATE_ICON[state] ?? "●";
  return (
    <span className={`badge ${css}`}>
      <span className="glyph" aria-hidden="true">{icon}</span>
      <span>{t(`state.${state}`)}</span>
    </span>
  );
}

const TIER_CSS: Record<Tier, string> = {
  A: "tier-A",
  B: "tier-B",
  C1: "tier-C1",
  C2: "tier-C2",
};

const TIER_LABEL: Record<Tier, string> = {
  A: "Tier A — ASHA / PHC",
  B: "Tier B — CHC / Taluk",
  C1: "Tier C1 — District",
  C2: "Tier C2 — Tertiary",
};

export function TierBadge({ tier }: { tier: Tier | null }) {
  if (!tier) {
    return (
      <span className="badge tier-none">
        <span className="glyph" aria-hidden="true">○</span>
        No tier
      </span>
    );
  }
  return (
    <span className={`badge ${TIER_CSS[tier]}`} title={TIER_LABEL[tier]}>
      <span className="glyph" aria-hidden="true">◆</span>
      Tier {tier}
    </span>
  );
}

export function TimeCriticalBadge() {
  const { t } = useT();
  return (
    <span className="badge crit" aria-label="Time critical case">
      <span className="glyph" aria-hidden="true">🛑</span>
      {t("badge.timeCritical")}
    </span>
  );
}
