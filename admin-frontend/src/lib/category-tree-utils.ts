/**
 * Generic pure tree operations for category nodes, extracted from
 * formulas/categories/page.tsx. These work with any tree of nodes that
 * have id, name, code, and children fields.
 */

export type CategoryTreeNode<T extends CategoryTreeNode<T>> = {
  id: number;
  name: string;
  code: string;
  children?: T[];
};

/**
 * Find a node by id in a tree, returns null when not found or id is null.
 */
export function findNodeInTree<T extends CategoryTreeNode<T>>(
  nodes: T[],
  id: number | null,
): T | null {
  if (id === null) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findNodeInTree(node.children ?? [], id);
    if (found) return found;
  }
  return null;
}

/**
 * Find the parent of a node by id, returns null when not found or id is null.
 */
export function findParentNode<T extends CategoryTreeNode<T>>(
  nodes: T[],
  id: number | null,
  parent: T | null = null,
): T | null {
  if (id === null) return null;
  for (const node of nodes) {
    if (node.id === id) return parent;
    const found = findParentNode(node.children ?? [], id, node);
    if (found) return found;
  }
  return null;
}

/**
 * Find the path from root to a node by id. Returns empty array when not found.
 */
export function findPathToNode<T extends CategoryTreeNode<T>>(
  nodes: T[],
  id: number | null,
): T[] {
  if (id === null) return [];
  for (const node of nodes) {
    if (node.id === id) return [node];
    const childPath = findPathToNode(node.children ?? [], id);
    if (childPath.length) return [node, ...childPath];
  }
  return [];
}

/**
 * Count all descendants of a node (not including the node itself).
 */
export function countDescendants<T extends CategoryTreeNode<T>>(node: T | null): number {
  if (!node) return 0;
  return (node.children ?? []).reduce((total, child) => total + 1 + countDescendants(child), 0);
}

/**
 * Filter a category tree by a search query, keeping nodes that match by
 * name or code, or have matching descendants. Case-insensitive.
 */
export function filterCategoryTree<T extends CategoryTreeNode<T>>(
  nodes: T[],
  query: string,
): T[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return nodes;
  return nodes.flatMap((node) => {
    const children = filterCategoryTree(node.children ?? [], normalized);
    const selfMatches =
      node.name.toLowerCase().includes(normalized) || node.code.toLowerCase().includes(normalized);
    return selfMatches || children.length ? [{ ...node, children }] : [];
  });
}
