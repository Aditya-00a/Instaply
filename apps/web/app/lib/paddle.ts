"use client";

/**
 * Paddle.js loader and singleton.
 *
 * Loads Paddle's CDN script lazily on first checkout open, initializes
 * with the client-side token from NEXT_PUBLIC_PADDLE_CLIENT_TOKEN, and
 * caches the global instance so subsequent checkouts open instantly.
 */

type PaddleCheckoutItem = { priceId: string; quantity: number };

type PaddleCheckoutSettings = {
  displayMode?: "overlay" | "inline";
  theme?: "light" | "dark";
  successUrl?: string;
  allowLogout?: boolean;
};

type PaddleEventData = {
  status: string;
  transaction_id?: string;
  customer?: { email?: string };
  items?: Array<{ price_id: string; quantity: number }>;
};

type PaddleEvent = {
  name: string;
  data?: PaddleEventData;
};

type PaddleSDK = {
  Initialize: (opts: {
    token: string;
    environment?: "production" | "sandbox";
    eventCallback?: (e: PaddleEvent) => void;
  }) => void;
  Checkout: {
    open: (opts: {
      items: PaddleCheckoutItem[];
      customer?: { email?: string; id?: string };
      customData?: Record<string, unknown>;
      settings?: PaddleCheckoutSettings;
    }) => void;
  };
  Environment?: { set: (env: "production" | "sandbox") => void };
};

declare global {
  interface Window {
    Paddle?: PaddleSDK;
  }
}

const PADDLE_CDN = "https://cdn.paddle.com/paddle/v2/paddle.js";

let loadingPromise: Promise<PaddleSDK | null> | null = null;

export function isPaddleConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN);
}

export async function getPaddle(): Promise<PaddleSDK | null> {
  if (typeof window === "undefined") return null;

  if (window.Paddle) return window.Paddle;
  if (loadingPromise) return loadingPromise;

  const token = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN;
  if (!token) return null;

  loadingPromise = new Promise<PaddleSDK | null>((resolve) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${PADDLE_CDN}"]`
    );
    if (existing && window.Paddle) {
      resolve(window.Paddle);
      return;
    }

    const script = existing ?? document.createElement("script");
    if (!existing) {
      script.src = PADDLE_CDN;
      script.async = true;
      document.head.appendChild(script);
    }

    script.addEventListener("load", () => {
      const sdk = window.Paddle;
      if (!sdk) {
        resolve(null);
        return;
      }
      try {
        sdk.Initialize({
          token,
          environment: token.startsWith("test_") ? "sandbox" : "production",
        });
      } catch {
        // If already initialized, that's fine.
      }
      resolve(sdk);
    });

    script.addEventListener("error", () => resolve(null));
  });

  return loadingPromise;
}

/**
 * Bonus-tier table (mirrors what the webhook handler will apply
 * server-side for real credit grants).
 */
export function bonusForAmount(amount: number): { pct: number; label: string } {
  if (amount >= 100) return { pct: 0.20, label: "+20% bonus" };
  if (amount >= 50) return { pct: 0.15, label: "+15% bonus" };
  if (amount >= 25) return { pct: 0.10, label: "+10% bonus" };
  return { pct: 0, label: "" };
}

export function totalCreditsForCustom(amount: number): number {
  const bonus = bonusForAmount(amount);
  return Math.floor(amount * (1 + bonus.pct));
}
