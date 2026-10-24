import { auth } from "@/auth";
import { NextResponse } from "next/server";

/**
 * Gate every dashboard route behind a session; unauthenticated users land
 * on /login (task scope item 2). /login and the NextAuth API routes stay
 * public so the sign-in redirect itself is reachable.
 */
export default auth((req) => {
  const { pathname } = req.nextUrl;
  const isPublic =
    pathname.startsWith("/login") ||
    pathname.startsWith("/patient") ||
    pathname.startsWith("/api/patient") ||
    pathname.startsWith("/api/auth") ||
    pathname.startsWith("/_next") ||
    pathname === "/favicon.ico" ||
    pathname === "/logo.png" ||
    pathname === "/icon.png" ||
    /\.(png|jpg|jpeg|svg|ico|webp)$/.test(pathname);

  if (isPublic) return NextResponse.next();

  if (!req.auth) {
    const loginUrl = new URL("/login", req.nextUrl.origin);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
});

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|logo.png|icon.png|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
