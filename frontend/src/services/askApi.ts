// frontend/src/services/askApi.ts
import type { AskResponse } from "../types/api";

function resolveApiBase(): string {
  // الأفضل احترافيًا: في dev نخليها "/api" + Vite proxy
  const raw = (import.meta.env.VITE_API_BASE || "/api").trim();
  return raw.replace(/\/+$/, "");
}

function joinUrl(base: string, path: string): string {
  const b = base.replace(/\/+$/, "");
  const p = path.replace(/^\/+/, "");
  return `${b}/${p}`;
}

const API_BASE = resolveApiBase();

export async function ask(
  question: string,
  opts: { use_llm: boolean; use_cache: boolean; explain: boolean },
  signal?: AbortSignal
): Promise<AskResponse> {
  const qs = new URLSearchParams();
  qs.set("use_llm", opts.use_llm ? "1" : "0");
  qs.set("use_cache", opts.use_cache ? "1" : "0");
  if (opts.explain) qs.set("explain", "1");

  const url = `${joinUrl(API_BASE, "ask")}?${qs.toString()}`;

  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ question }),
    signal,
  });

  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
  }

  return (await res.json()) as AskResponse;
}
