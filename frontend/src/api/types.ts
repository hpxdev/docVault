import type { components } from "./schema";

type S = components["schemas"];

export type DocumentOut = S["DocumentOut"];
export type DocumentList = S["DocumentList"];
export type UploadResult = S["UploadResult"];
export type UploadResponse = S["UploadResponse"];
export type InsightsOut = S["InsightsOut"];
export type SessionOut = S["SessionOut"];
export type SessionList = S["SessionList"];
export type SessionDocument = S["SessionDocument"];
export type MessageOut = S["MessageOut"];
export type MessageList = S["MessageList"];
export type CitationOut = S["CitationOut"];
export type AskResponse = S["AskResponse"];

/** Payload of `snapshot` / `status` events on GET /documents/events. */
export interface StatusPayload {
  id: string;
  filename: string;
  status: string;
  stages: { extract: string; index: string; insights: string };
  chat_ready: boolean;
  page_count: number | null;
  warnings: { code: string; pages?: number[] }[];
  error: { code: string; message: string | null } | null;
  updated_at: string | null;
  deleted?: boolean;
}

export interface Rate {
  value: number | null;
  numerator: number;
  denominator: number;
}

export interface Percentiles {
  p50: number | null;
  p95: number | null;
  count: number;
}

export interface DocumentMetrics {
  generated_at: string;
  cached: boolean;
  documents: {
    total: number;
    by_status: Record<string, number>;
    by_file_type: Record<string, number>;
    chat_ready: number;
  };
  content: { total_pages: number; total_chunks: number; total_bytes: number; average_pages: Rate };
  uploads_per_day: { date: string; count: number }[];
  top_categories: { category: string; count: number }[];
  top_tags: { tag: string; count: number }[];
}

export interface StageMetrics {
  started: number;
  succeeded: number;
  failed: number;
  retry_scheduled: number;
  running: number;
  success_rate: Rate;
  duration_ms: Percentiles;
  retries: number;
  failures_by_code: Record<string, number>;
}

export interface ProcessingMetrics {
  window: string;
  generated_at: string;
  cached: boolean;
  stages: Record<"extract" | "index" | "insights", StageMetrics>;
  upload_to_chat_ready_ms: Percentiles;
  queues: Record<string, number | null>;
  ai: {
    calls: number;
    errors: number;
    error_rate: Rate;
    input_tokens: number;
    output_tokens: number;
    estimated_cost_usd: number;
    by_purpose_and_model: {
      purpose: string;
      model: string;
      calls: number;
      errors: number;
      input_tokens: number;
      output_tokens: number;
      estimated_cost_usd: number;
    }[];
    spend_limit_usd: number;
    estimated_spend_all_time_usd: number;
  };
  chat: {
    questions: number;
    assistant_messages: number;
    answered: number;
    not_found_rate: Rate;
    unsupported_rate: Rate;
    error_rate: Rate;
    interrupted: number;
    first_token_ms: Percentiles;
    total_ms: Percentiles;
    avg_citations_per_answer: Rate;
  };
}

export interface Readiness {
  status: "ready" | "degraded" | "unavailable";
  checks: {
    database: { ok: boolean };
    redis: { ok: boolean };
    worker: { ok: boolean };
    ai: { ok: boolean; ai_mode: "fake" | "openai"; chat_model: string; error?: string };
  };
}
