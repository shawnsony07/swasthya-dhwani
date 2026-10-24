"use client";

import { SessionProvider } from "next-auth/react";
import LocaleClientProvider from "./LocaleClientProvider";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <LocaleClientProvider>{children}</LocaleClientProvider>
    </SessionProvider>
  );
}
