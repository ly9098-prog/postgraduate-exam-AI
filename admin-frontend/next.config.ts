import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
};

// In development, proxy /api/* and /static/* to the backend (default localhost:8000).
// Production uses nginx reverse proxy so this is not needed there.
if (process.env.NODE_ENV === "development") {
  nextConfig.rewrites = async () => [
    { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
    { source: "/static/:path*", destination: "http://localhost:8000/static/:path*" },
  ];
}

export default nextConfig;
