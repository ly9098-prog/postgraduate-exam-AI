import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

// In development, proxy /api/* and /static/* to the backend (default localhost:8000).
// Production uses nginx reverse proxy so this is not needed there.
if (process.env.NODE_ENV === "development") {
  // Next.js 16 blocks dev assets/HMR from 127.0.0.1 unless the host is
  // explicitly allowed. Without hydration, the login form does a native GET.
  nextConfig.allowedDevOrigins = ["127.0.0.1"];
  nextConfig.rewrites = async () => [
    {
      source: "/api/admin/:path*",
      destination: `${process.env.ADMIN_API_ORIGIN ?? "http://localhost:8000"}/api/admin/:path*`,
    },
    {
      source: "/api/v1/:path*",
      destination: `${process.env.ADMIN_API_ORIGIN ?? "http://localhost:8000"}/api/v1/:path*`,
    },
    {
      source: "/static/:path*",
      destination: `${process.env.ADMIN_API_ORIGIN ?? "http://localhost:8000"}/static/:path*`,
    },
  ];
}

export default nextConfig;
