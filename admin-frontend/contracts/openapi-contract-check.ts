/**
 * Compile-only assertions between FastAPI-generated OpenAPI types and the
 * hand-written admin types that are still consumed by existing pages.
 *
 * CI generates ../.contract/openapi.ts immediately before running tsc.
 */
import type { paths } from "../.contract/openapi";
import type {
  DashboardOverview,
  LoginResponse,
  SystemHealthResponse,
  TaskDiagnosticsResponse,
  TaskTraceResponse,
} from "../src/lib/api/types";

type HttpMethod = "get" | "post" | "put" | "patch" | "delete";
type JsonContent<T> = T extends { content: infer C }
  ? C extends { "application/json": infer Body }
    ? Body
    : never
  : never;
type SuccessResponse<Operation> = Operation extends { responses: infer R }
  ? R extends Record<PropertyKey, unknown>
    ? 200 extends keyof R
      ? JsonContent<R[200]>
      : 201 extends keyof R
        ? JsonContent<R[201]>
        : never
    : never
  : never;
type ResponseAt<Path extends keyof paths, Method extends HttpMethod> =
  Method extends keyof paths[Path]
    ? SuccessResponse<NonNullable<paths[Path][Method]>>
    : never;

type Assert<T extends true> = T;
type HasAllFrontendKeys<Backend, Frontend> = Exclude<keyof Frontend, keyof Backend> extends never
  ? true
  : false;

// These checks intentionally focus on response *shape availability*.  Existing
// manual types may be stricter than Pydantic's OpenAPI required/optional flags,
// but every field read by the UI must continue to exist in the backend schema.
type _Login = Assert<HasAllFrontendKeys<
  ResponseAt<"/api/admin/v1/auth/login", "post">,
  LoginResponse
>>;
type _Dashboard = Assert<HasAllFrontendKeys<
  ResponseAt<"/api/admin/v1/dashboard/overview", "get">,
  DashboardOverview
>>;
type _SystemHealth = Assert<HasAllFrontendKeys<
  ResponseAt<"/api/admin/v1/system/health", "get">,
  SystemHealthResponse
>>;
type _TaskDiagnostics = Assert<HasAllFrontendKeys<
  ResponseAt<"/api/admin/v1/tasks/diagnostics", "get">,
  TaskDiagnosticsResponse
>>;
type _TaskTrace = Assert<HasAllFrontendKeys<
  ResponseAt<"/api/admin/v1/tasks/trace/{trace_id}", "get">,
  TaskTraceResponse
>>;

export {};
