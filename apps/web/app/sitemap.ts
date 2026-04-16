import type { MetadataRoute } from "next";

const SITE = "https://instaply.asion.ai";

// Public, indexable routes only. Auth and app routes are intentionally
// excluded — they require a session anyway and we do not want them in
// search results.
const PUBLIC_ROUTES = [
  { path: "/", priority: 1.0, changeFrequency: "weekly" as const },
  { path: "/pricing", priority: 0.9, changeFrequency: "weekly" as const },
  { path: "/about", priority: 0.8, changeFrequency: "monthly" as const },
  { path: "/how-it-works", priority: 0.8, changeFrequency: "monthly" as const },
  { path: "/integrations", priority: 0.7, changeFrequency: "monthly" as const },
  { path: "/security", priority: 0.6, changeFrequency: "monthly" as const },
  { path: "/status", priority: 0.5, changeFrequency: "daily" as const },
  { path: "/changelog", priority: 0.7, changeFrequency: "weekly" as const },
  { path: "/careers", priority: 0.5, changeFrequency: "monthly" as const },
  { path: "/contact", priority: 0.6, changeFrequency: "monthly" as const },
  { path: "/sign-in", priority: 0.7, changeFrequency: "monthly" as const },
  { path: "/terms", priority: 0.4, changeFrequency: "yearly" as const },
  { path: "/privacy", priority: 0.4, changeFrequency: "yearly" as const },
  { path: "/refund", priority: 0.4, changeFrequency: "yearly" as const },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return PUBLIC_ROUTES.map((r) => ({
    url: `${SITE}${r.path}`,
    lastModified,
    changeFrequency: r.changeFrequency,
    priority: r.priority,
  }));
}
