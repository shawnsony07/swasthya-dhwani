import { redirect } from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import { auth, signIn } from "@/auth";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string }>;
}) {
  const session = await auth();
  const { callbackUrl } = await searchParams;

  if (session) {
    redirect(callbackUrl ?? "/dashboard");
  }

  return (
    <main
      style={{
        minHeight: "calc(100vh - 120px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem 1rem",
      }}
    >
      <div
        className="kpi-card"
        style={{
          maxWidth: "480px",
          width: "100%",
          padding: "2.5rem 2rem",
          display: "flex",
          flexDirection: "column",
          gap: "1.75rem",
          borderRadius: "var(--radius)",
          background: "var(--bg-1)",
          border: "1px solid var(--line-strong)",
          boxShadow: "0 24px 48px -12px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(233, 180, 76, 0.12)",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Top accent line */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: "3px",
            background: "linear-gradient(90deg, var(--brass), var(--tb), var(--info))",
          }}
        />

        {/* Header */}
        <div style={{ textAlign: "center" }}>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: "1.25rem" }}>
            <div
              style={{
                width: "88px",
                height: "88px",
                borderRadius: "22px",
                overflow: "hidden",
                border: "2px solid rgba(19, 194, 194, 0.45)",
                boxShadow: "0 0 32px rgba(19, 194, 194, 0.3), 0 12px 24px rgba(0, 0, 0, 0.6)",
                background: "#000",
              }}
            >
              <Image
                src="/logo.png"
                alt="Swasthya Dhwani Emblem"
                width={88}
                height={88}
                priority
                style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
              />
            </div>
          </div>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              padding: "0.25rem 0.75rem",
              borderRadius: "999px",
              background: "rgba(233, 180, 76, 0.1)",
              border: "1px solid rgba(233, 180, 76, 0.3)",
              color: "var(--brass)",
              fontSize: "0.75rem",
              fontWeight: 600,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              fontFamily: "var(--font-mono)",
              marginBottom: "1rem",
            }}
          >
            <span
              style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background: "var(--brass)",
                boxShadow: "0 0 8px var(--brass)",
              }}
            />
            Hospital Identity Gateway · OIDC
          </div>
          <h1
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "1.75rem",
              fontWeight: 700,
              color: "var(--text)",
              letterSpacing: "-0.02em",
              margin: 0,
            }}
          >
            Swasthya-Dhwani
          </h1>
          <p
            style={{
              fontSize: "0.875rem",
              color: "var(--muted)",
              marginTop: "0.5rem",
              marginBottom: 0,
            }}
          >
            Clinician Triage &amp; Emergency Routing Console
          </p>
        </div>

        {/* Action Button */}
        <form
          action={async () => {
            "use server";
            await signIn("keycloak", { redirectTo: callbackUrl ?? "/dashboard" });
          }}
          style={{ width: "100%" }}
        >
          <button
            type="submit"
            className="btn btn-primary"
            style={{
              width: "100%",
              justifyContent: "center",
              padding: "0.85rem 1.5rem",
              fontSize: "0.95rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            Sign In with Keycloak SSO
          </button>
        </form>

        {/* Patient Voice Triage Portal Direct Access */}
        <div
          style={{
            background: "rgba(19, 194, 194, 0.08)",
            border: "1px solid rgba(19, 194, 194, 0.28)",
            borderRadius: "var(--radius-sm)",
            padding: "0.9rem 1rem",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "0.75rem",
          }}
        >
          <div>
            <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--text)" }}>
              🎙️ രോഗികളുടെ വോയ്സ് ട്രയാജ്
            </div>
            <div style={{ fontSize: "0.74rem", color: "var(--muted)", marginTop: 2 }}>
              Patient Voice Triage (No Login Required)
            </div>
          </div>
          <Link
            href="/patient"
            className="btn btn-sm"
            style={{
              background: "var(--tb)",
              color: "#041414",
              fontWeight: 700,
              whiteSpace: "nowrap",
              border: "none",
            }}
          >
            Open Dialer →
          </Link>
        </div>

        {/* Demo Credentials Box */}
        <div
          style={{
            background: "var(--bg-2)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            padding: "1rem",
            fontSize: "0.8rem",
          }}
        >
          <div
            style={{
              fontWeight: 600,
              color: "var(--text-dim)",
              marginBottom: "0.5rem",
              fontSize: "0.75rem",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
            }}
          >
            <span style={{ color: "var(--tb)" }}>🔑</span> Pre-seeded Demo Accounts
          </div>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontFamily: "var(--font-mono)",
              fontSize: "0.75rem",
            }}
          >
            <tbody>
              <tr style={{ borderBottom: "1px solid var(--line)" }}>
                <td style={{ padding: "0.4rem 0", color: "var(--text)" }}>doctor1</td>
                <td style={{ padding: "0.4rem 0", color: "var(--muted)" }}>doctor1pass</td>
                <td style={{ padding: "0.4rem 0", color: "var(--ta)", textAlign: "right" }}>Doctor</td>
              </tr>
              <tr style={{ borderBottom: "1px solid var(--line)" }}>
                <td style={{ padding: "0.4rem 0", color: "var(--text)" }}>admin1</td>
                <td style={{ padding: "0.4rem 0", color: "var(--muted)" }}>admin1pass</td>
                <td style={{ padding: "0.4rem 0", color: "var(--brass)", textAlign: "right" }}>Admin</td>
              </tr>
              <tr>
                <td style={{ padding: "0.4rem 0", color: "var(--text)" }}>nurse1</td>
                <td style={{ padding: "0.4rem 0", color: "var(--muted)" }}>nurse1pass</td>
                <td style={{ padding: "0.4rem 0", color: "var(--info)", textAlign: "right" }}>Nurse</td>
              </tr>
            </tbody>
          </table>
          <p
            style={{
              marginTop: "0.6rem",
              marginBottom: 0,
              fontSize: "0.7rem",
              color: "var(--muted)",
              lineHeight: 1.4,
            }}
          >
            Logging in with <strong>doctor1</strong> enables real-time approve/reject clinical triage actions.
          </p>
        </div>

        {/* Disclaimer footer */}
        <p
          style={{
            margin: 0,
            fontSize: "0.72rem",
            color: "var(--muted)",
            textAlign: "center",
            lineHeight: 1.4,
          }}
        >
          Synthetic Kerala Emergency Demo Dataset · Not for clinical deployment
        </p>
      </div>
    </main>
  );
}
