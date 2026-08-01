"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { AlertCircle, ArrowRight, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AdminFooter } from "@/components/layout/admin-footer";
import { useAuthStore } from "@/lib/auth/auth-store";
import { safeInternalRedirect } from "@/lib/safe-redirect";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const login = useAuthStore((state) => state.login);
  const verifyTwoFactor = useAuthStore((state) => state.verifyTwoFactor);
  const cancelTwoFactor = useAuthStore((state) => state.cancelTwoFactor);
  const needsTwoFactor = useAuthStore((state) => state.needsTwoFactor);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [verifying, setVerifying] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (needsTwoFactor) {
      setVerifying(true);
      try {
        await verifyTwoFactor(twoFactorCode);
        router.replace(safeInternalRedirect(searchParams.get("next")));
      } catch {
        setError("验证码错误，请重试");
      } finally {
        setVerifying(false);
      }
      return;
    }
    setLoading(true);
    try {
      await login(username, password);
      // If the account has 2FA, the store flips to the code step instead of
      // authenticating; only redirect once the session is fully established.
      if (!useAuthStore.getState().needsTwoFactor) {
        router.replace(safeInternalRedirect(searchParams.get("next")));
      }
    } catch {
      setError("用户名或密码错误");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <main className="grid flex-1 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="blueprint-panel hidden items-end p-12 lg:flex">
          <div className="relative z-10 max-w-2xl animate-rise-in">
            <p className="mb-5 font-mono text-xs uppercase tracking-[0.34em] text-[var(--color-primary-dark)]">MemoGrad Control Plane</p>
            <h1 className="text-balance font-display text-6xl font-black leading-[0.96] text-[var(--ink)]">
              把题库、审核与用户运营收束到一张蓝图里。
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-8 text-[var(--color-text-secondary)]">
              后台只消费既有 Admin API，所有高风险动作保留人工确认，AI 仍作为辅助而不是自动决策者。
            </p>
          </div>
        </section>

        <section className="flex items-center justify-center px-6 py-6">
          <div className="w-full max-w-md animate-rise-in rounded-[2rem] border border-[var(--color-border)] bg-[rgba(255,253,248,0.88)] p-8 shadow-[var(--shadow-card)] backdrop-blur-xl">
            <div className="mb-8">
              <div className="mb-5 grid h-14 w-14 place-items-center rounded-2xl border border-[var(--color-primary)] bg-[var(--color-primary)] text-white shadow-[var(--shadow-crisp)]">
                <ShieldCheck className="h-7 w-7" />
              </div>
              <p className="font-mono text-xs uppercase tracking-[0.28em] text-[var(--color-text-hint)]">Admin Login</p>
              <h2 className="mt-2 font-display text-4xl font-bold text-[var(--ink)]">
                {needsTwoFactor ? "二次验证" : "进入后台"}
              </h2>
              {needsTwoFactor ? (
                <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
                  输入身份验证器 App 中的 6 位动态验证码
                </p>
              ) : null}
            </div>

            <form className="space-y-5" onSubmit={handleSubmit}>
              {needsTwoFactor ? (
                <>
                  <label className="block space-y-2">
                    <span className="text-sm font-semibold text-[var(--color-text-secondary)]">动态验证码</span>
                    <Input
                      value={twoFactorCode}
                      onChange={(event) => setTwoFactorCode(event.target.value)}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={10}
                      placeholder="6 位验证码"
                      required
                      autoFocus
                    />
                  </label>
                  {error ? (
                    <div className="flex items-center gap-2 rounded-2xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm font-semibold text-[var(--color-danger)]">
                      <AlertCircle className="h-4 w-4" />
                      {error}
                    </div>
                  ) : null}
                  <Button className="h-12 w-full" disabled={verifying || !twoFactorCode}>
                    {verifying ? "正在校验" : "验证并登录"}
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                  <button
                    type="button"
                    onClick={() => {
                      cancelTwoFactor();
                      setTwoFactorCode("");
                      setError("");
                    }}
                    className="w-full text-center text-sm font-medium text-[var(--color-text-hint)] hover:text-[var(--color-text-secondary)]"
                  >
                    返回重新登录
                  </button>
                </>
              ) : (
                <>
                  <label className="block space-y-2">
                    <span className="text-sm font-semibold text-[var(--color-text-secondary)]">用户名</span>
                    <Input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
                  </label>
                  <label className="block space-y-2">
                    <span className="text-sm font-semibold text-[var(--color-text-secondary)]">密码</span>
                    <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
                  </label>
                  {error ? (
                    <div className="flex items-center gap-2 rounded-2xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm font-semibold text-[var(--color-danger)]">
                      <AlertCircle className="h-4 w-4" />
                      {error}
                    </div>
                  ) : null}
                  <Button className="h-12 w-full" disabled={loading}>
                    {loading ? "正在校验" : "登录"}
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </>
              )}
            </form>
          </div>
        </section>
      </main>
      <AdminFooter />
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
