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
  duration_ms: number;
  plan_corrections?: string[];
}

export interface AskResponse {
  question: string;
  plan: AskPlan;
  result: AskResult;
  explain?: any;
  warnings?: string[] | null;
  meta: AskMeta;
}
