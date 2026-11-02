const backend = process.env.BACKEND_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
export default {
  output: "standalone",
  // Same-origin proxy: the browser only talks to :3000, so the session cookie
  // is first-party and needs no CORS.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};
