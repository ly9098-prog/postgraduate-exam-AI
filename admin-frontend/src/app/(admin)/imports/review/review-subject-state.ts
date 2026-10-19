export type ReviewSubjectOption = {
  id: number;
  parent_id?: number | null;
  path?: string | null;
  is_leaf?: boolean;
};

function isLeafByPath(
  subject: ReviewSubjectOption,
  allSubjects: ReviewSubjectOption[],
): boolean {
  const currentId = String(subject.id);
  return !allSubjects.some((item) => {
    if (!item.path) return false;
    const parts = String(item.path).split("/").map((part) => part.trim()).filter(Boolean);
    return parts.slice(0, -1).includes(currentId);
  });
}

export function getLeafSubjectOptions<T extends ReviewSubjectOption>(all: T[]): T[] {
  if (!all.length) return [];
  if (all.some((subject) => typeof subject.is_leaf === "boolean")) {
    return all.filter((subject) => subject.is_leaf === true);
  }
  if (all.some((subject) => subject.parent_id !== undefined)) {
    const parentIds = new Set(
      all.map((subject) => subject.parent_id)
        .filter((id): id is number => id !== null && id !== undefined),
    );
    return all.filter((subject) => !parentIds.has(subject.id));
  }
  if (all.some((subject) => subject.path)) {
    return all.filter((subject) => isLeafByPath(subject, all));
  }
  return all;
}
