// Instaply MV3 service worker.
//
// Two responsibilities, intentionally narrow for the MVP:
//   1. Handshake with the Instaply web app (instaply.asion.ai) over
//      `chrome.runtime.sendMessage` so the dashboard can detect the
//      extension is installed and trigger fills.
//   2. Stash a per-tab fill payload that content scripts read on boot
//      via `chrome.storage.session`. Session storage is ephemeral
//      (cleared on browser restart) — exactly right for one-shot fill
//      requests, and avoids any persistent secret on disk.
//
// What this MVP deliberately does NOT do:
//   - No login flow / no credential storage. The web app holds the
//     user's session and pushes profile + answers per fill request.
//   - No captcha solving. Content scripts pause and prompt the user.
//   - No background polling. All work is reactive to a message.

const VERSION = "0.0.1";

// External messages — from the Instaply web app (matches in
// manifest.externally_connectable). Returns within 5 minutes per MV3
// contract; we resolve in milliseconds.
chrome.runtime.onMessageExternal.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg !== "object") {
    sendResponse({ ok: false, error: "invalid_message" });
    return false;
  }

  if (msg.type === "ping") {
    sendResponse({ ok: true, version: VERSION });
    return false;
  }

  if (msg.type === "fill") {
    handleFill(msg).then(sendResponse).catch((err) => {
      sendResponse({ ok: false, error: String((err && err.message) || err) });
    });
    return true; // keep the message channel open for async sendResponse
  }

  sendResponse({ ok: false, error: `unknown_type:${msg.type}` });
  return false;
});

async function handleFill(msg) {
  const { url, profile, answers, applicationId, accessToken, apiBase } = msg;
  if (!url || typeof url !== "string") {
    return { ok: false, error: "missing_or_invalid_url" };
  }
  if (!/^https:\/\/(job-boards\.greenhouse\.io|boards\.greenhouse\.io|jobs\.lever\.co)\//.test(url)) {
    return { ok: false, error: "unsupported_url" };
  }

  // Open the apply page in a new tab. The content script for that
  // host will read the per-tab payload below on boot.
  const tab = await chrome.tabs.create({ url, active: true });

  await chrome.storage.session.set({
    [`fill:${tab.id}`]: {
      profile: profile || {},
      answers: Array.isArray(answers) ? answers : [],
      applicationId: applicationId || null,
      // accessToken + apiBase let the content script call
      // POST /applications/{id}/extension-finish to auto-mark the row
      // submitted after the user finishes. Stored ONLY in
      // chrome.storage.session (cleared on browser restart) and
      // consumed once on first read.
      accessToken: accessToken || null,
      apiBase: apiBase || null,
      ts: Date.now(),
    },
  });

  return { ok: true, tabId: tab.id };
}

// Internal messages — from content scripts requesting their per-tab
// payload at boot.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "get_fill_payload" && sender.tab && typeof sender.tab.id === "number") {
    const key = `fill:${sender.tab.id}`;
    chrome.storage.session.get(key).then((d) => {
      sendResponse(d[key] || null);
      // One-shot consumption: clear after read so a refresh doesn't
      // accidentally re-fill (the user might have edited fields).
      if (d[key]) chrome.storage.session.remove(key);
    });
    return true;
  }
  return false;
});
