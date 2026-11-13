import { beforeEach, describe, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import { Sidebar } from "./sidebar";

type Element = ReactElement<Record<string, unknown>>;
type AuthState = { role: { name: string }; permissions: string[] };

// The sidebar owns its expanded-group state with useState + useLayoutEffect.
// The project has no jsdom/react-testing-library (and must not add them), so the
// hooks are replaced with a tiny deterministic harness: state slots persist across
// renders like React state, and layout effects run only when explicitly flushed.
const h = vi.hoisted(() => ({
  states: [] as unknown[],
  stateIndex: 0,
  layoutEffects: [] as (() => void)[],
  pathname: "/questions",
  auth: { role: { name: "super_admin" }, permissions: [] as string[] } as AuthState,
}));

vi.mock("react", async (original) => ({
  ...(await original<typeof import("react")>()),
  useMemo: (compute: () => unknown) => compute(),
  useState: (initial: unknown) => {
    const index = h.stateIndex++;
    if (!(index in h.states)) h.states[index] = initial;
    const setter = (value: unknown) => {
      h.states[index] =
        typeof value === "function"
          ? (value as (current: unknown) => unknown)(h.states[index])
          : value;
    };
    return [h.states[index], setter];
  },
  useLayoutEffect: (effect: () => void) => {
    h.layoutEffects.push(effect);
  },
}));

vi.mock("next/navigation", () => ({ usePathname: () => h.pathname }));
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: AuthState) => unknown) => select(h.auth),
}));

function renderSidebar(): Element {
  h.stateIndex = 0;
  h.layoutEffects = [];
  return Sidebar() as Element;
}

function flushLayoutEffects() {
  h.layoutEffects.forEach((effect) => effect());
}

function walk(node: unknown, visit: (element: Element) => void) {
  if (Array.isArray(node)) {
    node.forEach((item) => walk(item, visit));
    return;
  }
  if (!isValidElement<Record<string, unknown>>(node)) return;
  visit(node);
  walk(node.props.children, visit);
}

function groupExpansion(tree: unknown): Record<string, boolean> {
  const expansion: Record<string, boolean> = {};
  walk(tree, (element) => {
    if (element.type !== "button") return;
    const controls = element.props["aria-controls"];
    if (typeof controls === "string" && controls.startsWith("sidebar-group-")) {
      expansion[controls.slice("sidebar-group-".length)] = element.props["aria-expanded"] === true;
    }
  });
  return expansion;
}

function groupButton(tree: unknown, key: string): Element {
  let found: Element | undefined;
  walk(tree, (element) => {
    if (element.type === "button" && element.props["aria-controls"] === `sidebar-group-${key}`) {
      found = element;
    }
  });
  if (!found) throw new Error(`missing sidebar group button: ${key}`);
  return found;
}

function logoLink(tree: unknown): Element {
  let found: Element | undefined;
  walk(tree, (element) => {
    if (element.props.href === "/dashboard" && String(element.props.className ?? "").includes("mb-8")) {
      found = element;
    }
  });
  if (!found) throw new Error("missing MemoGrad logo link");
  return found;
}

beforeEach(() => {
  h.states = [];
  h.stateIndex = 0;
  h.layoutEffects = [];
  h.pathname = "/questions";
  h.auth = { role: { name: "super_admin" }, permissions: [] };
});

describe("sidebar expanded group ownership", () => {
  it("collapses every expanded group when the logo navigates back to the dashboard", () => {
    // Arrange: a child route keeps its parent group expanded.
    let tree = renderSidebar();
    flushLayoutEffects();
    expect(groupExpansion(tree)["question-management"]).toBe(true);

    // Act: the logo sends the user to /dashboard, which belongs to no group.
    h.pathname = "/dashboard";
    renderSidebar();
    flushLayoutEffects();

    // Assert: no group stays expanded.
    expect(h.states[0]).toBeNull();
    tree = renderSidebar();
    const expansion = groupExpansion(tree);
    expect(expansion["question-management"]).toBe(false);
    expect(Object.values(expansion).some(Boolean)).toBe(false);
  });

  it("collapses a manually expanded group when the logo is clicked while already on the dashboard", () => {
    h.pathname = "/dashboard";
    h.states[0] = "system-management";
    let tree = renderSidebar();
    expect(groupExpansion(tree)["system-management"]).toBe(true);

    const onClick = logoLink(tree).props.onClick;
    expect(typeof onClick).toBe("function");

    // Clicking the logo must collapse the panel and hand the click back to the
    // link itself (no extra side effects beyond the normal navigation).
    expect((onClick as () => void)()).toBeUndefined();
    expect(h.states[0]).toBeNull();
    tree = renderSidebar();
    expect(groupExpansion(tree)["system-management"]).toBe(false);
  });

  it("keeps accordion semantics when moving between child routes", () => {
    renderSidebar();
    flushLayoutEffects();

    h.pathname = "/audit-logs";
    renderSidebar();
    flushLayoutEffects();

    const expansion = groupExpansion(renderSidebar());
    expect(expansion["system-management"]).toBe(true);
    expect(expansion["question-management"]).toBe(false);
    expect(Object.values(expansion).filter(Boolean)).toHaveLength(1);
  });

  it("keeps manual parent toggles working on a child route", () => {
    h.pathname = "/questions";
    let tree = renderSidebar();
    flushLayoutEffects();

    (groupButton(tree, "question-management").props.onClick as () => void)();
    expect(h.states[0]).toBeNull();

    tree = renderSidebar();
    expect(groupExpansion(tree)["question-management"]).toBe(false);

    (groupButton(tree, "system-management").props.onClick as () => void)();
    expect(h.states[0]).toBe("system-management");
  });
});
