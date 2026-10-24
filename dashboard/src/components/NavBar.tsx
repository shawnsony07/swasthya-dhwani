"use client";

import { signOut, useSession } from "next-auth/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import LangToggle from "./LangToggle";

const NAV_LINKS = [
  { href: "/dashboard", label: "Operations" },
  { href: "/dashboard/admin", label: "Admin" },
  { href: "/dashboard/routing", label: "Routing Board" },
];

export default function NavBar() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const username = (session?.user as { name?: string })?.name;

  return (
    <header className="nav" role="banner">
      <div className="nav-inner">
        <Link href="/dashboard" className="brand" aria-label="Swasthya Dhwani home">
          <span className="brand-mark" aria-hidden="true">ω</span>
          <span>
            <span className="brand-name">Swasthya Dhwani</span>
            <span className="brand-sub">Clinician Console</span>
          </span>
        </Link>

        <nav aria-label="Primary navigation">
          <ul style={{ display: "flex", gap: 2, listStyle: "none", margin: 0, padding: 0 }}>
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className="nav-link"
                  aria-current={
                    pathname === link.href ||
                    (link.href !== "/dashboard" && pathname?.startsWith(link.href))
                      ? "page"
                      : undefined
                  }
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <span className="nav-spacer" />

        <LangToggle />

        {username ? (
          <span className="user-pill">
            <strong>{username}</strong>
            <span className="role-tag">Clinician</span>
          </span>
        ) : null}

        <button
          type="button"
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="btn btn-sm"
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
