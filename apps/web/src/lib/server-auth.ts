import { cookies } from "next/headers";

const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:5000";

export type ServerAuthResult =
  | { state: "guest" }
  | { state: "unsubscribed"; userLabel: string }
  | { state: "ready"; userLabel: string; isAdmin: boolean };

export async function getServerAuth(): Promise<ServerAuthResult> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");

  try {
    const res = await fetch(`${backendUrl}/api/auth/me`, {
      headers: cookieHeader ? { Cookie: cookieHeader } : {},
      cache: "no-store",
    });
    const data = await res.json();
    if (!data.logged_in) return { state: "guest" };

    const userLabel = data.name || data.phone || "کاربر";

    return {
      state: "ready",
      userLabel,
      isAdmin: Boolean(data.is_admin),
    };
  } catch {
    return { state: "guest" };
  }
}
