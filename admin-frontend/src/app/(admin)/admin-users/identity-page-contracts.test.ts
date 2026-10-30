import { beforeEach, describe, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";
import AdminUsersPage from "./page";
import AppUsersPage from "../app-users/page";
import RolesPage from "../roles/page";
import AuditLogsPage from "../audit-logs/page";
import LoginPage from "../../(auth)/login/page";
import Home from "../../page";
import { AdminShell } from "@/components/layout/admin-shell";
import { AuditLogDrawer } from "@/components/audit-logs/audit-log-drawer";

type Query = { queryKey: unknown[]; queryFn: () => Promise<unknown>; enabled?: boolean };
type Mutation = {
  mutationFn: (input?: unknown) => Promise<unknown>;
  onSuccess: (result?: unknown, input?: unknown) => Promise<void> | void;
  onError: (error: unknown) => void;
};
type Element = ReactElement<Record<string, unknown>>;
const h = vi.hoisted(() => ({
  states: [] as unknown[], stateIndex: 0,
  setters: [] as ReturnType<typeof vi.fn>[], effects: [] as (() => unknown)[],
  queries: [] as Query[], mutations: [] as Mutation[],
  data: {} as Record<string, unknown>,
  auth: { role: { name: "super_admin" }, permissions: [] as string[], isBootstrapping: false, isAuthenticated: false },
  next: "/admin-users", path: "/roles",
  request: vi.fn(), toQuery: vi.fn(() => "?fixture"),
  invalidate: vi.fn(), replace: vi.fn(), redirect: vi.fn(), login: vi.fn(),
}));
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useMemo: (compute: () => unknown) => compute(),
  useCallback: (callback: unknown) => callback,
  useRef: (current: unknown) => ({ current }),
  useEffect: (effect: () => unknown) => { h.effects.push(effect); },
  useState: (initial: unknown) => {
    const index = h.stateIndex++;
    const setter = vi.fn();
    h.setters.push(setter);
    return [index in h.states ? h.states[index] : initial, setter];
  },
}));
vi.mock("@tanstack/react-query", () => ({
  keepPreviousData: (data: unknown) => data,
  useQueryClient: () => ({ invalidateQueries: h.invalidate }),
  useQuery: (query: Query) => {
    h.queries.push(query);
    return { data: h.data[JSON.stringify(query.queryKey)], isLoading: false, isFetching: false };
  },
  useMutation: (mutation: Mutation) => {
    h.mutations.push(mutation);
    return { mutate: vi.fn(), reset: vi.fn(), isPending: false };
  },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: h.replace }),
  useSearchParams: () => new URLSearchParams({ next: h.next }),
  usePathname: () => h.path,
  redirect: (path: string) => { h.redirect(path); throw new Error("redirect"); },
}));
vi.mock("@/lib/auth/auth-store", () => ({
  useAuthStore: (select: (state: typeof h.auth & { login: typeof h.login }) => unknown) =>
    select({ ...h.auth, login: h.login }),
}));
vi.mock("@/lib/auth/use-auth-bootstrap", () => ({ useAuthBootstrap: () => undefined }));
vi.mock("@/lib/api/client", () => ({ apiRequest: h.request, toQuery: h.toQuery }));

function findElement(node: unknown, type: string): Element | undefined {
  if (Array.isArray(node)) {
    return node.map((item) => findElement(item, type)).find(Boolean);
  }
  if (!isValidElement<Record<string, unknown>>(node)) return;
  if (node.type === type) return node;
  return findElement(node.props.children, type);
}
function renderLogin() {
  const wrapper = LoginPage() as ReactElement<{ children: ReactElement }>;
  const form = findElement((wrapper.props.children.type as () => unknown)(), "form")!;
  return form.props.onSubmit as (event: { preventDefault: () => void }) => Promise<void>;
}
beforeEach(() => {
  vi.clearAllMocks();
  h.states = []; h.stateIndex = 0; h.setters = []; h.effects = [];
  h.queries = []; h.mutations = []; h.data = {};
  h.auth = { role: { name: "super_admin" }, permissions: [], isBootstrapping: false, isAuthenticated: false };
  h.next = "/admin-users"; h.path = "/roles";
  h.request.mockReset().mockResolvedValue({ id: 12 });
  h.invalidate.mockReset().mockResolvedValue(undefined);
  h.login.mockReset().mockResolvedValue(undefined);
});

describe("login and shell ownership", () => {
  it("keeps the root redirect in Next navigation", () => {
    expect(() => Home()).toThrow("redirect");
    expect(h.redirect).toHaveBeenCalledWith("/dashboard");
  });

  it("waits for login before redirecting to a safe internal destination", async () => {
    h.states = ["operator", ["Unit", "Only", "12345!"].join(""), "", false];
    let release!: () => void;
    h.login.mockReturnValue(new Promise<void>((resolve) => { release = resolve; }));
    const submit = renderLogin();
    const preventDefault = vi.fn();
    const pending = submit({ preventDefault });
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(h.login).toHaveBeenCalledWith(h.states[0], h.states[1]);
    expect(h.replace).not.toHaveBeenCalled();
    expect(h.setters[3]).toHaveBeenCalledWith(true);
    release();
    await pending;
    expect(h.replace).toHaveBeenCalledWith("/admin-users");
    expect(h.setters[3]).toHaveBeenLastCalledWith(false);
  });

  it("rejects external login destinations through the real redirect helper", async () => {
    h.next = "https://example.invalid/escape";
    await renderLogin()({ preventDefault: vi.fn() });
    expect(h.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("keeps failed-login details opaque and restores the loading state", async () => {
    h.login.mockRejectedValue(new Error("private provider detail"));
    await renderLogin()({ preventDefault: vi.fn() });
    expect(h.replace).not.toHaveBeenCalled();
    expect(h.setters[2]).toHaveBeenLastCalledWith("用户名或密码错误");
    expect(h.setters[3]).toHaveBeenLastCalledWith(false);
  });

  it("waits for bootstrap before redirecting unauthenticated shell users", () => {
    h.auth.isBootstrapping = true;
    AdminShell({ children: null });
    h.effects[0]();
    expect(h.replace).not.toHaveBeenCalled();
  });

  it("preserves the protected pathname for the login return route", () => {
    expect(AdminShell({ children: null })).toBeNull();
    h.effects[0]();
    expect(h.replace).toHaveBeenCalledWith("/login?next=%2Froles");
  });
});

describe("Admin user request ownership", () => {
  it("keeps list filters and global summary reads in distinct scopes", async () => {
    h.states = ["draft", "committed", "3", "inactive", "", "", 2, 50];
    AdminUsersPage();
    await h.queries[0].queryFn();
    expect(h.queries[0].queryKey.slice(0, 6)).toEqual(["admin-users", 2, 50, "committed", "3", "inactive"]);
    expect(h.toQuery).toHaveBeenCalledWith({
      page: 2, page_size: 50, keyword: "committed", role_id: 3, is_active: false,
      created_from: undefined, created_to: undefined,
    });
    expect(h.queries.slice(2).map((q) => q.queryKey.slice(0, 2))).toEqual([
      ["admin-users-summary", "total"], ["admin-users-summary", "active"],
      ["admin-users-summary", "inactive"], ["admin-users-summary", "month"],
    ]);
    await h.queries[1].queryFn();
    expect(h.request).toHaveBeenLastCalledWith("/roles");
  });

  it("keeps force logout and deactivation distinct without deleting client records", async () => {
    AdminUsersPage();
    await h.mutations[0].mutationFn({ action: "force-logout", userId: 7, userName: "example" });
    await h.mutations[0].mutationFn({ action: "delete", userId: 7, userName: "example" });
    expect(h.request.mock.calls).toEqual([
      ["/admin-users/7/force-logout", { method: "POST" }],
      ["/admin-users/7", { method: "DELETE" }],
    ]);
    h.mutations[0].onSuccess({}, { action: "delete", userId: 7, userName: "example" });
    expect(h.invalidate.mock.calls.map(([q]) => q.queryKey)).toEqual([
      ["admin-users"], ["admin-users-summary"],
    ]);
  });

  it("sends only editable profile/role/state fields when updating an Admin", async () => {
    h.states[11] = {
      id: 7, username: "unchanged", password: "unused", display_name: " Example ",
      email: " ", role_id: "3", is_active: false,
    };
    AdminUsersPage();
    await h.mutations[1].mutationFn();
    expect(h.request).toHaveBeenCalledWith("/admin-users/7", {
      method: "PATCH", body: JSON.stringify({
        display_name: "Example", email: null, role_id: 3, is_active: false,
      }),
    });
  });

  it("rejects an incomplete create form before sending a write", async () => {
    AdminUsersPage();
    await expect(h.mutations[1].mutationFn()).rejects.toThrow();
    expect(h.request).not.toHaveBeenCalled();
  });

  it("normalizes a create form while keeping the credential separate from PATCH fields", async () => {
    const form = {
      username: " example ", password: ["Unit", "Only", "12345!"].join(""),
      display_name: " Example ", email: " ", role_id: "3", is_active: true,
    };
    h.states[11] = form;
    AdminUsersPage();
    await h.mutations[1].mutationFn();
    expect(h.request).toHaveBeenCalledWith("/admin-users", {
      method: "POST", body: JSON.stringify({
        username: "example", password: form.password, display_name: "Example",
        email: null, role_id: 3, is_active: true,
      }),
    });
  });

  it("keeps credential reset on its dedicated endpoint without copying its legacy value", async () => {
    AdminUsersPage();
    await h.mutations[0].mutationFn({ action: "reset-password", userId: 7, userName: "example" });
    const [path, init] = h.request.mock.calls[0];
    expect(path).toBe("/admin-users/7/reset-password");
    expect(init.method).toBe("POST");
    expect(Object.keys(JSON.parse(init.body))).toEqual(["new_password"]);
  });
});

describe("App user batch boundaries", () => {
  function setup() {
    h.states[10] = " review ";
    AppUsersPage();
    return h.mutations[0];
  }
  it("waits for all five writes before starting the next chunk", async () => {
    const releases: (() => void)[] = [];
    let second!: () => void, third!: () => void;
    const secondStarted = new Promise<void>((resolve) => { second = resolve; });
    const thirdStarted = new Promise<void>((resolve) => { third = resolve; });
    h.request.mockImplementation(() => new Promise<void>((resolve) => {
      releases.push(resolve);
      if (releases.length === 6) second();
      if (releases.length === 11) third();
    }));
    const pending = setup().mutationFn({ action: "ban", userIds: Array.from({ length: 11 }, (_, i) => i + 1) });
    expect(h.request).toHaveBeenCalledTimes(5);
    releases.slice(0, 4).forEach((release) => release());
    await Promise.resolve();
    expect(h.request).toHaveBeenCalledTimes(5);
    releases[4]();
    await secondStarted;
    expect(h.request).toHaveBeenCalledTimes(10);
    releases.slice(5, 10).forEach((release) => release());
    await thirdStarted;
    expect(h.request).toHaveBeenCalledTimes(11);
    releases[10]();
    await pending;
    expect(h.request.mock.calls.every(([path, init]) =>
      /^\/app-users\/\d+\/ban$/.test(path) &&
      init.method === "POST" && init.body === JSON.stringify({ reason: "review" }))).toBe(true);
    h.mutations[0].onSuccess(undefined, { action: "ban", userIds: [1, 2] });
    expect(h.invalidate.mock.calls.map(([q]) => q.queryKey)).toEqual([
      ["app-users"], ["app-users-summary"],
    ]);
  });

  it("stops later chunks after a rejected write without claiming earlier writes rolled back", async () => {
    const error = new Error("one write rejected");
    h.request.mockRejectedValueOnce(error);
    const mutation = setup();
    await expect(mutation.mutationFn({ action: "unban", userIds: [1, 2, 3, 4, 5, 6] })).rejects.toBe(error);
    expect(h.request).toHaveBeenCalledTimes(5);
    expect(h.request.mock.calls.every(([, init]) => init.body === undefined)).toBe(true);
    mutation.onError(error);
    expect(h.invalidate).not.toHaveBeenCalled();
  });
});

describe("role and audit page contracts", () => {
  it("disables role reads and redirects non-super-admin users after bootstrap", () => {
    h.auth.role.name = "admin";
    RolesPage();
    expect(h.queries.map((q) => q.enabled)).toEqual([false, false]);
    h.effects[0]();
    expect(h.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("waits for role invalidation before discarding only that role's edit overlay", async () => {
    RolesPage();
    await h.mutations[0].mutationFn({ roleId: 3, permissionIds: [9, 2] });
    expect(h.request).toHaveBeenCalledWith("/roles/3/permissions", {
      method: "PUT", body: JSON.stringify({ permission_ids: [9, 2] }),
    });
    let release!: () => void;
    h.invalidate.mockReturnValueOnce(new Promise<void>((resolve) => { release = resolve; }));
    const pending = h.mutations[0].onSuccess({}, { roleId: 3 });
    expect(h.setters[1]).not.toHaveBeenCalled();
    release();
    await pending;
    const update = h.setters[1].mock.calls[0][0] as (value: Record<number, number[]>) => Record<number, number[]>;
    expect(update({ 3: [9, 2], 4: [5] })).toEqual({ 4: [5] });
    expect(h.invalidate).toHaveBeenCalledWith({ queryKey: ["roles"] });
  });

  it("uses audit aliases and committed keyword rather than input draft", async () => {
    h.states = [{ keyword: "draft", debouncedKeyword: "committed", severity: "critical",
      status: "failed", action: "role.update_permissions", resourceType: "role", dateFrom: "", dateTo: "" }, 3, null];
    AuditLogsPage();
    await h.queries[0].queryFn();
    expect(h.toQuery).toHaveBeenCalledWith({
      page: 3, pageSize: 20, severity: "critical", status: "failed",
      action: "role.update_permissions", resourceType: "role", keyword: "committed",
    });
    expect(h.request).toHaveBeenCalledWith("/audit-logs?fixture");
  });

  it("scopes audit detail by ID and disables it when the drawer is closed", async () => {
    AuditLogDrawer({ detailId: null, onClose: vi.fn() });
    expect(h.queries[0].enabled).toBe(false);
    AuditLogDrawer({ detailId: 17, onClose: vi.fn() });
    expect(h.queries[1].queryKey).toEqual(["audit-logs", "detail", 17]);
    expect(h.queries[1].enabled).toBe(true);
    await h.queries[1].queryFn();
    expect(h.request).toHaveBeenCalledWith("/audit-logs/17");
  });
});
