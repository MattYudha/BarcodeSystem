import type { NextConfig } from "next";

// Origin API FastAPI. Browser selalu memanggil /api/* di domain web ini; Next meneruskannya ke API
// (rewrite) sehingga cookie sesi first-party dan tidak perlu CORS.
// Catatan: rewrites dievaluasi saat `next build` -> set API_ORIGIN di environment build (Vercel).
const apiOrigin = (process.env.API_ORIGIN ?? "http://localhost:8000").replace(/\/$/, "");
if (process.env.VERCEL && !process.env.API_ORIGIN) {
  throw new Error("API_ORIGIN wajib di-set di environment Vercel (mis. https://api.domainanda.id)");
}

const nextConfig: NextConfig = {
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
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          // Kamera hanya untuk origin sendiri (scan barcode).
          { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
