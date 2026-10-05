import type { NextConfig } from "next";

const hostedExport = process.env.SOURCEX_WEB_EXPORT === "1";
const nextConfig: NextConfig = hostedExport ? {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "export",
  trailingSlash: true,
} : {
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' http://127.0.0.1:8000 http://localhost:8000; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    ] }];
  },
};

export default nextConfig;
