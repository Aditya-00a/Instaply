// Greenhouse content script.
//
// State machine on the apply page:
//   1. boot       → fetch per-tab payload from background; bail silently if none
//   2. filling    → wait for form to mount, fill identity fields + saved answers
//   3. filled     → tell user "review and click Submit when ready"
//   4. verification → if a captcha widget renders, hold the banner open and
//                     wait for the user to solve it
//   5. ready      → captcha solved (token populated): tell user to click Submit
//   6. submitting → user clicked Submit; watch for navigation/text confirmation
//   7. done       → confirmation observed; POST extension-finish so the row
//                   is auto-marked as submitted in Instaply
//
// We never click the page's Submit button ourselves. The user always
// performs the final submit — that's the honest contract with the
// employer's ATS.

(async function init() {
  let payload;
  try {
    payload = await chrome.runtime.sendMessage({ type: "get_fill_payload" });
  } catch (_) {
    payload = null;
  }
  if (!payload) return; // direct browse — silent

  const ns = window.__instaply;
  ns.showStatus("filling", { message: "Looking for the application form…" });

  const form = await ns.waitFor(
    () => document.querySelector('form, #application_form, [data-qa="application-form"]'),
    8000,
  );
  if (!form) {
    ns.showStatus("error", { message: "Couldn't find the application form on this page." });
    return;
  }

  const filled = ns.fillForm(payload);
  ns.showStatus("filled", {
    message: `Filled ${filled} field${filled === 1 ? "" : "s"} from your Instaply profile. Review what's on screen, then click Submit Application when you're ready.`,
  });

  // ── Captcha state machine ─────────────────────────────────────
  // Watch the DOM for either a captcha widget appearing OR a confirmation
  // page replacing the form.
  let state = "filled";
  const setState = (next, opts) => {
    state = next;
    ns.showStatus(next, opts);
  };

  const obs = new MutationObserver(() => {
    if (state === "done" || state === "submitting") return;
    // Confirmation page reached without a captcha (rare on real GH but
    // possible if reCAPTCHA scored the user safe and let them through).
    const conf = ns.detectConfirmation();
    if (conf.ok) {
      setState("done", { message: "Submitted. Marking complete in Instaply…" });
      finishUpstream();
      return;
    }
    if (state === "filled" && ns.detectCaptcha()) {
      setState("verification", {
        message: "Verification required. Solve the captcha on the page — Instaply will continue automatically once it's done.",
      });
    } else if (state === "verification" && ns.detectCaptchaSolved()) {
      setState("ready", {
        message: "Verification done. Click Submit Application on the page.",
      });
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });

  // ── Watch the user's submit click → "submitting" → confirmation ──
  // We don't click the button ourselves. We listen for the user
  // clicking the page's real submit, then poll for the confirmation
  // signal so we can auto-report.
  document.addEventListener("click", (e) => {
    if (state === "done" || state === "submitting") return;
    const target = e.target;
    if (!(target instanceof Element)) return;
    const btn = target.closest('button, input[type="submit"]');
    if (!btn) return;
    const txt = (btn.textContent || btn.value || "").trim().toLowerCase();
    const looksLikeSubmit =
      btn.id === "submit_app" ||
      btn.getAttribute("data-action") === "submit" ||
      btn.getAttribute("type") === "submit" ||
      /submit application|submit$/i.test(txt);
    if (looksLikeSubmit) {
      setState("submitting", { message: "Submitting…" });
      pollForConfirmation();
    }
  }, true);

  async function pollForConfirmation() {
    for (let i = 0; i < 30; i++) { // 30 × 500ms = 15s window
      await new Promise((r) => setTimeout(r, 500));
      const conf = ns.detectConfirmation();
      if (conf.ok) {
        setState("done", { message: "Submitted. Marking complete in Instaply…" });
        finishUpstream();
        return;
      }
    }
    // No confirmation in 15s — could be slow page or silent rejection.
    // Fall back to ready-style guidance so the user can decide.
    setState("ready", {
      message: "Couldn't confirm submission yet. If the page shows a Thank-you state, click below to mark complete in Instaply.",
      action: { label: "I submitted this", onClick: () => finishUpstream() },
    });
  }

  let _finishedUpstream = false;
  async function finishUpstream() {
    if (_finishedUpstream) return;
    _finishedUpstream = true;
    if (!payload.applicationId || !payload.accessToken) {
      // Web didn't push a token — just leave the user on the dashboard's
      // "I submitted this manually" path.
      setState("done", {
        message: "Submitted on the page. Open Instaply and click \"I submitted this manually\" on the Vercel/Greenhouse card to mark complete.",
      });
      return;
    }
    const r = await ns.reportFinish({
      applicationId: payload.applicationId,
      accessToken: payload.accessToken,
      apiBase: payload.apiBase || "https://api.asion.ai",
    });
    if (r.ok) {
      setState("done", { message: "Submitted and marked complete in Instaply. You can close this tab." });
      try { obs.disconnect(); } catch (_) {}
    } else {
      setState("error", {
        message: `Submitted on the page, but couldn't auto-report to Instaply (${r.error || "unknown"}). Open Instaply and click "I submitted this manually" on the card.`,
      });
    }
  }

  // Stop the DOM observer after 10 minutes regardless — long-lived
  // observers become a memory cost on tabs the user leaves open.
  setTimeout(() => { try { obs.disconnect(); } catch (_) {} }, 10 * 60 * 1000);
})();
