"use client";

import { signOut, useSession } from "next-auth/react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import LangToggle from "./LangToggle";

const NAV_LINKS = [
  { href: "/dashboard", label: "Operations Queue" },
  { href: "/dashboard/routing", label: "Routing Board" },
  { href: "/dashboard/admin", label: "Admin & Telemetry" },
  { href: "/patient", label: "🎙️ Patient Screen" },
];

export default function NavBar() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const username = (session?.user as { name?: string })?.name || (session as { username?: string })?.username;
  const roles = (session as { roles?: string[] })?.roles ?? [];
  const primaryRole = roles.includes("admin")
    ? "Admin"
    : roles.includes("doctor")
    ? "Doctor"
    : roles.includes("nurse")
    ? "Nurse"
    : "Staff";

  return (
    <header className="nav" role="banner">
      <div className="nav-inner">
        {/* Brand */}
        <Link href="/dashboard" className="brand" aria-label="Swasthya Dhwani home">
          <span className="brand-mark" aria-hidden="true">
            <Image
              src="/logo.png"
              alt="Swasthya Dhwani Emblem"
              width={36}
              height={36}
              priority
              className="brand-logo-img"
            />
          </span>
          <span>
            <span className="brand-name">Swasthya Dhwani</span>
            <span className="brand-sub">Emergency Triage OS</span>
          </span>
        </Link>

        {/* Navigation Tabs */}
        <nav aria-label="Primary navigation" style={{ marginLeft: 16 }}>
          <ul style={{ display: "flex", gap: 6, listStyle: "none", margin: 0, padding: 0 }}>
            {NAV_LINKS.map((link) => {
              const isActive =
                pathname === link.href ||
                (link.href !== "/dashboard" && pathname?.startsWith(link.href));
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="nav-link"
                    aria-current={isActive ? "page" : undefined}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <span className="nav-spacer" />

        {/* Language Switcher */}
        <LangToggle />

        {/* Authenticated User */}
        {username ? (
          <span className="user-pill">
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--ok)" }} />
            <strong>{username}</strong>
            <span className="role-tag">{primaryRole}</span>
          </span>
        ) : null}

        {/* Sign Out Button */}
        <button
          type="button"
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="btn btn-sm"
          title="Sign out of current clinician session"
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
