import type { NextConfig } from "next";

// Proxy backend calls through the Next server so the browser only ever talks
// to the frontend origin (no CORS, works identically behind tunnels/deployments).
const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://localhost:8900";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["66.116.234.71"],
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${backendOrigin}/:path*` }];
  },
};

export default nextConfig;
