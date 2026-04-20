// Lever content script. Same state machine as the Greenhouse one;
// only the form selector + submit-button heuristics differ.

(async function init() {
  let payload;
  try {
    payload = await chrome.runtime.sendMessage({ type: "get_fill_payload" });
  } catch (_) {
    payload = null;
  }
  if (!payload) return;

  const ns = window.__instaply;
  ns.showStatus("filling", { message: "Looking for the application form…" });

  const form = await ns.waitFor(
    () => document.querySelector('form[data-qa="application-form"], form.application-form, form'),
    8000,
  );
  if (!form) {
    ns.showStatus("error", { message: "Couldn't find the application form on this page." });
    return;
  }

  const filled = ns.fillForm(payload);
  ns.showStatus("filled", {
    message: `Filled ${filled} field${filled === 1 ? "" : "s"} from your Instaply profile. Review what's on screen, then click Submit application when you're ready.`,
  });

  let state = "filled";
  const setState = (next, opts) => {
    state = next;
    ns.showStatus(next, opts);
  };

  const obs = new MutationObserver(() => {
    if (state === "done" || state === "submitting") return;
    const conf = ns.detectConfirmation();
    if (conf.ok) {
      setState("done", { message: "Submitted. Marking complete in Instaply…" });
      finishUpstream();
      return;
    }
    if (state === "filled" && ns.detectCaptcha()) {
      setState("verification", {
        message: "Verification required. Solve the hCaptcha on the page — Instaply will continue automatically once it's done.",
      });
    } else if (state === "verification" && ns.detectCaptchaSolved()) {
      setState("ready", {
        message: "Verification done. Click Submit application on the page.",
      });
    }
  });
  obs.observe(document.body, { childList: true, subtree: true });

  document.addEventListener("click", (e) => {
    if (state === "done" || state === "submitting") return;
    const target = e.target;
    if (!(target instanceof Element)) return;
    const btn = target.closest('button, input[type="submit"]');
    if (!btn) return;
    const txt = (btn.textContent || btn.value || "").trim().toLowerCase();
    const looksLikeSubmit =
      btn.id === "btn-submit" ||
      btn.getAttribute("data-qa") === "btn-submit" ||
      /submit application|submit application$|submit$/i.test(txt);
    if (looksLikeSubmit) {
      setState("submitting", { message: "Submitting…" });
      pollForConfirmation();
    }
  }, true);

  async function pollForConfirmation() {
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 500));
      const conf = ns.detectConfirmation();
      if (conf.ok) {
        setState("done", { message: "Submitted. Marking complete in Instaply…" });
        finishUpstream();
        return;
      }
    }
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
      setState("done", {
        message: "Submitted on the page. Open Instaply and click \"I submitted this manually\" on the Lever card to mark complete.",
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

  setTimeout(() => { try { obs.disconnect(); } catch (_) {} }, 10 * 60 * 1000);
})();
