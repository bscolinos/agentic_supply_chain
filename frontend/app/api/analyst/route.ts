import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.API_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.json();

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND_URL}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      // Next.js server-side fetch has no browser connection limit issues
      signal: AbortSignal.timeout(130_000),
    });
  } catch (err) {
    const isTimeout = err instanceof Error && err.name === "TimeoutError";
    return NextResponse.json(
      { detail: isTimeout ? "Request timed out" : "Failed to reach backend" },
      { status: isTimeout ? 504 : 502 }
    );
  }

  let data: unknown;
  try {
    data = await backendRes.json();
  } catch {
    return NextResponse.json(
      { detail: "Backend returned an unexpected response" },
      { status: 502 }
    );
  }
  const response = NextResponse.json(data, { status: backendRes.status });
  // Prevent browsers from reusing this connection via keep-alive.
  // Queries take 45-90s; without this, the browser reuses a connection
  // that Node.js already closed, causing "Failed to fetch" on POST retries.
  response.headers.set("Connection", "close");
  return response;
}
