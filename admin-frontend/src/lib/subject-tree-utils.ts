/**
 * Pure helpers for subjects page, extracted from subjects/page.tsx.
 * Covers flattening, relation building, summarizing, scoping, and tree status updates.
 */

import type { AdminSubjectNode } from "@/lib/api/types";

export type FlatSubject = AdminSubjectNode & { depth: number };

/**
 * Flatten a subject tree into a list with depth annotations.
 */
export function flattenSubjects(items: AdminSubjectNode[], depth = 0): FlatSubject[] {
  return items.flatMap((item) => [
    { ...item, depth },
    ...flattenSubjects(item.children || [], depth + 1),
  ]);
}

export type SubjectRelations = {
  activeDescendantsById: Map<number, AdminSubjectNode[]>;
  inactiveAncestorsById: Map<number, AdminSubjectNode[]>;
};

/**
 * Build descendant/ancestor relation maps for active/inactive subjects.
 */
export function buildSubjectRelations(items: AdminSubjectNode[]): SubjectRelations {
  const activeDescendantsById = new Map<number, AdminSubjectNode[]>();
  const inactiveAncestorsById = new Map<number, AdminSubjectNode[]>();

  function walk(item: AdminSubjectNode, ancestors: AdminSubjectNode[]): AdminSubjectNode[] {
    inactiveAncestorsById.set(item.id, ancestors.filter((ancestor) => !ancestor.is_active));

    const activeDescendants: AdminSubjectNode[] = [];
    for (const child of item.children || []) {
      if (child.is_active) activeDescendants.push(child);
      activeDescendants.push(...walk(child, [...ancestors, item]));
    }
    activeDescendantsById.set(item.id, activeDescendants);
    return activeDescendants;
  }

  for (const item of items) walk(item, []);

  return { activeDescendantsById, inactiveAncestorsById };
}

/**
 * Summarize a list of subjects into a short string (e.g. "数据结构、操作系统 等 5 个科目").
 */
export function summarizeSubjects(subjects: AdminSubjectNode[], max = 3): string {
  const names = subjects.slice(0, max).map((subject) => subject.name);
  if (subjects.length <= max) return names.join("、");
  return `${names.join("、")} 等 ${subjects.length} 个科目`;
}

/**
 * Get the scope label for a subject.
 */
export function scopeLabel(subject: AdminSubjectNode): string {
  if (subject.is_product_root) return "产品根科目";
  if (subject.product_scope === "exam408") return "核心科目";
  return "扩展科目";
}

/**
 * Get the scope tone for a subject badge.
 */
export function scopeTone(subject: AdminSubjectNode): "accent" | "neutral" {
  return subject.product_scope === "exam408" ? "accent" : "neutral";
}

/**
 * Update the is_active status of a subject and its descendants/ancestors in the tree.
 * When deactivating, all descendants are also deactivated.
 * When activating, the path from root to the target is activated.
 */
export function updateSubjectTreeStatus(
  items: AdminSubjectNode[],
  subjectId: number,
  isActive: boolean,
): AdminSubjectNode[] {
  if (!isActive) {
    return items.map((item) => ({
      ...item,
      is_active: item.id === subjectId ? false : item.is_active,
      children: updateSubjectTreeStatus(item.children || [], subjectId, false),
    }));
  }

  function activatePath(item: AdminSubjectNode): [AdminSubjectNode, boolean] {
    const childResults = (item.children || []).map(activatePath);
    const containsTarget = item.id === subjectId || childResults.some(([, contains]) => contains);
    return [
      {
        ...item,
        is_active: containsTarget ? true : item.is_active,
        children: childResults.map(([child]) => child),
      },
      containsTarget,
    ];
  }

  return items.map((item) => activatePath(item)[0]);
}
