import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "bhv_session"; // sama dengan settings.cookie_name di API

/**
 * Penjaga cepat: tanpa cookie sesi -> langsung ke /login. Validitas sesi (kedaluwarsa, akun
 * nonaktif, peran) tetap diperiksa API di setiap request; halaman /login sendiri tidak pernah
 * di-redirect di sini agar cookie basi tidak menimbulkan loop.
 */
export function proxy(request: NextRequest) {
  if (request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  const url = request.nextUrl.clone();
  const next = request.nextUrl.pathname + request.nextUrl.search;
  url.pathname = "/login";
  url.search = next && next !== "/" ? `?next=${encodeURIComponent(next)}` : "";
  return NextResponse.redirect(url);
}

export const config = {
  matcher: [
    // Semua halaman kecuali login, API (diteruskan ke FastAPI), aset Next & file statis.
    "/((?!login|api|_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|svg|ico|webmanifest)$).*)",
  ],
};
