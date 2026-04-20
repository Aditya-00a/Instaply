import { NextResponse, type NextRequest } from "next/server";
import { Resend } from "resend";
import { createServerClient } from "@supabase/ssr";

/**
 * POST /api/email/welcome
 *
 * Sends a welcome email to a new user. Called from the sign-up flow
 * after Supabase auth.signUp succeeds. If RESEND_API_KEY is not set,
 * silently skips (so local dev never fails).
 *
 * Auth: caller must be the signed-in user the email is being sent to
 * (verified via Supabase session cookie). Prevents abuse where any actor
 * could spam our domain with arbitrary "welcome" emails to victims.
 *
 * Body: { name?: string } — email comes from the verified session.
 */

// In-process rate limiter: max 3 welcome emails per user per hour.
const _windows: Map<string, { count: number; resetAt: number }> = new Map();
function rateLimitOk(key: string, max = 3, windowMs = 3600_000): boolean {
  const now = Date.now();
  const w = _windows.get(key);
  if (!w || now > w.resetAt) {
    _windows.set(key, { count: 1, resetAt: now + windowMs });
    return true;
  }
  if (w.count >= max) return false;
  w.count += 1;
  return true;
}

// HTML escape for any user-controlled content interpolated into the email body
function htmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export async function POST(request: NextRequest) {
  const key = process.env.RESEND_API_KEY;
  if (!key) {
    return NextResponse.json({ sent: false, reason: "RESEND_API_KEY not set" });
  }

  // 1. Require a valid Supabase session — auth-side identifies the user
  const supaUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supaKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!supaUrl || !supaKey) {
    return NextResponse.json({ error: "Auth not configured" }, { status: 500 });
  }
  const supabase = createServerClient(supaUrl, supaKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: () => { /* read-only here */ },
    },
  });
  const { data: { user } } = await supabase.auth.getUser();
  if (!user || !user.email) {
    return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
  }

  // 2. Rate limit per user
  if (!rateLimitOk(user.id)) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }

  // 3. Parse + sanitize body. Email comes from the session, NOT the body.
  let body: { name?: string };
  try {
    body = await request.json();
  } catch {
    body = {};
  }

  const resend = new Resend(key);
  const rawName = (body.name || user.user_metadata?.full_name || "").toString();
  // Truncate, then escape for HTML interpolation. This neuters any
  // injection attempts via display_name (e.g. <img onerror>).
  const firstName = htmlEscape(rawName.split(/\s+/)[0]?.slice(0, 60) || "there");
  const recipient = user.email;

  try {
    await resend.emails.send({
      from: "Instaply <hello@asion.ai>",
      to: recipient,
      subject: "Welcome to Instaply — 3 free applications are ready",
      html: `
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 560px; margin: 0 auto; padding: 32px 0;">
          <h1 style="font-size: 24px; font-weight: 700; color: #0a0b0d; margin: 0 0 16px;">
            Hey ${firstName} — welcome to Instaply
          </h1>
          <p style="font-size: 16px; line-height: 1.6; color: #5b616e; margin: 0 0 20px;">
            Your account is live. You have <strong>3 free application credits</strong>
            ready to use — no card required.
          </p>
          <p style="font-size: 16px; line-height: 1.6; color: #5b616e; margin: 0 0 20px;">
            Here's how to get your first confirmed application in under 10 minutes:
          </p>
          <ol style="font-size: 15px; line-height: 1.7; color: #0a0b0d; padding-left: 20px; margin: 0 0 24px;">
            <li>Upload your resume in the onboarding wizard</li>
            <li>Set your target roles and locations</li>
            <li>Watch matched roles populate your dashboard</li>
          </ol>
          <a href="https://instaply.asion.ai/onboarding"
             style="display: inline-block; padding: 14px 28px; background: #0052ff; color: #fff; font-size: 15px; font-weight: 600; text-decoration: none; border-radius: 10px;">
            Complete your profile
          </a>
          <p style="font-size: 13px; color: #5b616e; margin: 24px 0 0;">
            Questions? Reply to this email or visit
            <a href="https://instaply.asion.ai/contact" style="color: #0052ff; text-decoration: none;">instaply.asion.ai/contact</a>.
          </p>
          <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0 16px;" />
          <p style="font-size: 11px; color: #9ca3af; margin: 0;">
            Instaply by Ravendise · hello@asion.ai ·
            <a href="https://instaply.asion.ai/privacy" style="color: #9ca3af;">Privacy</a> ·
            <a href="https://instaply.asion.ai/terms" style="color: #9ca3af;">Terms</a>
          </p>
        </div>
      `,
    });
    return NextResponse.json({ sent: true });
  } catch (e) {
    console.error("Welcome email failed:", e);
    return NextResponse.json({ sent: false, error: String(e) }, { status: 500 });
  }
}
