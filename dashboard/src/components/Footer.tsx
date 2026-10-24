"use client";

import { useT } from "@/lib/i18n";

export default function Footer() {
  const { t } = useT();
  return (
    <footer className="mt-auto border-t border-amber-300 bg-amber-50 px-4 py-3 text-center text-sm font-medium text-amber-900">
      {t("footer.synthetic")}
    </footer>
  );
}
