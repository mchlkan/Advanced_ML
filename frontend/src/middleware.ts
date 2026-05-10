import { NextRequest, NextResponse } from "next/server";

export const config = {
  // Run on every route except Next internals, favicon, and the login page itself.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|login).*)"],
};

export function middleware(req: NextRequest) {
  if (req.cookies.get("resell-auth")?.value === "ok") {
    return NextResponse.next();
  }
  return NextResponse.redirect(new URL("/login", req.url));
}
