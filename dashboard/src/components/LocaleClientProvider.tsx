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
    try {
      const stored = window.localStorage.getItem("swasthya.locale");
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
