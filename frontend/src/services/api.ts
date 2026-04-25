const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function api<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
