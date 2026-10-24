"use client";

import { signOut } from "next-auth/react";
import Link from "next/link";
import { useT } from "@/lib/i18n";
import LangToggle from "./LangToggle";

export default function NavBar({ username }: { username?: string }) {
  const { t } = useT();
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3">
      <Link
        href="/dashboard"
        className="text-lg font-semibold text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      >
        {t("nav.title")}
      </Link>
      <div className="flex items-center gap-3">
        <LangToggle />
        {username ? (
          <span className="text-sm text-slate-600">
            {t("nav.signedInAs")}: <strong>{username}</strong>
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
        >
          {t("nav.signOut")}
        </button>
      </div>
    </header>
  );
}
