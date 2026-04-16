/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // API is on a separate origin (Fly), so the client calls it directly with
  // CORS + bearer auth. No rewrites needed.
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "https://api.asion.ai",
  },
};
export default nextConfig;
