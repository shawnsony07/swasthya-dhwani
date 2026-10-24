"use client";

import { useT } from "@/lib/i18n";

export default function LangToggle() {
  const { t, locale, setLocale } = useT();
  return (
    <button
      type="button"
      onClick={() => setLocale(locale === "en" ? "ml" : "en")}
      className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
    >
      {t("lang.toggle")}
    </button>
  );
}
