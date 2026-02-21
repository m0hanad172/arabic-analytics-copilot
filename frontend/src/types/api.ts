export type SortDir = "asc" | "desc";

export interface AskPlan {
  metrics: string[];
  dimensions: string[];
  filters: Array<{ field: string; op: string; value: any }>;
  sort: Array<{ field: string; dir: SortDir }>;
  limit: number;
  notes?: string;
}

export interface AskResult {
  sql: string;
  rows: Array<Record<string, any>>;
  warnings?: any;
  suggestions?: any;
}

export interface AskMeta {
  ask_version: string;
  log_id: number;

  used_cache: boolean;
  used_llm: boolean;

  llm_enabled: boolean;
  llm_attempted?: boolean;
  llm_error?: string | null;

  // legacy: DB/compile/exec time (does NOT include LLM)
  duration_ms: number;

  // ✅ new: total wall time (includes LLM + everything)
  total_ms?: number;

  // ✅ LLM details (optional, safe)
  llm_model?: string;
  llm_ms?: number;
  llm_status?: string;
  llm_attempts?: number;

  plan_corrections?: string[];
  catalog_source?: string;
  catalog_hash?: string;
  explain_used?: boolean;
  explain_mode?: string | null;
}


export interface AskResponse {
  question: string;
  plan: AskPlan;
  result: AskResult;
  explain?: any;
  warnings?: string[] | null;
  meta: AskMeta;
}
