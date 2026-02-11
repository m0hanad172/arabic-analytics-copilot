// frontend/src/services/transcribeApi.ts
function resolveApiBase(): string {
  const raw = (import.meta.env.VITE_API_BASE || "/api").trim();
  return raw.replace(/\/+$/, "");
}

function joinUrl(base: string, path: string): string {
  const b = base.replace(/\/+$/, "");
  const p = path.replace(/^\/+/, "");
  return `${b}/${p}`;
}

const API_BASE = resolveApiBase();

export type TranscribeResponse = {
  text: string;
  language?: string;
  timings?: { bytes?: number; write_ms?: number; transcribe_ms?: number };
};

export async function transcribeAudio(
  blob: Blob,
  lang = "ar",
  opts?: { debug?: boolean; signal?: AbortSignal }
): Promise<TranscribeResponse> {
  const fd = new FormData();
  fd.append("file", blob, "voice.webm");

  const qs = new URLSearchParams();
  if (lang) qs.set("lang", lang);
  if (opts?.debug) qs.set("debug", "1");

  const url = `${joinUrl(API_BASE, "transcribe")}?${qs.toString()}`;

  const res = await fetch(url, {
    method: "POST",
    body: fd,
    signal: opts?.signal,
  });

  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`Transcribe failed (${res.status}): ${t || res.statusText}`);
  }

  return (await res.json()) as TranscribeResponse;
}
