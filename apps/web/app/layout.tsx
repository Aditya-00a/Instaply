import "./globals.css";
import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif, Inter, JetBrains_Mono } from "next/font/google";
import { CookieBanner } from "./components/cookie-banner";

const geistSans = Geist({
  subsets: ["latin"],
  variable: "--font-geist-sans"
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono"
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif"
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter"
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono"
});

const SITE_URL = "https://instaply.asion.ai";
const TITLE = "Instaply — apply to jobs from inside Claude";
const DESCRIPTION =
  "A free, local-first MCP server that fills employer forms in your own browser. Open source. MIT licensed.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s | Instaply"
  },
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Instaply",
    title: TITLE,
    description: DESCRIPTION,
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
  robots: {
    index: true,
    follow: true,
  },
  applicationName: "Instaply",
  authors: [{ name: "Aditya Sanjay Sakhale", url: SITE_URL }],
  creator: "Aditya Sanjay Sakhale",
  publisher: "Aditya Sanjay Sakhale",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} ${inter.variable} ${jetbrainsMono.variable}`}
    >
      <body className="app-body">
        {children}
        <CookieBanner />
      </body>
    </html>
  );
}
