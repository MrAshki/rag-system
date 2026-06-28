export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const backendUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:5000";

export async function POST(request: Request) {
  const cookie = request.headers.get("cookie");
  const contentType = request.headers.get("content-type") ?? "application/json";
  const body = await request.text();

  const upstream = await fetch(`${backendUrl}/api/ask/stream`, {
    method: "POST",
    headers: {
      "Content-Type": contentType,
      ...(cookie ? { Cookie: cookie } : {}),
    },
    body,
    cache: "no-store",
  });

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
    },
  });
}
