import "./globals.css";
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { CookieBanner } from "./components/cookie-banner";

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans"
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono"
});

const SITE_URL = "https://instaply.asion.ai";
const DESCRIPTION =
  "Instaply is an agentic job-application platform. We submit applications to Greenhouse, Lever, SmartRecruiters, and Workday on your behalf. $1 per confirmed application. No subscriptions.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Instaply — $1 per confirmed job application",
    template: "%s | Instaply"
  },
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Instaply",
    title: "Instaply — $1 per confirmed job application",
    description: DESCRIPTION,
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "Instaply — $1 per confirmed job application",
    description: DESCRIPTION,
  },
  robots: {
    index: true,
    follow: true,
  },
  applicationName: "Instaply",
  authors: [{ name: "Ravendise", url: SITE_URL }],
  creator: "Ravendise",
  publisher: "Ravendise",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="app-body">
        {children}
        <CookieBanner />
      </body>
    </html>
  );
}
