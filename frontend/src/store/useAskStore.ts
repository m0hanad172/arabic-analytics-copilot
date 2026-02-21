// frontend/src/store/useAskStore.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AskResponse } from "../types/api";
import { ask as askApi } from "../services/askApi";

export type RunOpts = { use_llm: boolean; use_cache: boolean; explain: boolean };
type Settings = RunOpts & { theme: "dark" };

export type HistoryItem = {
  q: string;
  ts: number;
  req: RunOpts;
  meta?: {
    used_llm?: boolean;
    used_cache?: boolean;

    // legacy: DB/compile/exec time (does NOT include LLM)
    duration_ms?: number;

    // ✅ new: total wall time (includes LLM + network)
    total_ms?: number;

    // ✅ LLM timing + status
    llm_ms?: number;
    llm_status?: string;
    llm_error?: string;
    llm_attempts?: number;
    llm_model?: string;

    log_id?: number;
    ask_version?: string;
    plan_corrections?: string[];
  };
};

type AskState = {
  settings: Settings;
  history: HistoryItem[];
  draftQuestion: string;
  focusTick: number;

  last?: AskResponse;
  busy: boolean;
  error?: string;

  setSetting: <K extends keyof Settings>(k: K, v: Settings[K]) => void;
  setDraftQuestion: (q: string) => void;
  requestFocus: () => void;

  pushHistory: (item: HistoryItem) => void;
  clearHistory: () => void;

  setLast: (r?: AskResponse) => void;
  setBusy: (v: boolean) => void;
  setError: (e?: string) => void;

  runAsk: (question?: string, opts?: Partial<RunOpts>) => Promise<void>;
};

function asNum(v: any): number | undefined {
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export const useAskStore = create<AskState>()(
  persist(
    (set, get) => ({
      // ✅ force dark
      settings: { use_llm: true, use_cache: true, explain: false, theme: "dark" },

      history: [],
      draftQuestion: "قارن صافي المبيعات والخصومات حسب المدينة والربع واعرض أعلى 5",
      focusTick: 0,

      last: undefined,
      busy: false,
      error: undefined,

      // ✅ block theme changes completely
      setSetting: (k, v) => {
        if (k === "theme") return;
        set({ settings: { ...get().settings, [k]: v } });
      },

      setDraftQuestion: (q) => set({ draftQuestion: q }),
      requestFocus: () => set({ focusTick: get().focusTick + 1 }),

      pushHistory: (item) => set({ history: [item, ...get().history].slice(0, 50) }),
      clearHistory: () => set({ history: [] }),

      setLast: (r) => set({ last: r }),
      setBusy: (v) => set({ busy: v }),
      setError: (e) => set({ error: e }),

      runAsk: async (question, opts) => {
        const q = (question ?? get().draftQuestion ?? "").trim();
        if (!q) return;

        const s = get().settings;
        const req: RunOpts = {
          use_llm: opts?.use_llm ?? s.use_llm,
          use_cache: opts?.use_cache ?? s.use_cache,
          explain: opts?.explain ?? s.explain,
        };

        set({ busy: true, error: undefined });

        try {
          const data = await askApi(q, req);
          set({ last: data, busy: false, error: undefined });

          const m: any = data?.meta ?? {};

          const dbMs = asNum(m.duration_ms);
          const llmMs = asNum(m.llm_ms);
          // ✅ prefer backend total_ms; otherwise best-effort fallback
          const totalMs =
            asNum(m.total_ms) ??
            (dbMs != null && llmMs != null ? dbMs + llmMs : dbMs);

          get().pushHistory({
            q,
            ts: Date.now(),
            req,
            meta: {
              used_llm: !!m.used_llm,
              used_cache: !!m.used_cache,

              duration_ms: dbMs,
              total_ms: totalMs,

              llm_ms: llmMs,
              llm_status: typeof m.llm_status === "string" ? m.llm_status : undefined,
              llm_error: typeof m.llm_error === "string" ? m.llm_error : undefined,
              llm_attempts: asNum(m.llm_attempts),
              llm_model: typeof m.llm_model === "string" ? m.llm_model : undefined,

              log_id: asNum(m.log_id),
              ask_version: typeof m.ask_version === "string" ? m.ask_version : undefined,
              plan_corrections: Array.isArray(m.plan_corrections) ? m.plan_corrections : undefined,
            },
          });
        } catch (e: any) {
          set({ busy: false, error: e?.message || String(e) });
        }
      },
    }),
    {
      name: "aac.ui.v1",
      version: 3,
      // ✅ لا نخزن last/busy/error في localStorage
      partialize: (s) => ({
        settings: { ...s.settings, theme: "dark" },
        history: s.history,
        draftQuestion: s.draftQuestion,
      }),
      migrate: (state: any) => {
        if (!state?.settings) return state;
        return { ...state, settings: { ...state.settings, theme: "dark" } };
      },
    }
  )
);
