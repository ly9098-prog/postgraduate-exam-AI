export type QuestionOptionsValue =
  | string
  | unknown[]
  | Record<string, unknown>
  | null;

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

export type PdfPageRangeInfo = {
  requested_start?: number | null;
  requested_end?: number | null;
  effective_start: number;
  effective_end: number;
  selected_page_count: number;
  total_pages: number;
};

export type ImportPipelineUploadResponse = {
  pipeline_id: string;
  status: string;
  source_type?: string | null;
  page_range?: PdfPageRangeInfo | null;
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
    table_structured_count?: number;
    table_review_count?: number;
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
  page_range?: PdfPageRangeInfo | null;
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
  options?: QuestionOptionsValue;
  answer?: string;
  analysis?: string;
  knowledge_points?: unknown[];
  difficulty?: number;
  source?: string;
  source_type?: string;
};

export type QuestionAddOptionItem = {
  text: string;
  key?: string | null;
};

export type QuestionAddOptionsRequest = {
  options: QuestionAddOptionItem[];
  edit_reason?: string | null;
};

export type QuestionDeleteImageRequest = {
  target: string; // "stem" | "option:A"
  url: string;
  edit_reason?: string | null;
};

export type AdminQuestion = {
  id: number;
  subject_id?: number | null;
  subject_code?: string | null;
  subject_name?: string | null;
  subject_path?: string | null;
  question_type: string;
  content: Record<string, unknown>;
  options?: QuestionOptionsValue;
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
  edited_by_name?: string | null;
  edit_reason?: string | null;
  created_at?: string;
};

export type QuestionVersionDetail = QuestionVersion & {
  content: Record<string, unknown>;
  options?: QuestionOptionsValue;
  answer: string;
  analysis?: string | null;
  difficulty: number;
  knowledge_points: string[];
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

export type QuestionAuditDetail = {
  id: number | null;
  subject_id: number | null;
  subject_code: string | null;
  subject_name: string | null;
  question_type: string | null;
  content: unknown;
  content_text: string | null;
  content_preview: string | null;
  options: unknown;
  answer: unknown;
  analysis: unknown;
  knowledge_points: unknown;
  difficulty: number | null;
  source: string | null;
  source_type: string | null;
  source_file: string | null;
  year: number | null;
  review_status: string | null;
  is_active: boolean | null;
  data_source: "audit_snapshot" | "audit_before" | "audit_after" | "audit_summary" | "current_database" | null;
};

export type AuditLogDetail = AuditLogListItem & {
  detail: Record<string, unknown> | null;
  user_agent: string | null;
  question_detail: QuestionAuditDetail | null;
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
  display_name?: string;
  provider?: string;
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
  api_base_url: string;
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
  api_key?: string;
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

export type ReadyHealthResponse = {
  status: "ok" | "degraded" | string;
  db: "ok" | "unavailable" | string;
  redis: "ok" | "degraded" | string;
};

// ── Vector / Embedding Config ──

export type VectorConfig = {
  vector_enabled: boolean;
  vector_cache_ttl_sec: number;
  vector_top_k: number;
  vector_similarity_threshold: number;
  embedding_model_config_id: number | null;
  embedding_dim: number;
  embedding_timeout: number;
  embedding_batch_size: number;
  updated_at: string | null;
};

export type VectorConfigPatchRequest = {
  vector_enabled?: boolean;
  vector_cache_ttl_sec?: number;
  vector_top_k?: number;
  vector_similarity_threshold?: number;
  embedding_model_config_id?: number | null;
  embedding_dim?: number;
  embedding_timeout?: number;
  embedding_batch_size?: number;
};

export type EmbeddingTestRequest = {
  model_config_id?: number;
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

// ── 批量答案补录 (Phase 1) ──

export type BatchAnswerPreviewItem = {
  import_id: number;
  source_order_index: number | null;
  source_question_no: string | null;
  stem_excerpt: string;
  question_type: string | null;
  original_answer: string | null;
  input_answer: string | null;
  normalized_answer: string | null;
  status: string;
  status_message: string;
  will_update: boolean;
  validation_errors: string[];
};

export type BatchAnswerPreviewSummary = {
  batch_total: number;
  parsed_answer_count: number;
  target_question_count: number;
  remaining_question_count: number;
  writable_count: number;
  skipped_existing_count: number;
  skipped_existing_same_count: number;
  unsupported_count: number;
  invalid_count: number;
  warning_count: number;
  order_anomaly_count: number;
};

export type BatchAnswerPreviewResponse = {
  batch_id: string;
  preview_token: string;
  operation_id: string;
  summary: BatchAnswerPreviewSummary;
  items: BatchAnswerPreviewItem[];
  warnings: string[];
};

export type BatchAnswerApplyResponse = {
  operation_id: string;
  updated_count: number;
  skipped_existing_count: number;
  remaining_count: number;
  batch_stats: Record<string, number>;
};

// ── 批量答案补录 — 图片导入 (Phase 2) ──

export type BatchAnswerImagePreviewItem = {
  import_id: number | null;
  source_order_index: number | null;
  source_question_no: string | null;
  stem_excerpt: string;
  question_type: string | null;
  original_answer: string | null;
  original_analysis: string | null;
  extracted_answer: string | null;
  extracted_analysis: string | null;
  status: string; // matched | unmatched | ambiguous
  status_message: string;
  will_update_answer: boolean;
  will_update_analysis: boolean;
  validation_errors: string[];
  source_filename: string | null;
  image_index: number | null;
  ocr_confidence: number | null;
  extract_method: string | null;
  raw_text_excerpt: string | null;
};

export type BatchAnswerImagePreviewSummary = {
  total_images: number;
  extracted_entries: number;
  matched_count: number;
  unmatched_count: number;
  ambiguous_count: number;
  writable_answer_count: number;
  writable_analysis_count: number;
  skipped_existing_answer_count: number;
  skipped_existing_analysis_count: number;
};

export type BatchAnswerImagePreviewResponse = {
  batch_id: string;
  preview_token: string;
  operation_id: string;
  summary: BatchAnswerImagePreviewSummary;
  items: BatchAnswerImagePreviewItem[];
  warnings: string[];
};

export type BatchAnswerImageApplyResponse = {
  operation_id: string;
  updated_answer_count: number;
  updated_analysis_count: number;
  skipped_existing_answer_count: number;
  skipped_existing_analysis_count: number;
  remaining_count: number;
  batch_stats: Record<string, number>;
};

// ── Formula Graph Asset ──

export type FormulaGraphAsset = {
  id: number;
  formula_card_id: number;
  source_type: "uploaded" | "template" | "generated" | string;
  template_type?: string | null;
  template_parameters?: Record<string, unknown> | null;
  viewport?: Record<string, unknown> | null;
  image_url?: string | null;
  thumbnail_url?: string | null;
  original_svg_url?: string | null;
  mime_type?: string | null;
  width?: number | null;
  height?: number | null;
  file_size?: number | null;
  checksum?: string | null;
  renderer_version?: number | null;
  alt_text?: string | null;
  description?: string | null;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  review_note?: string | null;
  published_version?: number | null;
  created_at?: string;
  updated_at?: string;
};

// ── Graph Spec (auto-generation) ──

export type GraphSpecExpression = {
  expression: string;
  display_latex?: string | null;
  label?: string | null;
  line_style?: "solid" | "dashed" | "dotted" | "dashdot";
};

export type GraphSpecDomain = {
  intervals: Array<[number | null, number | null]>;
  exclude_points?: number[];
};

export type GraphSpecAnnotation = {
  x: number;
  y: number;
  label?: string | null;
  color?: string | null;
  point_style?: "filled" | "hollow";
};

export type GraphSpecRefLine = {
  value: number;
  label?: string | null;
  style?: "solid" | "dashed" | "dotted" | "dashdot";
  is_vertical?: boolean;
};

export type GraphSpecLayout = {
  rows: number;
  columns: number;
};

export type GraphSpecPanel = {
  expressions: GraphSpecExpression[];
  domain?: GraphSpecDomain;
  axis_mode?: "manual" | "auto" | "auto_robust";
  x_range?: [number, number];
  y_range?: [number, number];
  annotations?: GraphSpecAnnotation[];
  vertical_lines?: GraphSpecRefLine[];
  horizontal_lines?: GraphSpecRefLine[];
  title?: string | null;
  x_label?: string;
  y_label?: string;
};

export type GraphSpec = {
  schema_version: number;
  render_mode: "explicit_2d" | "preset_diagram" | "manual_only";
  template: "single_function" | "function_comparison" | "multi_panel" | "discontinuity_comparison" | "inequality_auxiliary";
  layout?: GraphSpecLayout;
  panels: GraphSpecPanel[];
};

export type GraphStatus =
  | "not_applicable"
  | "unconfigured"
  | "missing"
  | "generating"
  | "draft"
  | "ready"
  | "failed"
  | "ignored";

export type QualityCheckResult = {
  errors: string[];
  warnings: string[];
  passed: boolean;
};

export type GraphPreviewResponse = {
  preview_url: string;
  thumbnail_url?: string | null;
  preview_token: string;
  checksum: string;
  width: number;
  height: number;
  mime_type: string;
  quality: QualityCheckResult;
  expires_at: string;
};

export type GraphConfirmRequest = {
  preview_token: string;
  checksum: string;
  card_version: number;
  accept_warnings?: boolean;
};

export type GraphConfirmResponse = {
  asset: FormulaGraphAsset;
  graph_status: string;
};

export type FormulaCardType = "auto" | "pure_formula" | "function_graph";

// ── 推荐系统 (recommendation) ──

export type RecommendationScene = "practice_smart" | "similar" | "knowledge_path" | "wrong_variant";

export type RecommendationStrategy = {
  id: number;
  name: string;
  display_name: string;
  description: string | null;
  scene: RecommendationScene;
  is_active: boolean;
  is_default: boolean;
  weight_vector_similarity: number;
  weight_knowledge_overlap: number;
  weight_difficulty_match: number;
  weight_mastery_gap: number;
  weight_path_priority: number;
  exploration_ratio: number;
  config_json: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type RecommendationStrategyUpsert = {
  name: string;
  display_name?: string;
  description?: string | null;
  scene: RecommendationScene;
  is_active?: boolean;
  is_default?: boolean;
  weight_vector_similarity?: number;
  weight_knowledge_overlap?: number;
  weight_difficulty_match?: number;
  weight_mastery_gap?: number;
  weight_path_priority?: number;
  exploration_ratio?: number;
  config_json?: Record<string, unknown> | null;
};

export type ExperimentVariant = { key: string; strategy: string; ratio: number };

export type RecommendationExperiment = {
  id: number;
  name: string;
  scene: string;
  description: string | null;
  status: "draft" | "running" | "paused" | "finished";
  start_at: string | null;
  end_at: string | null;
  traffic_ratio: number;
  variants: ExperimentVariant[] | null;
  max_traffic_percent: number;
  fallback_strategy_name: string | null;
  auto_pause_on_error_rate: number | null;
  min_sample_size: number;
  started_at: string | null;
  ended_at: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ExperimentCreate = {
  name: string;
  scene: string;
  description?: string | null;
  start_at?: string | null;
  end_at?: string | null;
  traffic_ratio?: number;
  variants: ExperimentVariant[];
  max_traffic_percent?: number;
  fallback_strategy_name?: string | null;
  auto_pause_on_error_rate?: number | null;
  min_sample_size?: number;
};

export type RecommendationMetricsDaily = {
  date: string;
  subject_id: number;
  subject_code?: string | null;
  subject_name?: string | null;
  scene: string;
  strategy: string;
  variant_key: string | null;
  exposure_count: number;
  click_count: number;
  answer_count: number;
  correct_count: number;
  wrong_count: number;
  avg_recommend_score: number;
  avg_similarity: number;
  avg_mastery_before: number | null;
  avg_mastery_after: number | null;
  avg_mastery_delta: number | null;
  completion_rate: number;
  accuracy: number;
  ctr: number;
};

export type SeedStrategiesResponse = { created: number; updated: number; skipped: number };
export type MetricsAggregateResponse = { aggregated_rows: number; target_date: string; subject_id: number | null };
export type MetricsBackfillResponse = { success_dates: string[]; failed_dates: string[]; errors: string[] };
export type SafetyCheckResponse = { paused: boolean; reason: string | null; metrics: Record<string, unknown> };
export type VariantComparisonResponse = { experiment_id: number; experiment_name: string; variants: Record<string, unknown>[] };
export type HealthReportResponse = {
  total_recommendation_logs: number;
  fallback_rate: number;
  empty_recommendation_count: number;
  low_similarity_rate: number;
  strategy_resolve_failed_count: number;
  experiment_assignment_count: number;
  experiment_variant_distribution: Record<string, unknown>;
  vector_recall_failure_count: number;
  knowledge_path_empty_count: number;
  top_fallback_scenes: Record<string, unknown>[];
  top_error_strategies: Record<string, unknown>[];
  warnings: string[];
};
export type RecommendationQualityReport = {
  summary: Record<string, unknown>;
  warnings: string[];
  hot_questions: Record<string, unknown>[];
  high_fallback_scenes: Record<string, unknown>[];
  low_similarity_samples: Record<string, unknown>[];
};
export type KnowledgeQualityReport = {
  summary: Record<string, unknown>;
  warnings: string[];
  isolated_knowledge_points: Record<string, unknown>[];
  low_question_count_points: Record<string, unknown>[];
  cycles: number[][];
};

// ── 管理端知识图谱 ──

export type KnowledgeGraphSubject = {
  id: number;
  code: string;
  name: string;
  level: number;
  path: string;
  knowledge_point_count: number;
  edge_count: number;
};

export type KnowledgeGraphNode = {
  id: number;
  name: string;
  normalized_name: string;
  aliases: string[];
  description: string | null;
  difficulty_level: number;
  subject_id: number;
  question_count: number;
  in_degree: number;
  out_degree: number;
  degree: number;
  relation_counts: Record<string, number>;
};

export type KnowledgeGraphEdge = {
  id: number;
  source: number;
  target: number;
  relation_type: "prerequisite" | "parent" | "related" | "next";
  weight: number;
  confidence: number;
  source_type: "manual" | "imported" | "ai" | "inferred" | string;
};

export type KnowledgeGraphSummary = {
  total_nodes: number;
  total_edges: number;
  visible_nodes: number;
  visible_edges: number;
  isolated_nodes: number;
  avg_confidence: number;
  relation_counts: Record<string, number>;
  source_counts: Record<string, number>;
  relation_confidence: Record<string, number>;
};

export type KnowledgeGraphResponse = {
  subject: { id: number; code: string; name: string };
  summary: KnowledgeGraphSummary;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  hot_nodes: Array<{ id: number; name: string; degree: number }>;
  focus_id: number | null;
};

// ── Async task observability / diagnostics ──

export type TaskHealthIssue = {
  code: string;
  severity: "warning" | "error";
  message: string;
  value?: number | null;
};

export type TaskQueueDiagnostic = {
  task_type: string;
  ready: number;
  processing: number;
  retry: number;
  dead: number;
  corrupt: number;
  oldest_ready_seconds: number;
};

export type TaskOutboxFailure = {
  outbox_id: number;
  task_id: string;
  task_type: string;
  retry_count: number;
  last_error?: string | null;
  trace_id?: string | null;
  request_id?: string | null;
  updated_at: string;
};

export type TaskDiagnosticsResponse = {
  generated_at: string;
  async_runtime_expected: boolean;
  health: {
    ok: boolean;
    severity: "ok" | "warning" | "error";
    issues: TaskHealthIssue[];
  };
  outbox: {
    counts: Record<string, number>;
    unpublished: number;
    oldest_unpublished_seconds: number;
    oldest_unpublished_at?: string | null;
    pending_by_type: Record<string, number>;
    recent_failures: TaskOutboxFailure[];
  };
  redis: {
    configured: boolean;
    available: boolean;
    error?: string | null;
    queues: TaskQueueDiagnostic[];
    totals: {
      ready: number;
      processing: number;
      retry: number;
      dead: number;
      corrupt: number;
    };
    oldest_ready_seconds: number;
  };
  projection: {
    unprojected: number;
    oldest_age_sec: number;
    oldest_answered_at?: string | null;
    projection_receipts_total: number;
    repairs_scheduled_24h: number;
  };
  trend: Array<{
    date: string;
    created: number;
    published: number;
    failed: number;
    projection_receipts: number;
  }>;
};

export type TaskTraceItem = {
  outbox_id: number;
  task_id: string;
  task_type: string;
  trace_id?: string | null;
  request_id?: string | null;
  outbox_status: string;
  outbox_retry_count: number;
  outbox_error?: string | null;
  created_at: string;
  published_at?: string | null;
  updated_at: string;
  practice_record_id?: number | null;
  projection_receipt_at?: string | null;
  queue?: {
    status?: string | null;
    retry_count: number;
    generation: number;
    created_at?: number | null;
    updated_at?: number | null;
    last_error?: string | null;
  } | null;
};

export type TaskTraceResponse = {
  trace_id: string;
  redis_available: boolean;
  items: TaskTraceItem[];
  total: number;
};

// ── System task center ────────────────────────────────────────

export type ScheduledSystemTask = {
  task_id: string;
  name: string;
  description: string;
  task_type: "scheduled" | "system";
  executor: "scheduler" | "systemd" | string;
  status: "idle" | "running" | "failed" | "disabled" | string;
  enabled: boolean;
  schedule: string;
  next_run_at?: string | null;
  next_run_label?: string | null;
  last_run_at?: string | null;
  last_status?: "success" | "failed" | "skipped" | string | null;
  last_message?: string | null;
  last_duration_ms?: number | null;
  last_source?: "scheduler" | "manual" | "systemd" | string | null;
  can_run_now: boolean;
  executor_available?: boolean | null;
  executor_state?: string | null;
  note?: string | null;
  artifact_name?: string | null;
  artifact_size_bytes?: number | null;
  artifact_created_at?: string | null;
  backup_count?: number | null;
  backup_dir?: string | null;
  script_available?: boolean | null;
  pg_dump_available?: boolean | null;
  timer_unit?: string | null;
  service_unit?: string | null;
  service_loaded?: boolean | null;
};

export type ScheduledSystemTaskListResponse = {
  generated_at: string;
  tasks: ScheduledSystemTask[];
};

export type DatabaseBackupArtifact = {
  name: string;
  size_bytes: number;
  created_at: string;
  method?: string | null;
  database?: string | null;
};

export type DatabaseBackupHistoryResponse = {
  backup_dir: string;
  items: DatabaseBackupArtifact[];
  total: number;
};

export type AsyncTaskSummary = {
  task_id: string;
  task_type: string;
  status: string;
  queue_location?: "ready" | "processing" | "retry" | "dead" | "corrupt" | string | null;
  retry_count: number;
  max_retries: number;
  generation: number;
  trace_id?: string | null;
  request_id?: string | null;
  last_error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AsyncTaskListResponse = {
  tasks: AsyncTaskSummary[];
  total: number;
};

export type AsyncTaskDetail = AsyncTaskSummary & {
  payload_summary?: Record<string, unknown> | null;
  has_heartbeat: boolean;
  owner_token_prefix?: string | null;
};

export type TaskOperationResult = {
  task_id: string;
  operation: string;
  success: boolean;
  message: string;
};


export type AdminSubjectNode = {
  id: number;
  parent_id: number | null;
  code: string;
  name: string;
  level: number;
  path: string;
  sort_order: number;
  is_active: boolean;
  product_code?: string | null;
  product_scope?: string | null;
  is_product_core?: boolean;
  is_product_root?: boolean;
  created_at: string;
  updated_at: string;
  children: AdminSubjectNode[];
};

export type AdminSubjectListResponse = {
  items: AdminSubjectNode[];
};

export type AdminSubjectUpdateRequest = {
  is_active?: boolean;
  confirm_core_disable?: boolean;
};

export type AdminExamPaperType = "past_exam_choice" | "mock_choice";
export type AdminExamPaperStatus = "draft" | "published" | "archived";

export type AdminExamPaperListItem = {
  id: number;
  title: string;
  paper_type: AdminExamPaperType;
  year?: number | null;
  source?: string | null;
  duration_sec?: number | null;
  version: number;
  status: AdminExamPaperStatus;
  is_active: boolean;
  question_count: number;
  total_choice_score: number;
  attempt_count: number;
  published_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type AdminExamPaperQuestionItem = {
  id: number;
  question_id: number;
  question_version_id: number;
  position: number;
  score: number;
  subject_id: number;
  subject_code: string;
  subject_name: string;
  question_type: string;
  content: Record<string, unknown>;
  options?: QuestionOptionsValue;
  year?: number | null;
  source?: string | null;
  difficulty: number;
  review_status: string;
  is_active: boolean;
  current_version_id?: number | null;
  version_is_current: boolean;
};

export type AdminExamPaperDetail = AdminExamPaperListItem & {
  items: AdminExamPaperQuestionItem[];
  validation_errors: string[];
};


export type SyllabusVersionStatus = "draft" | "active" | "archived";
export type SyllabusMappingType =
  | "unchanged"
  | "renamed"
  | "added"
  | "removed"
  | "merged"
  | "split"
  | "replaced";

export type SyllabusVersionSummary = {
  id: number;
  code: string;
  name: string;
  effective_year: number;
  status: SyllabusVersionStatus;
  description?: string | null;
  knowledge_point_count: number;
  activated_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type SyllabusKnowledgePointItem = {
  id: number;
  knowledge_point_id: number;
  subject_id: number;
  subject_code: string;
  subject_name: string;
  name: string;
  normalized_name: string;
  description?: string | null;
  difficulty_level: number;
  sort_order: number;
};

export type SyllabusVersionDetail = SyllabusVersionSummary & {
  knowledge_points: SyllabusKnowledgePointItem[];
};

export type SyllabusCatalogItem = {
  knowledge_point_id: number;
  subject_id: number;
  subject_code: string;
  subject_name: string;
  name: string;
  description?: string | null;
  difficulty_level: number;
  included: boolean;
};

export type SyllabusCatalogResponse = {
  syllabus_version_id: number;
  items: SyllabusCatalogItem[];
};

export type SyllabusMappingItem = {
  id: number;
  from_syllabus_knowledge_point_id?: number | null;
  to_syllabus_knowledge_point_id?: number | null;
  relation_type: SyllabusMappingType;
  note?: string | null;
  from_name?: string | null;
  to_name?: string | null;
  created_at: string;
};

export type SyllabusCoverageItem = {
  syllabus_knowledge_point_id: number;
  knowledge_point_id: number;
  subject_id: number;
  subject_code: string;
  subject_name: string;
  name: string;
  question_count: number;
  covered: boolean;
};

export type SyllabusCoverageResponse = {
  syllabus_version_id: number;
  syllabus_code: string;
  total_knowledge_points: number;
  covered_knowledge_points: number;
  coverage_ratio: number;
  items: SyllabusCoverageItem[];
};
