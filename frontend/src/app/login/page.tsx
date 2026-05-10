import { redirect } from "next/navigation";
import { cookies } from "next/headers";

async function login(formData: FormData) {
  "use server";
  const password = formData.get("password");
  if (
    typeof password === "string" &&
    password === process.env.RESELL_ACCESS_PASSWORD
  ) {
    cookies().set("resell-auth", "ok", {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      maxAge: 60 * 60 * 24 * 30,
      path: "/",
    });
    redirect("/");
  }
  redirect("/login?error=1");
}

export default function LoginPage({
  searchParams,
}: {
  searchParams: { error?: string };
}) {
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#fafaf8",
        color: "#0e0f0e",
        fontFamily: '"Inter", -apple-system, system-ui, sans-serif',
        padding: 24,
      }}
    >
      <form
        action={login}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          padding: 32,
          width: "min(360px, 100%)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 22,
              height: 22,
              borderRadius: 6,
              backgroundColor: "oklch(0.62 0.15 145)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                backgroundColor: "#fff",
              }}
            />
          </div>
          <span style={{ fontSize: 15, fontWeight: 600, letterSpacing: "-0.2px" }}>
            Resell Copilot
          </span>
        </div>
        <p style={{ fontSize: 13, color: "#6b6c69", lineHeight: 1.5, margin: 0 }}>
          This demo is gated. Enter the shared password to continue.
        </p>
        <input
          name="password"
          type="password"
          placeholder="Password"
          autoComplete="current-password"
          autoFocus
          required
          style={{
            padding: "12px 14px",
            border: `1px solid ${searchParams.error ? "oklch(0.55 0.20 25)" : "#d6d3cc"}`,
            borderRadius: 10,
            fontSize: 14,
            backgroundColor: "#fff",
            outline: "none",
          }}
        />
        {searchParams.error && (
          <p
            style={{
              fontSize: 12,
              color: "oklch(0.55 0.20 25)",
              margin: 0,
            }}
          >
            Wrong password. Try again.
          </p>
        )}
        <button
          type="submit"
          style={{
            padding: "12px 14px",
            border: "none",
            borderRadius: 10,
            backgroundColor: "oklch(0.62 0.15 145)",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Enter
        </button>
      </form>
    </main>
  );
}
