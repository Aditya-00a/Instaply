import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";

/**
 * OAuth + email-confirmation callback.
 *
 * Supabase sends the user here after they click a magic link or finish
 * an OAuth handshake. We exchange the ?code for a session, set cookies
 * via the response, and then redirect to ?next= (falling back to
 * /dashboard).
 *
 * In demo mode (no env vars), we just bounce to /dashboard.
 */
export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const next = searchParams.get("next") || "/dashboard";

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  const redirect = new URL(next, origin);
  const response = NextResponse.redirect(redirect);

  // Demo mode — just redirect.
  if (!url || !anon) return response;

  if (!code) {
    // Missing code param: send them back to sign-in with a hint.
    const signIn = new URL("/sign-in", origin);
    signIn.searchParams.set("error", "missing_code");
    return NextResponse.redirect(signIn);
  }

  const supabase = createServerClient(url, anon, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (cookiesToSet) => {
        cookiesToSet.forEach(({ name, value, options }) => {
          response.cookies.set(name, value, options);
        });
      },
    },
  });

  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    const signIn = new URL("/sign-in", origin);
    signIn.searchParams.set("error", error.message);
    return NextResponse.redirect(signIn);
  }

  return response;
}
