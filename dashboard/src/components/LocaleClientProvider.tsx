"use client";

import { useEffect, useState } from "react";
import { LocaleProvider, type Locale } from "@/lib/i18n";

export default function LocaleClientProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    // One-time hydration correction, not a cascading-render risk: the
    // server has no localStorage, so the initial render must default to
    // "en" to avoid a hydration mismatch, and the real value can only be
    // read after mount. This sets state at most once per mount, never in
    // response to a changing dependency.
    try {
      const stored = window.localStorage.getItem("swasthya.locale");
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (stored === "en" || stored === "ml") setLocaleState(stored);
    } catch {
      // localStorage unavailable; default to English
    }
  }, []);

  const setLocale = (l: Locale) => {
    setLocaleState(l);
    try {
      window.localStorage.setItem("swasthya.locale", l);
    } catch {
      // ignore
    }
  };

  return (
    <LocaleProvider value={{ locale, setLocale }}>{children}</LocaleProvider>
  );
}
