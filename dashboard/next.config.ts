import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // cacheComponents/PPR disabled: every route here is session-gated
  // (middleware + NextAuth) and fetches live task/alert data per request,
  // so there's nothing worth statically prerendering -- and leaving it on
  // forces every dynamic read behind an explicit Suspense/"use cache"
  // boundary for no benefit on a dashboard that's dynamic end to end.
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
