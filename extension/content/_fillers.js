// Field-matching + filling + UX helpers shared by the Greenhouse and
// Lever content scripts.
//
// Exposes `window.__instaply` with:
//   fillForm(payload)              → fills inputs, returns count
//   detectCaptcha()                → bool, true if hCaptcha/reCAPTCHA widget present
//   detectCaptchaSolved()          → bool, true if widget present AND token field populated
//   showStatus(state, opts)        → renders/updates the status box
//   reportFinish({applicationId, accessToken, apiBase})
//                                  → POST /applications/{id}/extension-finish
//   waitFor(check, timeoutMs)      → MutationObserver-based waiter
//
// Status box has six states, mirroring what the user actually sees:
//   filling | filled | verification | ready | submitting | done | error

(function () {
  if (window.__instaply) return; // guard against double-injection
  const ns = (window.__instaply = {});

  // ─── Field rules ────────────────────────────────────────────────
  // Thin port of the worker's deterministic rules. The worker remains
  // the source of truth for complex matches; the extension covers the
  // high-frequency identity fields plus saved-answer reuse.
  const _RULES = [
    { keys: ["first_name", "fname", "given_name", "givenname"], get: (p) => p.first_name || (p.full_name || "").split(" ")[0] },
    { keys: ["last_name", "lname", "surname", "family_name", "familyname"], get: (p) => p.last_name || (p.full_name || "").split(" ").slice(1).join(" ") },
    { keys: ["full_name", "fullname"], get: (p) => p.full_name },
    { keys: ["email"], get: (p) => p.email },
    { keys: ["phone", "mobile", "telephone"], get: (p) => p.phone_e164 || p.phone_national || p.phone },
    { keys: ["linkedin"], get: (p) => p.linkedin_url },
    { keys: ["github"], get: (p) => p.github_url },
    { keys: ["website", "portfolio", "personal_site"], get: (p) => p.portfolio_url || p.website_url },
    { keys: ["city"], get: (p) => p.city || p.current_city },
    { keys: ["state", "province", "region"], get: (p) => p.state || p.current_state },
    { keys: ["country"], get: (p) => p.country || p.current_country },
    { keys: ["zip", "postal", "postcode"], get: (p) => p.postal_code || p.zip_code },
    { keys: ["company", "employer"], get: (p) => p.current_company },
    { keys: ["title", "role", "position"], get: (p) => p.current_title },
    { keys: ["school", "university", "college"], get: (p) => p.school },
    { keys: ["major", "field_of_study"], get: (p) => p.major },
    { keys: ["degree"], get: (p) => p.degree },
  ];

  function _norm(s) {
    return (s || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  }

  function _matchRule(name, label) {
    const n = _norm(name);
    const l = _norm(label);
    for (const r of _RULES) {
      for (const k of r.keys) {
        if (n.includes(k) || l.includes(k)) return r;
      }
    }
    return null;
  }

  function _findLabel(el) {
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl && lbl.textContent) return lbl.textContent;
    }
    const parentLbl = el.closest("label");
    if (parentLbl && parentLbl.textContent) return parentLbl.textContent;
    let cur = el.parentElement;
    for (let i = 0; i < 6 && cur; i++) {
      const sib = cur.querySelector(".application-label, .application-question label, label");
      if (sib && sib !== el && sib.textContent) return sib.textContent;
      cur = cur.parentElement;
    }
    return el.placeholder || el.getAttribute("aria-label") || "";
  }

  // React-friendly setter (frameworks overwrite plain assignment on next render).
  function _setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value");
    if (setter && setter.set) setter.set.call(el, value);
    else el.value = value;
  }

  function _setValue(el, value) {
    if (value == null || value === "") return false;
    const tag = el.tagName.toLowerCase();
    if (tag === "select") {
      const v = String(value).toLowerCase().trim();
      for (const opt of el.options) {
        if (opt.value === String(value) || (opt.text || "").toLowerCase().trim() === v) {
          el.value = opt.value;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return true;
        }
      }
      return false;
    }
    if (el.type === "checkbox" || el.type === "radio") {
      const truthy = ["yes", "true", "on", "1"].includes(String(value).toLowerCase());
      if (truthy && !el.checked) {
        el.checked = true;
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }
      return false;
    }
    _setNativeValue(el, String(value));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  ns.fillForm = function fillForm({ profile, answers }) {
    let filled = 0;
    const inputs = document.querySelectorAll("input, textarea, select");
    for (const el of inputs) {
      if (el.type === "hidden" || el.disabled || el.readOnly) continue;
      if (el.value && el.value.trim()) continue;
      const label = _findLabel(el);
      const rule = _matchRule(el.name, label);
      if (!rule) continue;
      const value = rule.get(profile || {});
      if (_setValue(el, value)) filled++;
    }
    if (Array.isArray(answers) && answers.length) {
      const answerByQ = new Map();
      for (const a of answers) {
        const q = (a.question_text || "").toLowerCase().trim();
        if (q && a.answer_text) answerByQ.set(q, a.answer_text);
      }
      for (const el of inputs) {
        if (el.type === "hidden" || el.disabled || el.readOnly) continue;
        if (el.value && el.value.trim()) continue;
        const label = (_findLabel(el) || "").toLowerCase().trim();
        if (!label) continue;
        const ans = answerByQ.get(label);
        if (ans && _setValue(el, ans)) filled++;
      }
    }
    return filled;
  };

  // ─── Captcha detection ──────────────────────────────────────────
  ns.detectCaptcha = function detectCaptcha() {
    return !!document.querySelector(
      '.h-captcha, .g-recaptcha, iframe[src*="hcaptcha"], iframe[src*="recaptcha"]'
    );
  };

  // True when a captcha widget exists AND its hidden response token
  // field has a value. Both hCaptcha and reCAPTCHA write the user's
  // solve token into a textarea named `h-captcha-response` /
  // `g-recaptcha-response` — non-empty value = solved.
  ns.detectCaptchaSolved = function detectCaptchaSolved() {
    if (!ns.detectCaptcha()) return false;
    const tokenInputs = document.querySelectorAll(
      'textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"], input[name="h-captcha-response"], input[name="g-recaptcha-response"]'
    );
    for (const t of tokenInputs) {
      if ((t.value || "").trim().length > 0) return true;
    }
    return false;
  };

  // ─── Confirmation detection (mirror of worker/actions.py) ───────
  const _CONFIRMATION_TEXT_SIGNALS = [
    "thank you for applying",
    "thanks for applying",
    "application received",
    "application submitted",
    "successfully submitted",
    "your application has been received",
    "your application was submitted",
    "we have received your application",
    "we'll be in touch",
    "we will be in touch",
    "submission successful",
    "thanks for your interest",
  ];
  const _CONFIRMATION_URL_TOKENS = [
    "thanks", "thank-you", "thank_you", "thankyou",
    "confirmation", "confirmed", "success",
    "submitted", "submission", "applied",
    "application-complete", "complete", "received",
  ];

  ns.detectConfirmation = function detectConfirmation() {
    // URL tokens
    try {
      const path = (location.pathname + location.search).toLowerCase();
      const segments = path.replace(/[?]/g, "/").split("/").filter(Boolean);
      for (const seg of segments) {
        const tokens = new Set([seg, ...seg.replace(/[-_]/g, " ").split(" ")]);
        for (const sig of _CONFIRMATION_URL_TOKENS) {
          if (tokens.has(sig)) return { ok: true, via: `url:${sig}` };
        }
      }
    } catch (_) {}
    // Body text
    try {
      const body = (document.body.innerText || "").toLowerCase();
      for (const phrase of _CONFIRMATION_TEXT_SIGNALS) {
        if (body.includes(phrase)) return { ok: true, via: `text:${phrase}` };
      }
    } catch (_) {}
    return { ok: false };
  };

  // ─── Post-submit reporting ──────────────────────────────────────
  ns.reportFinish = async function reportFinish({ applicationId, accessToken, apiBase }) {
    if (!applicationId || !accessToken) {
      return { ok: false, error: "missing_id_or_token" };
    }
    const base = apiBase || "https://api.asion.ai";
    try {
      const resp = await fetch(`${base}/applications/${encodeURIComponent(applicationId)}/extension-finish`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) return { ok: false, status: resp.status, error: body.detail || body.error || resp.statusText };
      return { ok: true, body };
    } catch (e) {
      return { ok: false, error: String(e && e.message || e) };
    }
  };

  // ─── Status box (replaces the simple banner) ────────────────────
  // States with copy + color + optional action button:
  //   filling      — neutral, "Instaply is filling this application…"
  //   filled       — neutral, "Filled N fields. Review what's on screen."
  //   verification — yellow, "Verification required — solve the captcha. Resume below when done."
  //   ready        — green,  "Verification done. Click Submit Application on the page."
  //   submitting   — blue,   "Submitting…"
  //   done         — green,  "Submitted. Marked complete in Instaply."
  //   error        — red,    optional message
  const STATE_STYLES = {
    filling:       { bg: "rgba(15,17,21,0.96)", border: "rgba(255,255,255,0.18)",  accent: "#9aa3b3" },
    filled:        { bg: "rgba(15,17,21,0.96)", border: "rgba(255,214,90,0.30)",   accent: "#ffd65a" },
    verification:  { bg: "rgba(48,30,5,0.96)",  border: "rgba(255,153,51,0.45)",   accent: "#ffb766" },
    ready:         { bg: "rgba(16,40,24,0.96)", border: "rgba(122,223,163,0.35)",  accent: "#7adfa3" },
    submitting:    { bg: "rgba(15,30,50,0.96)", border: "rgba(120,170,235,0.35)",  accent: "#7caee5" },
    done:          { bg: "rgba(16,40,24,0.96)", border: "rgba(122,223,163,0.45)",  accent: "#7adfa3" },
    error:         { bg: "rgba(48,16,16,0.96)", border: "rgba(255,120,120,0.35)",  accent: "#ff8080" },
  };

  ns.showStatus = function showStatus(state, opts) {
    opts = opts || {};
    const id = "instaply-status";
    let box = document.getElementById(id);
    if (!box) {
      box = document.createElement("div");
      box.id = id;
      box.style.cssText = [
        "position:fixed", "top:14px", "right:14px",
        "z-index:2147483647",
        "color:#e9eaee",
        "border-radius:12px",
        "padding:14px 16px",
        "max-width:360px",
        "min-width:260px",
        "font:13px/-apple-system,BlinkMacSystemFont,system-ui,sans-serif",
        "line-height:1.45",
        "box-shadow:0 14px 44px rgba(0,0,0,0.45)",
        "transition:background 200ms ease, border-color 200ms ease",
      ].join(";");
      document.body.appendChild(box);
    }
    const style = STATE_STYLES[state] || STATE_STYLES.filling;
    box.style.background = style.bg;
    box.style.border = `1px solid ${style.border}`;
    const accent = style.accent;
    const message = String(opts.message || "").replace(/</g, "&lt;");
    const actionLabel = opts.action && opts.action.label ? String(opts.action.label).replace(/</g, "&lt;") : "";
    box.innerHTML =
      `<div style="display:flex;align-items:center;gap:8px;font-weight:600;color:${accent};font-size:12px;letter-spacing:0.4px;text-transform:uppercase;margin-bottom:6px">` +
        `<span style="display:inline-block;width:8px;height:8px;border-radius:99px;background:${accent}"></span>` +
        `Instaply` +
      `</div>` +
      `<div style="color:#e9eaee">${message}</div>` +
      (actionLabel
        ? `<div style="margin-top:10px"><button id="instaply-action" style="background:${accent};color:#0f1115;border:none;border-radius:8px;padding:7px 12px;font-weight:600;font-size:12.5px;cursor:pointer">${actionLabel}</button></div>`
        : "");
    if (opts.action && opts.action.onClick) {
      const btn = box.querySelector("#instaply-action");
      if (btn) btn.addEventListener("click", opts.action.onClick);
    }
    return box;
  };

  ns.hideStatus = function hideStatus() {
    const box = document.getElementById("instaply-status");
    if (box) box.remove();
  };

  // ─── Generic waiter ─────────────────────────────────────────────
  ns.waitFor = function waitFor(check, timeoutMs) {
    return new Promise((resolve) => {
      const found = check();
      if (found) return resolve(found);
      const obs = new MutationObserver(() => {
        const f = check();
        if (f) { obs.disconnect(); resolve(f); }
      });
      obs.observe(document.body || document.documentElement, { childList: true, subtree: true });
      setTimeout(() => { try { obs.disconnect(); } catch (_) {} resolve(null); }, timeoutMs || 8000);
    });
  };
})();
