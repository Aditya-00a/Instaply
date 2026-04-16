/** @type {import('next').NextConfig} */

// Security headers — best-practice defaults for a SaaS web app.
// CSP intentionally allows the third-party origins we depend on:
//   - *.supabase.co for auth + storage signed URLs
//   - cdn.paddle.com for Paddle.js
//   - vercel-insights.com for analytics if/when we add it
const securityHeaders = [
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://js.stripe.com https://*.supabase.co",
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' data: https://fonts.gstatic.com",
      "img-src 'self' data: blob: https:",
      "connect-src 'self' https://*.supabase.co wss://*.supabase.co https://api.asion.ai https://*.stripe.com",
      "frame-src https://*.stripe.com https://js.stripe.com",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self' mailto:",
    ].join("; "),
  },
];

const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@instaply/contracts"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
