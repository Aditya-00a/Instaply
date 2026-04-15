import type { MetadataRoute } from "next";

const SITE = "https://instaply.asion.ai";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // Don't let crawlers waste budget on auth and app routes — they
        // all require a session and return the same shell anyway.
        disallow: [
          "/sign-in",
          "/dashboard",
          "/applications",
          "/review",
          "/documents",
          "/onboarding",
          "/billing",
          "/settings",
          "/api/",
        ],
      },
    ],
    sitemap: `${SITE}/sitemap.xml`,
    host: SITE,
  };
}
