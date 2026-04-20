/** @type {import('next').NextConfig} */

// Security headers — best-practice defaults for a SaaS web app.
// CSP intentionally allows the third-party origins we depend on:
//   - *.supabase.co for auth + storage signed URLs
//   - checkout.razorpay.com for the payment overlay
//   - api.asion.ai for our backend
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
      // 'unsafe-inline' is required for Next.js inline runtime + Razorpay's
      // SDK; 'unsafe-eval' has been dropped — Razorpay v1 doesn't need it
      // and Next.js app-router doesn't either. Reduces XSS blast radius.
      "script-src 'self' 'unsafe-inline' https://checkout.razorpay.com https://*.supabase.co",
      "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
      "font-src 'self' data: https://fonts.gstatic.com",
      "img-src 'self' data: blob: https:",
      "connect-src 'self' https://*.supabase.co wss://*.supabase.co https://api.asion.ai https://*.razorpay.com https://lumberjack.razorpay.com",
      "frame-src https://*.razorpay.com https://api.razorpay.com",
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
