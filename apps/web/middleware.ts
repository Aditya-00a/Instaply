import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * Routes that require an authenticated session. Any request under
 * these paths without a Supabase session gets bounced to /sign-in.
 *
 * If Supabase env vars are missing, the middleware is a no-op so local
 * dev and preview builds continue to render the demo shells.
 */
const PROTECTED_PREFIXES = [
  "/dashboard",
  "/applications",
  "/review",
  "/documents",
  "/onboarding",
  "/billing",
  "/settings",
  "/search",
];

function isProtected(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`)
  );
}

export async function middleware(request: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  // Demo mode — auth disabled, let everything through.
  if (!url || !anon) return NextResponse.next();

  const response = NextResponse.next({ request });

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

  // Refreshing the session on every request keeps tokens fresh.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const pathname = request.nextUrl.pathname;

  // Block protected pages when not signed in.
  if (!user && isProtected(pathname)) {
    const redirect = request.nextUrl.clone();
    redirect.pathname = "/sign-in";
    redirect.searchParams.set("next", pathname);
    return NextResponse.redirect(redirect);
  }

  // Already signed in? Bounce away from /sign-in to the dashboard.
  if (user && pathname === "/sign-in") {
    const redirect = request.nextUrl.clone();
    redirect.pathname = "/dashboard";
    return NextResponse.redirect(redirect);
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Run on every route except:
     * - _next static/image pipelines
     * - favicon, og/sitemap/robots
     * - any file with an extension (assets)
     */
    "/((?!_next/static|_next/image|favicon.ico|opengraph-image|sitemap.xml|robots.txt|.*\\..*).*)",
  ],
};
