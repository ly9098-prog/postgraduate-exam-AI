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

export type AdminQuestion = {
  id: number;
  subject: string;
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

export type AdminQuestionDetail = AdminQuestion & {
  import_record?: unknown;
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

export type DashboardOverview = {
  users_total: number;
  users_new_today: number;
  questions_total: number;
  questions_pending_review: number;
  questions_approved: number;
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

export type AuditLog = {
  id: number;
  operator_id?: number | null;
  operator_name?: string | null;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  severity: "critical" | "important" | "normal" | "low";
  status?: "success" | "failed";
  detail?: Record<string, unknown> | null;
  user_agent?: string | null;
  ip?: string | null;
  error_message?: string | null;
  created_at?: string;
};
