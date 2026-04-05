const KI_API_URL = process.env.KI_API_URL ?? "http://localhost:8080";
const KI_API_TOKEN = process.env.KI_API_TOKEN;
const TIMEOUT_MS = 10_000;

export async function kiRequest<T>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: unknown
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (KI_API_TOKEN) {
    headers["Authorization"] = `Bearer ${KI_API_TOKEN}`;
  }

  let response: Response;
  try {
    response = await fetch(`${KI_API_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    throw new Error(
      `KI API unreachable at ${KI_API_URL}${path}: ${(err as Error).message}`
    );
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`KI API error: ${response.status} ${response.statusText} — ${text}`);
  }

  return response.json() as Promise<T>;
}
