import type { Metadata } from "next";
import {
  Bricolage_Grotesque,
  Instrument_Sans,
  JetBrains_Mono,
  Noto_Sans_Malayalam,
} from "next/font/google";
import Providers from "@/components/Providers";
import Footer from "@/components/Footer";
import "./globals.css";

const display = Bricolage_Grotesque({
  variable: "--font-display",
  subsets: ["latin"],
});

const body = Instrument_Sans({
  variable: "--font-body",
  subsets: ["latin"],
});

const mono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

const ml = Noto_Sans_Malayalam({
  variable: "--font-ml",
  subsets: ["malayalam"],
});

export const metadata: Metadata = {
  title: "Swasthya-Dhwani Clinician Console",
  description:
    "Live triage operations, call telemetry and Kerala-tier routing for clinicians and administrators (synthetic/demo data)",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${mono.variable} ${ml.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>
          <div className="shell">
            {children}
            <Footer />
          </div>
        </Providers>
      </body>
    </html>
  );
}
