export const ACTION_LABELS: Record<string, string> = {
  "question.update": "编辑题目",
  "question.delete": "删除题目",
  "question.batch_delete": "批量删除题目",
  "question.toggle_active": "修改题目启用状态",
  "question.backfill_embeddings": "题目向量回填",
  "question.approve": "审核通过",
  "subject.create": "新增科目",
  "subject.update": "编辑科目",
  "subject.delete": "删除科目",
  "admin_user.create": "新增管理员",
  "admin_user.update": "编辑管理员",
  "admin_user.delete": "删除管理员",
  "admin_user.force_logout": "强制登出",
  "admin_user.reset_password": "重置密码",
  "admin_user.change_password": "修改密码",
  "app_user.update": "编辑用户",
  "app_user.ban": "封禁用户",
  "app_user.unban": "解封用户",
  "app_user.bind_admin": "绑定管理员",
  "app_user.unbind_admin": "解绑管理员",
  "ai_model_config.create": "新增AI模型",
  "ai_model_config.update": "编辑AI模型",
  "ai_model_config.delete": "删除AI模型",
  "ai_config.update": "更新AI配置",
  "ai_setting.update": "更新AI设置",
  "ai_setting.disable": "关闭AI解析",
  "ai_parse.blocked": "AI解析被拒绝",
  "ai_quota.exhausted": "AI额度耗尽",
  "role.update_permissions": "修改角色权限",
  "import.complete": "AI补全导入题",
  "import.batch_complete": "AI批量补全",
  "import.enrich": "AI富化导入题",
  "watermark_rule.create": "新增水印规则",
  "watermark_rule.update": "编辑水印规则",
  "watermark_rule.delete": "删除水印规则",
  "vector_config.update": "更新向量配置",
  "knowledge.backfill": "知识点回填",
  "knowledge.create_edge": "创建知识图谱边",
  "knowledge.infer_edges": "推断知识图谱边",
};

export const SEVERITY_LABELS: Record<string, string> = {
  critical: "严重",
  important: "重要",
  normal: "普通",
  low: "低",
};

export const STATUS_LABELS: Record<string, string> = {
  success: "成功",
  failed: "失败",
};

export const RESOURCE_TYPE_LABELS: Record<string, string> = {
  question: "题目",
  subject: "科目",
  admin_user: "管理员",
  app_user: "普通用户",
  role: "角色",
  watermark_rule: "水印规则",
  knowledge_point: "知识点",
  knowledge_edge: "知识边",
  ai_model_config: "AI 配置",
  ai_config: "AI 配置",
  ai_setting: "AI 设置",
  vector_config: "向量配置",
  import: "导入",
};

export const DATA_SOURCE_LABELS: Record<string, string> = {
  audit_snapshot: "操作时快照",
  audit_before: "操作前快照",
  audit_after: "操作后快照",
  audit_summary: "日志摘要",
  current_database: "当前数据库内容，仅用于兼容历史日志",
};

export const TONE_MAP: Record<string, "danger" | "warning" | "primary" | "neutral"> = {
  critical: "danger",
  important: "warning",
  normal: "primary",
  low: "neutral",
};

export const CHANGED_FIELD_LABELS: Record<string, string> = {
  content: "题干",
  options: "选项",
  answer: "答案",
  analysis: "解析",
  difficulty: "难度",
  is_active: "启用状态",
  review_status: "审核状态",
  knowledge_points: "知识点",
  subject_id: "科目",
  question_type: "题型",
  source: "来源",
  source_type: "来源类型",
  year: "年份",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] || action;
}

export function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity] || severity;
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] || status;
}

export function resourceTypeLabel(type: string): string {
  return RESOURCE_TYPE_LABELS[type] || type;
}

export function changedFieldLabel(field: string): string {
  return CHANGED_FIELD_LABELS[field] || field;
}

export function friendlyBoolean(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value ? "是 / 已启用" : "否 / 已停用";
}

export function friendlyStatus(value: string | null | undefined): string {
  if (!value) return "—";
  const map: Record<string, string> = {
    approved: "已通过",
    pending: "待审核",
    rejected: "已拒绝",
    draft: "草稿",
  };
  return map[value] || value;
}
