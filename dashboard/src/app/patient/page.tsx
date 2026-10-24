"use client";

import dynamic from "next/dynamic";

const PatientVoiceClient = dynamic(() => import("./PatientVoiceClient"), {
  ssr: false,
  loading: () => (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#080d12",
        color: "var(--muted)",
        fontFamily: "var(--font-mono)",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: "1.5rem", marginBottom: "0.5rem" }}>🎙️</div>
        <div>സ്വാസ്ഥ്യ ധ്വനി ലോഡ് ചെയ്യുന്നു... (Loading Voice Triage)</div>
      </div>
    </div>
  ),
});

export default function PatientPage() {
  return <PatientVoiceClient />;
}
