# Instaply Chrome extension (MVP 0.0.1)

Smallest real Chrome MV3 extension that lets the Instaply web app continue
captcha- or verification-blocked applications inside the user's own browser.

## What it does today

1. The Instaply dashboard pings the extension to confirm it's installed
   (`chrome.runtime.sendMessage` against `externally_connectable`).
2. When the user clicks "Open & finish" on a `Needs attention` row, the
   web app sends a `fill` message containing `{ url, applicationId, profile, answers }`.
3. The service worker opens the apply URL in a new tab and stashes the
   payload keyed by `tabId` in `chrome.storage.session` (ephemeral).
4. The matching content script (`greenhouse.js` or `lever.js`) reads the
   payload at boot, fills the form (identity fields + saved-answer reuse),
   and shows a small banner.
5. If a captcha widget appears, a held-open banner tells the user to solve
   it manually. **The extension never bypasses captchas.** This is intentional.

## What it does NOT do (yet)

- No login flow / no credential storage. The web app holds the user session
  and pushes data per fill request. Direct browses to GH/Lever pages without
  a fill request silently no-op.
- No Workday / SmartRecruiters support — only Greenhouse and Lever for now.
- No retry-after-solve automation. After captcha solve the user clicks the
  Submit button themselves, then comes back to Instaply and clicks
  "I submitted this manually."
- No popup-based connection management. The popup is a status indicator only.
- No Chrome Web Store listing. Loaded unpacked for development.

## Files

```
extension/
├── manifest.json                       MV3 manifest, externally_connectable
├── background/service-worker.js        Handshake + per-tab payload stash
├── content/_fillers.js                 Shared field matchers + helpers
├── content/greenhouse.js               GH content script (job-boards / boards)
├── content/lever.js                    Lever content script (jobs.lever.co)
├── popup/popup.html                    Status popup
├── popup/popup.js                      Active-tab detection
└── popup/popup.css                     Popup styling
```

The web side adds:

```
apps/web/app/lib/extension.ts           isExtensionInstalled() + triggerExtensionFill()
```

## Loading unpacked (development)

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select `C:\Ravendise\Instaply\extension`.
4. Copy the auto-generated **extension ID** from the new card (a 32-char string).
5. Add `NEXT_PUBLIC_EXTENSION_ID=<that-id>` to `apps/web/.env.local`
   AND to your Vercel production env vars.
6. Redeploy web. The dashboard's `isExtensionInstalled()` will now resolve
   to `true` for clients with the extension.

## Stable extension ID across reloads

Without a `key` field, Chrome generates a new extension ID every time
the unpacked extension is loaded into a fresh Chrome profile. That's
fine for one-shot testing; for reliable dev (and production-style
testing of the dashboard wiring) you want the ID to stay constant so
`NEXT_PUBLIC_EXTENSION_ID` doesn't drift.

**One-time setup (run once, paste the result into `manifest.json`):**

PowerShell:
```powershell
# Generate a 2048-bit RSA key, extract the public key in DER form,
# base64-encode it, and print a manifest-ready snippet.
openssl genrsa 2048 2>$null | openssl rsa -pubout -outform DER 2>$null | base64 -w0
```

Bash / Git Bash:
```bash
openssl genrsa 2048 2>/dev/null | openssl rsa -pubout -outform DER 2>/dev/null | base64 -w0
```

Add the resulting base64 string as `"key"` at the top level of
`manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "Instaply",
  "key": "MIIBIjANBgkqhkiG9w0BAQEFAAOC...PASTE_HERE",
  "version": "0.0.1",
  ...
}
```

Reload the extension once. The ID is now permanent for that key
across reloads, fresh installs, and other Chrome profiles loaded
unpacked from the same source.

The `key` field MUST stay out of source control if it's tied to a
private key you intend to keep — but for a dev-only ID it's harmless.
For production publishing on the Chrome Web Store, the store assigns
the final permanent ID (different from the dev key's ID) and you
should remove the `key` field before submitting.

## What still needs to be wired before onboarding can require it

In rough cost order, smallest first:

1. **Stable extension ID across reinstalls.** The dev workflow above gives a
   different ID every time the unpacked extension is reloaded. Either:
   - Add a `"key"` field to `manifest.json` (RSA public key — pin a stable ID
     across all dev installs), OR
   - Publish to the Chrome Web Store (final IDs are permanent post-publish).
2. **Dashboard wiring.** On `Needs attention` cards with `submit_reason` of
   `captcha_required` / `verification_required`, change the `Open & finish`
   button to call `triggerExtensionFill()` when `isExtensionInstalled()`
   returns true; fall back to the plain link otherwise.
3. **Onboarding step.** A new step in `apps/web/app/onboarding/page.tsx`
   that polls `isExtensionInstalled()` every 1.5 s while the step is
   visible. Auto-advance the moment it returns true. After 60 s with no
   detection, surface a "I've installed it" acknowledge button — only
   because the polling is real and the button is the explicit-acknowledgement
   escape hatch.
4. **Chrome Web Store listing** (when ready to publish) — produces a stable
   ID and lets the extension be discoverable.
5. **Workday / SmartRecruiters content scripts** if you want extension
   coverage to match worker coverage.
6. **Optional: post-submit confirmation reporting.** A tiny content-script
   message back to the background after the user clicks the page's submit
   button, so the web can mark the row complete without the user having to
   click "I submitted this manually."

## Constraints respected

- No CapSolver / 2Captcha / any captcha-bypass service.
- No automated captcha solving in any form.
- No marketplace polish (no logo design, no store assets).
- No multi-browser support (Firefox/Safari out of scope).
- No redesign of the dashboard.

## Architecture rationale

The extension is intentionally a **remote-controlled filler**: the web app
holds the user's session and pushes data per request. This avoids the
biggest risks of a self-contained extension MVP (auth flows, secret
storage, drift between extension and worker rules). A future evolution
can add direct extension auth + on-page Instaply login if the product
needs it; today the dashboard-originated flow is enough to unblock the
captcha-gated cases the worker can't finish.
