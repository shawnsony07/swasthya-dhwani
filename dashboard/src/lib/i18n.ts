"use client";

import { createContext, useContext } from "react";

/**
 * Minimal Malayalam/English i18n (task scope item 6: "minimal next-intl or
 * a small custom setup on the highest-visibility labels"). A small custom
 * context + dictionary was chosen over next-intl to avoid pulling in
 * App-Router routing middleware/config surface (locale sub-paths, a second
 * middleware alongside the auth one) for a pass that only needs label
 * swapping, not full route localization.
 *
 * Coverage: nav, task states, tiers, approve/reject actions, the
 * synthetic-data footer, and the time-critical badge. NOT translated:
 * triage snapshot field labels (raw transcript, confidence, impairment
 * signals, etc.), error messages, and form validation text -- noted as
 * left untranslated in the delivery report.
 */

export type Locale = "en" | "ml";

type Dict = Record<string, { en: string; ml: string }>;

export const dictionary: Dict = {
  "nav.title": { en: "Swasthya-Dhwani Dashboard", ml: "സ്വാസ്ഥ്യ-ധ്വനി ഡാഷ്ബോർഡ്" },
  "nav.dashboard": { en: "Dashboard", ml: "ഡാഷ്ബോർഡ്" },
  "nav.signOut": { en: "Sign out", ml: "സൈൻ ഔട്ട്" },
  "nav.signedInAs": { en: "Signed in as", ml: "സൈൻ ഇൻ ചെയ്തത്" },

  "queue.title": { en: "Emergency Triage Queue", ml: "അടിയന്തര ട്രിയേജ് ക്യൂ" },
  "filter.needsApproval": { en: "Needs approval", ml: "അംഗീകാരം വേണ്ടത്" },
  "filter.all": { en: "All", ml: "എല്ലാം" },

  "state.working": { en: "Working", ml: "പ്രവർത്തനത്തിൽ" },
  "state.awaiting_approval": { en: "Awaiting approval", ml: "അംഗീകാരത്തിനായി കാത്തിരിക്കുന്നു" },
  "state.human_handoff": { en: "Human handoff", ml: "മനുഷ്യ ഇടപെടൽ" },
  "state.approved": { en: "Approved", ml: "അംഗീകരിച്ചു" },
  "state.rejected": { en: "Rejected", ml: "നിരസിച്ചു" },
  "state.auto_escalated": { en: "Auto-escalated", ml: "സ്വയം ഉയർത്തി" },

  "tier.A": { en: "Tier A", ml: "ടയർ A" },
  "tier.B": { en: "Tier B", ml: "ടയർ B" },
  "tier.C1": { en: "Tier C1", ml: "ടയർ C1" },
  "tier.C2": { en: "Tier C2", ml: "ടയർ C2" },

  "action.approve": { en: "Approve", ml: "അംഗീകരിക്കുക" },
  "action.reject": { en: "Reject", ml: "നിരസിക്കുക" },

  "badge.timeCritical": { en: "TIME-CRITICAL", ml: "സമയ-നിർണായകം" },

  "footer.synthetic": {
    en: "Synthetic / demo data — not a real clinical tool.",
    ml: "സിന്തറ്റിക് / ഡെമോ ഡാറ്റ — ഇത് ഒരു യഥാർത്ഥ ക്ലിനിക്കൽ ടൂൾ അല്ല.",
  },

  "lang.toggle": { en: "മലയാളം", ml: "English" },
};

const LocaleContext = createContext<{
  locale: Locale;
  setLocale: (l: Locale) => void;
}>({ locale: "en", setLocale: () => {} });

export const LocaleProvider = LocaleContext.Provider;

export function useT() {
  const { locale, setLocale } = useContext(LocaleContext);
  const t = (key: string) => dictionary[key]?.[locale] ?? key;
  return { t, locale, setLocale };
}
