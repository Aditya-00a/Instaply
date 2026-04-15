"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const KEY = "instaply_cookie_choice_v1";

export function CookieBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(KEY);
      if (!stored) setVisible(true);
    } catch {
      // storage blocked — do not show banner rather than trap the user
    }
  }, []);

  const record = (choice: "accept" | "reject") => {
    try {
      localStorage.setItem(
        KEY,
        JSON.stringify({ choice, at: new Date().toISOString() })
      );
    } catch {
      /* noop */
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="cookie-banner" role="region" aria-label="Cookie consent">
      <div className="cookie-banner-text">
        We use essential cookies to run the site and a single first-party
        analytics cookie to understand anonymous usage. No third-party
        trackers. Read the{" "}
        <Link href="/privacy">Privacy Policy</Link> for detail.
      </div>
      <div className="cookie-banner-actions">
        <button
          type="button"
          className="cookie-banner-btn"
          onClick={() => record("reject")}
        >
          Essential only
        </button>
        <button
          type="button"
          className="cookie-banner-btn cookie-banner-btn-primary"
          onClick={() => record("accept")}
        >
          Accept all
        </button>
      </div>
    </div>
  );
}
