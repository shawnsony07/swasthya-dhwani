import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "സ്വാസ്ഥ്യ ധ്വനി · രോഗികളുടെ അടിയന്തര വോയ്സ് ട്രയാജ് | Swasthya-Dhwani Patient Triage",
  description:
    "Direct WebRTC Malayalam Voice Triage for emergency healthcare routing in Kerala.",
};

export default function PatientLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
