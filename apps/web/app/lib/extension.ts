/**
 * Helpers for talking to the Instaply Chrome extension.
 *
 * The extension exposes itself via `chrome.runtime.sendMessage(EXT_ID, ...)`
 * (manifest `externally_connectable` matches `instaply.asion.ai/*`).
 * The extension ID is set via NEXT_PUBLIC_EXTENSION_ID. Without it,
 * every helper resolves to "not installed" and the dashboard falls
 * back to its existing Open & finish flow with no surprises.
 *
 * Wiring path before the dashboard or onboarding can rely on this:
 *   1. Build the extension in C:\Ravendise\Instaply\extension\.
 *   2. Load it unpacked in Chrome (chrome://extensions → Developer mode
 *      → Load unpacked → select that directory). Copy the auto-generated
 *      ID from the extension card.
 *   3. Set NEXT_PUBLIC_EXTENSION_ID in your Vercel env (production)
 *      and .env.local (dev). Redeploy web.
 *   4. For a stable production ID across reinstalls, add a `key` field
 *      to manifest.json (RSA public key) before publishing.
 */

const EXTENSION_ID = process.env.NEXT_PUBLIC_EXTENSION_ID || "";
const PING_TIMEOUT_MS = 800;

// `chrome` is injected globally by Chromium for pages allowed by the
// extension's externally_connectable manifest match. TypeScript doesn't
// ship types for it; declare a minimal subset so we don't pull in
// @types/chrome for this single integration.
declare const chrome:
  | {
      runtime?: {
        sendMessage?: (
          extensionId: string,
          message: unknown,
          callback: (response: unknown) => void,
        ) => void;
        lastError?: { message?: string };
      };
    }
  | undefined;

function _hasChromeRuntime(): boolean {
  return typeof chrome !== "undefined" && !!chrome?.runtime?.sendMessage;
}

export interface PingResponse {
  ok: boolean;
  version?: string;
}

/**
 * Returns true if the Instaply extension is installed AND alive.
 * Pings the extension and waits up to PING_TIMEOUT_MS for a response.
 * If EXTENSION_ID isn't configured (env var unset), short-circuits to
 * false so non-extension users never trip a console error.
 */
export async function isExtensionInstalled(): Promise<boolean> {
  if (!EXTENSION_ID || !_hasChromeRuntime()) return false;
  return new Promise<boolean>((resolve) => {
    let done = false;
    const timer = setTimeout(() => {
      if (!done) {
        done = true;
        resolve(false);
      }
    }, PING_TIMEOUT_MS);
    try {
      chrome!.runtime!.sendMessage!(EXTENSION_ID, { type: "ping" }, (resp) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        // Reading lastError clears it so it doesn't bubble as a noisy
        // unchecked error in the page console when the extension is
        // simply not installed.
        const err = chrome?.runtime?.lastError;
        if (err) return resolve(false);
        const r = resp as PingResponse | undefined;
        resolve(!!(r && r.ok));
      });
    } catch {
      done = true;
      clearTimeout(timer);
      resolve(false);
    }
  });
}

export interface FillRequest {
  applicationId: string;
  applyUrl: string;
  // Optional auth payload. When present, the extension's content
  // script can call POST /applications/{id}/extension-finish on the
  // user's behalf to auto-mark the row submitted after the user
  // completes verification + clicks Submit on the page. When absent,
  // the extension still fills + guides through verification, but the
  // user has to come back to the dashboard and click "I submitted
  // this manually" to close the loop.
  accessToken?: string;
  apiBase?: string;
  // Subset of UserProfile the extension's content scripts can use. Web
  // app builds this from the user's authenticated session — the
  // extension never touches Supabase directly.
  profile: {
    first_name?: string | null;
    last_name?: string | null;
    full_name?: string | null;
    email?: string | null;
    phone_e164?: string | null;
    phone_national?: string | null;
    phone?: string | null;
    linkedin_url?: string | null;
    github_url?: string | null;
    portfolio_url?: string | null;
    website_url?: string | null;
    city?: string | null;
    current_city?: string | null;
    state?: string | null;
    current_state?: string | null;
    country?: string | null;
    current_country?: string | null;
    postal_code?: string | null;
    zip_code?: string | null;
    current_company?: string | null;
    current_title?: string | null;
    school?: string | null;
    major?: string | null;
    degree?: string | null;
  };
  answers: Array<{ question_text: string; answer_text: string }>;
}

export interface FillResponse {
  ok: boolean;
  tabId?: number;
  error?: string;
}

/**
 * Asks the extension to open the apply URL and fill it with the given
 * profile + saved-answer payload. The extension opens the tab; the
 * matching content script picks up the payload at boot and fills.
 *
 * Captcha pages are NOT bypassed — the user solves them in their own
 * browser. Same conservative contract as the worker.
 */
export async function triggerExtensionFill(req: FillRequest): Promise<FillResponse> {
  if (!EXTENSION_ID || !_hasChromeRuntime()) {
    return { ok: false, error: "extension_not_available" };
  }
  return new Promise<FillResponse>((resolve) => {
    try {
      chrome!.runtime!.sendMessage!(
        EXTENSION_ID,
        {
          type: "fill",
          url: req.applyUrl,
          applicationId: req.applicationId,
          accessToken: req.accessToken,
          apiBase: req.apiBase,
          profile: req.profile,
          answers: req.answers,
        },
        (resp) => {
          const err = chrome?.runtime?.lastError;
          if (err) {
            return resolve({ ok: false, error: err.message || "runtime_error" });
          }
          resolve((resp as FillResponse) || { ok: false, error: "no_response" });
        },
      );
    } catch (e) {
      resolve({
        ok: false,
        error: e instanceof Error ? e.message : "send_failed",
      });
    }
  });
}
