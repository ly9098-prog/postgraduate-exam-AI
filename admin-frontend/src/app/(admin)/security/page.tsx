"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Check, CheckCircle2, Copy, KeyRound, ShieldCheck, ShieldOff } from "lucide-react";
import { apiRequest } from "@/lib/api/client";
import type { MeResponse, TwoFactorConfirmResponse, TwoFactorSetupResponse } from "@/lib/api/types";
import { useAuthStore } from "@/lib/auth/auth-store";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    void navigator.clipboard.writeText(text);
  }
}

export default function SecurityPage() {
  const logout = useAuthStore((state) => state.logout);

  // ── status ──
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [statusError, setStatusError] = useState("");

  // ── enable flow ──
  const [setup, setSetup] = useState<TwoFactorSetupResponse | null>(null);
  const [enableCode, setEnableCode] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  // ── disable flow ──
  const [disableCode, setDisableCode] = useState("");
  const [disableBusy, setDisableBusy] = useState(false);
  const [disableError, setDisableError] = useState("");

  const loadStatus = useCallback(async () => {
    try {
      const me = await apiRequest<MeResponse>("/auth/me");
      setEnabled(Boolean(me.two_factor_enabled));
      setStatusError("");
    } catch {
      setStatusError("无法读取安全状态");
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  async function startSetup() {
    setBusy(true);
    setError("");
    setBackupCodes(null);
    try {
      const res = await apiRequest<TwoFactorSetupResponse>("/auth/2fa/setup");
      setSetup(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "初始化失败");
    } finally {
      setBusy(false);
    }
  }

  async function confirmEnable() {
    setBusy(true);
    setError("");
    try {
      const res = await apiRequest<TwoFactorConfirmResponse>("/auth/2fa/confirm", {
        method: "POST",
        body: JSON.stringify({ code: enableCode }),
      });
      setBackupCodes(res.backup_codes);
      setEnableCode("");
      await loadStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "验证码错误");
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setDisableBusy(true);
    setDisableError("");
    try {
      await apiRequest<{ status: string }>("/auth/2fa/disable", {
        method: "POST",
        body: JSON.stringify({ code: disableCode }),
      });
      setDisableCode("");
      setSetup(null);
      setBackupCodes(null);
      await loadStatus();
    } catch (e) {
      setDisableError(e instanceof Error ? e.message : "验证码错误");
    } finally {
      setDisableBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="font-display text-3xl font-bold text-[var(--ink)]">安全设置</h1>
        <p className="mt-1 text-sm text-[var(--color-text-secondary)]">两步验证（TOTP）与登录安全</p>
      </div>

      {statusError ? (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--color-danger)] bg-[var(--color-danger-light)] px-4 py-3 text-sm font-semibold text-[var(--color-danger)]">
          <AlertCircle className="h-4 w-4" />
          {statusError}
        </div>
      ) : null}

      {enabled === null ? (
        <Card>
          <CardContent>
            <p className="py-10 text-center text-sm text-[var(--color-text-hint)]">加载中…</p>
          </CardContent>
        </Card>
      ) : enabled ? (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-emerald-600" />
              <span className="font-display text-lg font-bold text-[var(--ink)]">两步验证已启用</span>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            <p className="text-sm text-[var(--color-text-secondary)]">
              登录时需要输入身份验证器 App 生成的 6 位动态验证码。
            </p>

            <div className="rounded-2xl border border-[var(--color-border)] p-5">
              <h3 className="mb-2 text-sm font-bold text-[var(--ink)]">关闭两步验证</h3>
              <p className="mb-3 text-xs text-[var(--color-text-hint)]">
                需要输入当前动态验证码或一次性的备份码。
              </p>
              <div className="flex flex-wrap items-center gap-3">
                <Input
                  value={disableCode}
                  onChange={(e) => setDisableCode(e.target.value)}
                  placeholder="验证码 / 备份码"
                  maxLength={16}
                  className="w-52"
                />
                <Button
                  variant="danger"
                  disabled={disableBusy || !disableCode}
                  onClick={disable}
                >
                  <ShieldOff className="h-4 w-4" />
                  {disableBusy ? "处理中…" : "关闭"}
                </Button>
              </div>
              {disableError ? (
                <p className="mt-2 flex items-center gap-1 text-sm font-semibold text-[var(--color-danger)]">
                  <AlertCircle className="h-4 w-4" />
                  {disableError}
                </p>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <KeyRound className="h-5 w-5 text-[var(--color-primary)]" />
              <span className="font-display text-lg font-bold text-[var(--ink)]">启用两步验证</span>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {backupCodes ? (
              <div className="rounded-2xl border border-amber-300 bg-amber-50 p-5">
                <div className="mb-2 flex items-center gap-2 text-amber-800">
                  <CheckCircle2 className="h-5 w-5" />
                  <h3 className="font-bold">保存你的备份码</h3>
                </div>
                <p className="mb-3 text-xs text-amber-700">
                  备份码仅显示这一次，请妥善保管。每个备份码只能使用一次。
                </p>
                <div className="grid grid-cols-2 gap-2 font-mono text-sm font-bold text-amber-900 sm:grid-cols-4">
                  {backupCodes.map((code) => (
                    <div key={code} className="rounded-lg bg-white px-2 py-1.5 text-center border border-amber-200">
                      {code}
                    </div>
                  ))}
                </div>
                <Button
                  className="mt-4"
                  size="sm"
                  onClick={() => {
                    copyText(backupCodes.join("\n"));
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                  }}
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copied ? "已复制" : "复制全部备份码"}
                </Button>
              </div>
            ) : setup ? (
              <>
                <div className="rounded-2xl border border-[var(--color-border)] p-5">
                  <h3 className="mb-2 text-sm font-bold text-[var(--ink)]">第一步：添加密钥到身份验证器</h3>
                  <p className="mb-3 text-xs text-[var(--color-text-hint)]">
                    在 Google Authenticator / Microsoft Authenticator 等 App 中「手动添加账号」，输入下方密钥。
                  </p>
                  <div className="flex flex-wrap items-center gap-3">
                    <code className="rounded-lg bg-[var(--color-surface)] px-4 py-2 font-mono text-lg font-bold tracking-wider text-[var(--ink)]">
                      {setup.secret}
                    </code>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => {
                        copyText(setup.secret);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                      }}
                    >
                      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                      {copied ? "已复制" : "复制密钥"}
                    </Button>
                  </div>
                  <details className="mt-3 text-xs text-[var(--color-text-hint)]">
                    <summary className="cursor-pointer font-medium">高级：显示 otpauth URI</summary>
                    <code className="mt-2 block break-all rounded-lg bg-[var(--color-surface)] px-3 py-2">
                      {setup.otpauth_uri}
                    </code>
                  </details>
                </div>

                <div className="rounded-2xl border border-[var(--color-border)] p-5">
                  <h3 className="mb-2 text-sm font-bold text-[var(--ink)]">第二步：输入动态验证码确认</h3>
                  <p className="mb-3 text-xs text-[var(--color-text-hint)]">
                    在身份验证器 App 中输入刚生成的 6 位验证码。
                  </p>
                  <div className="flex flex-wrap items-center gap-3">
                    <Input
                      value={enableCode}
                      onChange={(e) => setEnableCode(e.target.value)}
                      placeholder="6 位验证码"
                      inputMode="numeric"
                      maxLength={6}
                      className="w-52"
                    />
                    <Button disabled={busy || enableCode.length !== 6} onClick={confirmEnable}>
                      {busy ? "确认中…" : "确认并启用"}
                    </Button>
                  </div>
                </div>
              </>
            ) : (
              <div>
                <p className="mb-4 text-sm text-[var(--color-text-secondary)]">
                  两步验证开启后，登录需要「密码 + 动态验证码」双重校验，显著降低账号被盗风险。
                </p>
                <Button onClick={startSetup} disabled={busy}>
                  <ShieldCheck className="h-4 w-4" />
                  {busy ? "初始化中…" : "开始绑定"}
                </Button>
              </div>
            )}

            {error ? (
              <p className="flex items-center gap-1 text-sm font-semibold text-[var(--color-danger)]">
                <AlertCircle className="h-4 w-4" />
                {error}
              </p>
            ) : null}
          </CardContent>
        </Card>
      )}

      <p className="text-xs text-[var(--color-text-hint)]">
        忘记验证码或丢失身份验证器时，可使用一次性备份码关闭两步验证后重新绑定。
      </p>
      <button
        type="button"
        onClick={() => void logout()}
        className="text-xs font-medium text-[var(--color-text-hint)] underline-offset-2 hover:underline"
      >
        退出登录
      </button>
    </div>
  );
}
