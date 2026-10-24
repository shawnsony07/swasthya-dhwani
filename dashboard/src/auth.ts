import NextAuth from "next-auth";
import Keycloak from "next-auth/providers/keycloak";
import type { JWT } from "next-auth/jwt";

const keycloakBaseUrl =
  process.env.KEYCLOAK_BASE_URL ?? "http://localhost:8081";
const keycloakRealm = process.env.KEYCLOAK_REALM ?? "swasthya";

/**
 * Realm roles we care about, read from the Keycloak access token's
 * `realm_access.roles` claim (docs/api_contract.md "Auth"). Same claim
 * shape the FastAPI backend reads server-side -- this is purely for
 * client-side UI gating (show/hide approve buttons); the backend is the
 * real enforcement point (defense in depth, per the task scope).
 */
export type Role = "doctor" | "nurse" | "admin";

function decodeRolesFromAccessToken(accessToken: string | undefined): Role[] {
  if (!accessToken) return [];
  try {
    const payload = accessToken.split(".")[1];
    if (!payload) return [];
    const json = Buffer.from(payload, "base64url").toString("utf8");
    const claims = JSON.parse(json) as {
      realm_access?: { roles?: string[] };
    };
    const roles = claims.realm_access?.roles ?? [];
    return roles.filter((r): r is Role =>
      r === "doctor" || r === "nurse" || r === "admin"
    );
  } catch {
    return [];
  }
}

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    roles?: Role[];
    username?: string;
    error?: "RefreshAccessTokenError";
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    accessTokenExpiresAt?: number;
    roles?: Role[];
    username?: string;
    error?: "RefreshAccessTokenError";
  }
}

async function refreshAccessToken(token: JWT): Promise<JWT> {
  if (!token.refreshToken) {
    return { ...token, error: "RefreshAccessTokenError" };
  }
  try {
    const response = await fetch(
      `${keycloakBaseUrl}/realms/swasthya/protocol/openid-connect/token`,
      {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          client_id: process.env.KEYCLOAK_CLIENT_ID ?? "swasthya-dashboard",
          grant_type: "refresh_token",
          refresh_token: token.refreshToken,
        }),
      }
    );
    const refreshed = await response.json();
    if (!response.ok) {
      throw new Error(refreshed.error_description ?? "refresh failed");
    }
    return {
      ...token,
      accessToken: refreshed.access_token,
      accessTokenExpiresAt: Date.now() + refreshed.expires_in * 1000,
      refreshToken: refreshed.refresh_token ?? token.refreshToken,
      roles: decodeRolesFromAccessToken(refreshed.access_token),
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshAccessTokenError" };
  }
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  trustHost: true,
  providers: [
    Keycloak({
      issuer: `${keycloakBaseUrl}/realms/swasthya`,
      clientId: process.env.KEYCLOAK_CLIENT_ID ?? "swasthya-dashboard",
      // Public client (no secret) per architecture.md section 11 and the
      // task brief -- Keycloak client "swasthya-dashboard" has no secret
      // configured. Auth.js's Keycloak provider accepts an empty string
      // for public clients using the authorization_code + PKCE flow.
      clientSecret: "",
      checks: ["pkce", "state"],
    }),
  ],
  session: { strategy: "jwt" },
  pages: {
    signIn: "/login",
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account) {
        token.accessToken = account.access_token;
        token.refreshToken = account.refresh_token;
        token.accessTokenExpiresAt = account.expires_at
          ? account.expires_at * 1000
          : undefined;
        token.roles = decodeRolesFromAccessToken(account.access_token);
        token.username =
          (profile?.preferred_username as string | undefined) ??
          (profile?.name as string | undefined) ??
          token.sub;
        return token;
      }

      if (
        token.accessTokenExpiresAt &&
        Date.now() > token.accessTokenExpiresAt - 10_000
      ) {
        return refreshAccessToken(token);
      }

      return token;
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken;
      session.roles = token.roles ?? [];
      session.username = token.username;
      session.error = token.error;
      return session;
    },
  },
});
