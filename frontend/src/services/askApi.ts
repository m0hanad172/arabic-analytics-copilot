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

function envInt(name: string, fallback: number): number {
  const raw = (import.meta as any)?.env?.[name];
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

// default timeout (non-breaking): يمنع "pending" للأبد
// - العادي: 20s
// - مع LLM: 60s (لأن LLM ممكن يتأخر)
const DEFAULT_TIMEOUT_MS = envInt("VITE_API_TIMEOUT_MS", 20_000);
const DEFAULT_LLM_TIMEOUT_MS = envInt("VITE_API_LLM_TIMEOUT_MS", 60_000);

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

  // ✅ Timeout ذكي حسب use_llm
  const timeoutMs = opts.use_llm ? DEFAULT_LLM_TIMEOUT_MS : DEFAULT_TIMEOUT_MS;

  // نستخدم controller داخلي علشان نعمل timeout + نقدر ندمجه مع signal الخارجي
  const controller = new AbortController();

  let externalAbortHandler: (() => void) | null = null;
  if (signal) {
    if (signal.aborted) controller.abort();
    externalAbortHandler = () => controller.abort();
    signal.addEventListener("abort", externalAbortHandler, { once: true });
  }

  const t = window.setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`);
    }

    return (await res.json()) as AskResponse;
  } catch (err: any) {
    // ✅ رسالة واضحة للـ timeout بدل “AbortError” الغامضة
    if (err?.name === "AbortError") {
      const sec = Math.round(timeoutMs / 1000);
      throw new Error(`Request timed out after ${sec}s`);
    }
    throw err;
  } finally {
    window.clearTimeout(t);
    if (signal && externalAbortHandler) {
      signal.removeEventListener("abort", externalAbortHandler);
    }
  }
}
