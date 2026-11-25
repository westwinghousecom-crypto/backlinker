import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // standalone is only for the Docker image; Vercel builds its own output and must not use it.
  ...(process.env.VERCEL ? {} : { output: "standalone" as const }),
  poweredByHeader: false,
  compress: true,
  async redirects() {
    return [
      { source: "/", destination: "/dashboard", permanent: false },
      { source: "/app", destination: "/dashboard", permanent: false },
      { source: "/signin", destination: "/login", permanent: true },
      { source: "/sign-in", destination: "/login", permanent: true },
      { source: "/signup", destination: "/register", permanent: true },
      { source: "/sign-up", destination: "/register", permanent: true },
      { source: "/privacy-policy", destination: "/privacy", permanent: true },
      { source: "/terms-of-service", destination: "/terms", permanent: true },
    ];
  },
  // Same-origin API proxy. On Vercel it is enabled only when BACKEND_ORIGIN is set (otherwise the browser calls
  // NEXT_PUBLIC_API_URL directly). Locally it falls back to the backend on 127.0.0.1 (not localhost: Node may resolve ::1).
  async rewrites() {
    const backend = process.env.BACKEND_ORIGIN ?? (process.env.VERCEL ? "" : "http://127.0.0.1:8000");
    if (!backend) return [];
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/batches/:path*", destination: `${backend}/batches/:path*` },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
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
