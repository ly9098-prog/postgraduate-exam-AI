export type ImportQuestionItem = {
  id: number;
  batch_id: string;
  source_type: string;
  source_file?: string | null;
  subject_id?: number | null;
  subject_code?: string | null;
  subject_name?: string | null;
  question_type?: string | null;
  raw_data?: Record<string, unknown> | null;
  parsed_content?: Record<string, unknown> | null;
  parsed_options?: Record<string, unknown> | null;
  parsed_answer?: string | null;
  parsed_analysis?: string | null;
  question_hash?: string | null;
  duplicate_status?: string | null;
  duplicate_of_question_id?: number | null;
  duplicate_of_import_id?: number | null;
  status: string;
  review_note?: string | null;
  question_id?: number | null;
  reject_reason?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  ai_generated: boolean;
  ai_source?: string | null;
  ai_confidence?: number | null;
  ai_metadata?: Record<string, unknown> | null;
  ai_reviewed_at?: string | null;
  ai_answer_flag: boolean;
  content_preview?: string;
  risk_flags: string[];
  risk_level: string;
  risk_reasons: string[];
  // ── 导入审核定位与答案状态增强 ──
  source_question_no?: string | null;
  source_question_label?: string | null;
  source_image_seq?: number | null;
  source_image_name?: string | null;
  source_page_start?: number | null;
  source_page_end?: number | null;
  source_order_index?: number | null;
  raw_text_preview?: string | null;
  source_locator?: string | null;
  answer_status?: string | null;
  answer_source?: string | null;
  answer_confidence?: number | null;
  review_priority?: number | null;
  created_at: string;
  updated_at: string;
};

export type ImportPipelineUploadResponse = {
  pipeline_id: string;
  status: string;
  source_type?: string | null;
};

export type ImportPipelineStatusResponse = {
  pipeline_id: string;
  status: string;
  stages: Record<string, unknown>;
  stats: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  quality_report?: {
    total_questions: number;
    low_risk?: number;
    medium_risk?: number;
    high_risk?: number;
    requires_manual_review?: number;
    ai_answer_count?: number;
    math_image_count?: number;
    table_markdown_count?: number;
    repair_skipped?: number;
    repair_called?: number;
    ocr_cache_hit?: number;
    ocr_cache_miss?: number;
    review_duplicates_skipped?: number;
    estimated_manual_check_rate?: number;
    performance_summary?: {
      total_duration_ms: number;
      total_ai_calls: number;
      total_tokens_used: number;
      cache_hit_rate: number;
      slowest_stage: string;
      slowest_duration_ms: number;
    };
  } | null;
  errors: string[];
  batch_id: string;
  raw_text_preview: string;
  question_count: number;
  started_at: string;
  finished_at: string;
  current_stage: string;
  ocr_progress: string;
  source_type: string;
  chunk_progress?: Record<string, unknown> | null;
  alerts?: AlertItem[] | null;
};

export type ImportActionResponse = {
  id?: number | null;
  batch_id?: string | null;
  status: string;
  affected_count: number;
};

export type AdminImportCompleteResponse = {
  missing: string[];
  from_fallback: boolean;
  ai_metadata: Record<string, unknown>;
  tokens_used: number;
  duration_ms: number;
  item: ImportQuestionItem;
};

export type BatchImageUploadResponse = {
  job_id: string;
  status: string;
  total: number;
  rejected: number;
  rejected_files: string[];
  concurrency: number;
  duplicate?: boolean;
};

export type BatchImageJobItem = {
  id: number;
  seq: number;
  source_file: string | null;
  status: string; // pending | processing | succeeded | failed
  review_batch_id: string | null;
  question_count: number;
  error_message: string | null;
  has_ocr_cache: boolean;
  batch_import_id?: string | null;
  image_import_id?: string | null;
  request_id?: string | null;
};

export type BatchImageJobStatusResponse = {
  job_id: string;
  status: string; // queued | running | completed | failed
  source_type: string;
  subject_id?: number | null;
  concurrency: number;
  total: number;
  completed: number;
  processing: number;
  pending: number;
  succeeded: number;
  failed: number;
  total_questions: number;
  current_seq: number;
  current_file: string;
  error_message: string | null;
  started_at: string;
  finished_at: string;
  items: BatchImageJobItem[];
  partial_failure?: boolean;
  trace_events?: TraceEvent[];
};

export type TraceEvent = {
  seq: number;
  item_seq: number;
  step: string;
  status: string;
  message: string;
  duration_ms: number | null;
  created_at: string;
  request_id?: string | null;
  image_import_id?: string | null;
  batch_import_id?: string | null;
};

export type BatchImageReparseResponse = {
  item_id: number;
  status: string;
  review_batch_id: string | null;
  question_count: number;
  error_message: string | null;
};

export type BatchCompleteResponseItem = {
  import_id: number;
  status: string; // "success" | "failed" | "skipped"
  error?: string | null;
  completed_fields: string[];
};

export type BatchCompleteResponse = {
  total: number;
  succeeded: number;
  failed: number;
  skipped: number;
  items: BatchCompleteResponseItem[];
};

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type Role = {
  id: number;
  name: string;
  display_name: string;
  description?: string | null;
  is_system: boolean;
  permission_ids?: number[];
};

export type AdminUserSummary = {
  id: number;
  username: string;
  display_name?: string | null;
  email?: string | null;
  is_active: boolean;
  role_id: number;
  last_login_at?: string | null;
  last_login_ip?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type AdminRoleSummary = {
  id: number;
  name: string;
  display_name: string;
  is_system: boolean;
};

export type AdminUserDetail = AdminUserSummary & {
  role: AdminRoleSummary;
};

export type AdminUserCreateRequest = {
  username: string;
  password: string;
  display_name?: string | null;
  email?: string | null;
  role_id: number;
  is_active?: boolean;
};

export type AdminUserPatchRequest = {
  display_name?: string | null;
  email?: string | null;
  is_active?: boolean | null;
  role_id?: number | null;
};

export type AuthUser = AdminUserSummary;

export type LoginResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
  role: Role;
  permissions: string[];
};

export type MeResponse = {
  user: AuthUser;
  role: Role;
  permissions: string[];
};

export type Permission = {
  id: number;
  name: string;
  resource: string;
  action: string;
  category: string;
  description?: string | null;
};

export type AppUser = {
  id: number;
  openid: string;
  nickname?: string | null;
  avatar_url?: string | null;
  is_banned: boolean;
  banned_reason?: string | null;
  banned_at?: string | null;
  banned_by?: number | null;
  created_at?: string;
  updated_at?: string;
};

export type AppUserDetail = AppUser & {
  practice_count: number;
  wrong_count: number;
  recent_active_at?: string | null;
};

export type QuestionEditRequest = {
  subject_id?: number | null;
  question_type?: string;
  content?: Record<string, unknown>;
  options?: Record<string, unknown>;
  answer?: string;
  analysis?: string;
  knowledge_points?: unknown[];
  difficulty?: number;
  source?: string;
  source_type?: string;
};

export type AdminQuestion = {
  id: number;
  subject_id?: number | null;
  subject_code?: string | null;
  subject_name?: string | null;
  subject_path?: string | null;
  question_type: string;
  content: Record<string, unknown>;
  options?: Record<string, unknown> | null;
  answer: string;
  analysis?: string | null;
  knowledge_points?: unknown[] | null;
  difficulty: number;
  source?: string | null;
  source_type?: string | null;
  source_file?: string | null;
  import_batch_id?: string | null;
  raw_content?: string | null;
  image_url?: unknown[] | null;
  year?: number | null;
  review_status: string;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
};

export type AdminQuestionImportSummary = {
  id: number;
  batch_id?: string | null;
  question_hash?: string | null;
  duplicate_status?: string | null;
  duplicate_of_question_id?: number | null;
  duplicate_of_import_id?: number | null;
};

export type AdminQuestionDetail = AdminQuestion & {
  import_record?: AdminQuestionImportSummary | null;
};

export type QuestionVersion = {
  id: number;
  question_id: number;
  version: number;
  edited_by: number;
  edit_reason?: string | null;
  created_at?: string;
};

export type QuestionVersionDetail = QuestionVersion & {
  content: Record<string, unknown>;
  options?: Record<string, unknown> | null;
  answer: string;
  analysis?: string | null;
  difficulty: number;
  knowledge_points?: unknown;
};

export type BatchFailure = {
  id: number;
  error: string;
};

export type BatchResult = {
  success_ids?: number[];
  successIds?: number[];
  failed_items?: BatchFailure[];
  failedItems?: BatchFailure[];
};

// P7-1: Pipeline summary for observability listing
export type ImportPipelineSummaryItem = {
  pipeline_id: string;
  source_type: string;
  source_file?: string | null;
  status: string;
  total_pages?: number | null;
  error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  quality_report?: ImportPipelineStatusResponse["quality_report"];
  alerts?: AlertItem[] | null;
};

export type PipelinesListResponse = {
  items: ImportPipelineSummaryItem[];
  total: number;
  page: number;
  page_size: number;
};

// P7-2: Alert item from alert rules evaluation
export type AlertItem = {
  level: "error" | "warning" | "info";
  code: string;
  message: string;
  value?: number | string | null;
  threshold?: number | string | null;
  suggested_action?: string | null;
};

// P7-3: Cleanup response
export type CleanupResponse = {
  dry_run: boolean;
  target: string;
  targets: Record<string, Record<string, unknown>>;
};

// P7-4: Failure case export
export type ExportCaseResponse = {
  case_id: string;
  source_file: string;
  source_page?: number | null;
  subject_id?: number | null;
  question_type?: string | null;
  import_id: number;
  raw_data: Record<string, unknown>;
  parsed_content: Record<string, unknown>;
  risk_flags: string[];
  failure_types: string[];
  expected_template: Record<string, unknown>;
  exported_at: string;
};

export type DashboardOverview = {
  users_total: number;
  users_new_today: number;
  questions_total: number;
  questions_pending_review: number;
  imports_total: number;
  imports_pending: number;
  audit_critical_today: number;
  cache: Record<string, unknown>;
};

export type DashboardDailyPoint = {
  date: string;
  users_new: number;
  questions_new: number;
  imports_new: number;
  audits_total: number;
};

export type DashboardQuestionStats = {
  by_subject: Array<{ name: string; count: number }>;
  by_review_status: Array<{ name: string; count: number }>;
  by_difficulty: Array<{ name: string; count: number }>;
};

export type AIUsageMonthly = {
  year_month: string;
  call_count: number;
  limit_snapshot?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AISettings = {
  id: number;
  ai_parse_enabled: boolean;
  monthly_call_limit: number;
  current_usage: AIUsageMonthly;
  remaining_calls?: number | null;
  updated_by?: number | null;
  updated_at?: string | null;
};

export type AISettingsPatchRequest = {
  ai_parse_enabled?: boolean;
  monthly_call_limit?: number;
};

export type DailyTrendPoint = {
  date: string;
  calls: number;
  tokens: number;
  success_rate: number;
  avg_latency_ms: number;
};

export type AIStatsResponse = {
  today_calls: number;
  monthly_calls: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens: number;
  estimated_cost: number;
  daily_trends: DailyTrendPoint[];
};

export type AuditSeverity = "critical" | "important" | "normal" | "low";
export type AuditStatus = "success" | "failed";

type DetailSummary = {
  id?: number;
  content_preview?: string | null;
  subject_name?: string | null;
  question_type?: string | null;
  resource_label?: string;
};

export type AuditLogListItem = {
  id: number;
  operator_id: number | null;
  operator_name: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  severity: AuditSeverity;
  status: AuditStatus;
  ip: string | null;
  created_at: string;       // ISO 8601 with Z suffix
  detail_summary: DetailSummary | null;
  error_message: string | null;
};

export type AuditLogDetail = AuditLogListItem & {
  detail: Record<string, unknown> | null;
  user_agent: string | null;
};

export type AdminAiModelConfig = {
  id: number;
  name: string;
  display_name: string;
  provider: string;
  api_base_url: string | null;
  api_configured: boolean;
  api_key_masked: string | null;
  is_enabled: boolean;
  is_default: boolean;
  sort_order: number;
  feature: string | null;
  features: string[] | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AdminAiModelConfigPatchRequest = {
  name?: string;
  is_enabled?: boolean;
  is_default?: boolean;
  api_key?: string;
  api_base_url?: string;
  feature?: string | null;
  features?: string[] | null;
};

export type AdminAiModelConfigCreateRequest = {
  name: string;
  display_name: string;
  provider: string;
  api_base_url?: string;
  api_key?: string;
  feature?: string | null;
  features?: string[] | null;
};

export type AdminAiConfigsResponse = {
  configs: Record<string, string | number | boolean>;
};

export type AdminAiConfigsPatchRequest = {
  configs: Record<string, string | number | boolean>;
};

export type ModelTestConnectionRequest = {
  api_base_url: string;
  api_key: string;
  model_name: string;
  model_id?: number;
  provider?: string;
  feature?: string;
  features?: string[];
};

export type ModelTestConnectionResponse = {
  success: boolean;
  status: string;
  message: string;
  latency_ms: number | null;
  model_returned?: string | null;
};

// ── System health types ─────────────────────────────────────

export type HealthCheckItem = {
  ok: boolean;
  severity: "ok" | "warning" | "error";
  code?: string;
  message: string;
  enabled_count?: number;
  default_count?: number;
  providers?: string[];
  features?: string[];
};

export type SystemHealthResponse = {
  ok: boolean;
  checks: Record<string, HealthCheckItem>;
};

// ── Vector / Embedding Config ──

export type VectorConfig = {
  vector_enabled: boolean;
  vector_mode: string;
  vector_allowlist: string;
  vector_cache_ttl_sec: number;
  vector_top_k: number;
  vector_similarity_threshold: number;
  embedding_provider: string;
  embedding_api_key_configured: boolean;
  embedding_api_key_masked: string;
  embedding_base_url: string;
  embedding_model: string;
  embedding_dim: number;
  embedding_timeout: number;
  embedding_batch_size: number;
  updated_at: string | null;
};

export type VectorConfigPatchRequest = {
  vector_enabled?: boolean;
  vector_mode?: string;
  vector_allowlist?: string;
  vector_cache_ttl_sec?: number;
  vector_top_k?: number;
  vector_similarity_threshold?: number;
  embedding_provider?: string;
  embedding_api_key?: string;
  embedding_base_url?: string;
  embedding_model?: string;
  embedding_dim?: number;
  embedding_timeout?: number;
  embedding_batch_size?: number;
};

export type EmbeddingTestRequest = {
  api_base_url: string;
  api_key: string;
  model: string;
  dim?: number;
  timeout?: number;
};

export type EmbeddingTestResponse = {
  success: boolean;
  status: string;
  message: string;
  latency_ms: number;
  returned_dim: number | null;
};

// ── Import History (batch management) ──

export type ImportBatchListItem = {
  batch_id: string;
  source_type: string;
  source_file: string | null;
  total_count: number;
  pending_count: number;
  approved_count: number;
  rejected_count: number;
  published_count: number;
  created_at: string;
  updated_at: string;
};

export type ImportBatchDetail = ImportBatchListItem & {
  items: ImportQuestionItem[];
};

export type ImportPublishResponse = {
  published: number;
};

export type ImportDeleteResponse = {
  deleted_count: number;
};
