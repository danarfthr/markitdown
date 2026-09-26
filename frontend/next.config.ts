import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /*
   * Dev-only bridge to the Python service.
   *
   * In production, Vercel Services routes /api/* to the Python service via the
   * top-level rewrites in ../vercel.json. `next dev` knows nothing about
   * vercel.json, so without this the frontend would POST /api/convert to itself
   * and get a 404 while developing locally.
   *
   * The destination is the local uvicorn server (see README). This rewrite is
   * inert in production because Vercel routes /api/* before Next.js ever sees it.
   */
  async rewrites() {
    if (process.env.NODE_ENV === "production") return [];
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
