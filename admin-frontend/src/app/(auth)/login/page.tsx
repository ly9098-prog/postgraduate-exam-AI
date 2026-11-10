"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  ClipboardCheck,
  Database,
  Eye,
  EyeOff,
  Loader2,
  LockKeyhole,
  ScanText,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { AdminFooter } from "@/components/layout/admin-footer";
import { useAuthStore } from "@/lib/auth/auth-store";
import { safeInternalRedirect } from "@/lib/safe-redirect";

const capabilities = [
  {
    index: "01",
    title: "导入与确认",
    detail: "OCR 与 AI 识别结果经人工确认入库",
  },
  {
    index: "02",
    title: "审计与追溯",
    detail: "关键操作全量留痕，可回查追责",
  },
  {
    index: "03",
    title: "角色与隔离",
    detail: "最小授权，后台身份完全隔离",
  },
];

function BrandMark({ size = 36 }: { size?: 36 | 44 }) {
  const box = size === 44 ? "h-11 w-11" : "h-9 w-9";
  return (
    <span
      aria-hidden
      className={`relative block shrink-0 ${box} overflow-hidden rounded-[11px] bg-[linear-gradient(145deg,#2d5068_0%,#4a6f8a_58%,#63849b_100%)] shadow-[inset_0_1px_0_rgba(255,255,255,0.14)] ring-1 ring-inset ring-white/[0.14]`}
    >
      <span
        className="absolute left-1/2 top-1/2 block w-[55%] -translate-x-1/2 -translate-y-1/2"
        style={{ aspectRatio: "5 / 3" }}
      >
        <svg viewBox="0 0 50 30" className="h-full w-full">
          <polyline
            points="2,24 15,12 27,19 48,3"
            fill="none"
            stroke="rgba(255,255,255,0.94)"
            strokeWidth="3.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="48" cy="3" r="4.2" fill="#e8f0f5" />
        </svg>
      </span>
    </span>
  );
}

function BrandLockup({ tone = "dark" }: { tone?: "dark" | "light" }) {
  const onDark = tone === "dark";
  return (
    <div className="flex items-center gap-3">
      <BrandMark />
      <span className="leading-tight">
        <span
          className={`block text-[15px] font-semibold tracking-[0.01em] ${
            onDark ? "text-white" : "text-[#172033]"
          }`}
        >
          MemoGrad
        </span>
        <span
          className={`mt-0.5 block text-[10px] font-medium uppercase tracking-[0.22em] ${
            onDark ? "text-[#94a3b8]" : "text-[#64748b]"
          }`}
        >
          Control Plane
        </span>
      </span>
    </div>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const login = useAuthStore((state) => state.login);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const hasError = Boolean(error);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      router.replace(safeInternalRedirect(searchParams.get("next")));
    } catch {
      setError("用户名或密码错误");
    } finally {
      setLoading(false);
    }
  }

  const fieldShell = hasError ? "auth-field-shell-error" : "";
  const fieldClassName =
    "auth-input h-full w-full min-w-0 flex-1 bg-transparent px-3.5 text-[#172033] caret-[#4a6f8a] outline-none placeholder:font-normal placeholder:text-[#9aa5ab]";

  return (
    <div className="auth-surface min-h-dvh bg-[#faf8f5] text-[#1e2b38] antialiased lg:grid lg:grid-cols-[5fr_7fr]">
      <section className="auth-ambient relative hidden overflow-hidden bg-[var(--auth-ink)] lg:flex lg:flex-col lg:justify-between lg:px-12 lg:pt-10 lg:pb-6 xl:px-16 xl:pt-12 xl:pb-6">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          {/* Deep tones derived from the admin ink and primary-dark tokens. */}
          <div className="absolute inset-0 bg-[linear-gradient(158deg,#111d26_0%,#182c3a_42%,#142733_72%,#0e1b24_100%)]" />
          {/* The main light uses the exact admin primary colour: #4a6f8a. */}
          <div className="auth-aurora auth-aurora-primary absolute -left-[22%] top-[5%] h-[72%] w-[112%] rounded-[50%] bg-[radial-gradient(ellipse_at_center,rgba(74,111,138,0.42)_0%,rgba(74,111,138,0.22)_32%,rgba(45,80,104,0.08)_52%,rgba(45,80,104,0)_74%)] blur-[42px]" />
          {/* A trace of the admin's warm sand token softens the distant edge. */}
          <div className="auth-aurora auth-aurora-secondary absolute -right-[42%] top-[12%] h-[70%] w-[105%] rounded-[50%] bg-[radial-gradient(ellipse_at_center,rgba(196,154,107,0.13)_0%,rgba(196,154,107,0.07)_38%,rgba(196,154,107,0)_72%)] blur-[60px]" />
          <div className="absolute -bottom-[18%] -left-[20%] h-[54%] w-[108%] rounded-[50%] bg-[radial-gradient(ellipse_at_center,rgba(45,80,104,0.3)_0%,rgba(45,80,104,0.12)_42%,rgba(30,43,56,0)_74%)] blur-[50px]" />
          <div className="absolute inset-0 bg-[radial-gradient(52%_44%_at_48%_39%,rgba(232,240,245,0.07)_0%,rgba(232,240,245,0)_72%)]" />
          {/* A fine technical grid, masked into the light rather than laid on top. */}
          <svg className="absolute inset-0 h-full w-full opacity-[0.16]">
            <defs>
              <pattern id="auth-fine-grid" width="44" height="44" patternUnits="userSpaceOnUse">
                <path d="M 44 0 L 0 0 0 44" fill="none" stroke="rgba(232,240,245,0.12)" strokeWidth="1" />
              </pattern>
              <radialGradient id="auth-grid-fade" cx="40%" cy="42%" r="72%">
                <stop offset="0%" stopColor="white" stopOpacity="0.9" />
                <stop offset="64%" stopColor="white" stopOpacity="0.25" />
                <stop offset="100%" stopColor="white" stopOpacity="0" />
              </radialGradient>
              <mask id="auth-grid-mask">
                <rect width="100%" height="100%" fill="url(#auth-grid-fade)" />
              </mask>
            </defs>
            <rect width="100%" height="100%" fill="url(#auth-fine-grid)" mask="url(#auth-grid-mask)" />
          </svg>
          <svg
            className="absolute inset-0 h-full w-full"
            viewBox="0 0 560 900"
            preserveAspectRatio="xMidYMid slice"
          >
            <defs>
              <radialGradient id="auth-glow-primary">
                <stop offset="0%" stopColor="#f4f8fa" stopOpacity="0.68" />
                <stop offset="22%" stopColor="#c6d5df" stopOpacity="0.34" />
                <stop offset="52%" stopColor="#8faabc" stopOpacity="0.13" />
                <stop offset="100%" stopColor="#4a6f8a" stopOpacity="0" />
              </radialGradient>
              <radialGradient id="auth-glow-primary-soft">
                <stop offset="0%" stopColor="#e8f0f5" stopOpacity="0.54" />
                <stop offset="28%" stopColor="#c6d5df" stopOpacity="0.26" />
                <stop offset="62%" stopColor="#8faabc" stopOpacity="0.09" />
                <stop offset="100%" stopColor="#4a6f8a" stopOpacity="0" />
              </radialGradient>
              <radialGradient id="auth-glow-sand">
                <stop offset="0%" stopColor="#eadbc8" stopOpacity="0.42" />
                <stop offset="28%" stopColor="#c49a6b" stopOpacity="0.18" />
                <stop offset="62%" stopColor="#9f7950" stopOpacity="0.06" />
                <stop offset="100%" stopColor="#c49a6b" stopOpacity="0" />
              </radialGradient>
              <linearGradient id="auth-flow" gradientUnits="userSpaceOnUse" x1="80" y1="786" x2="530" y2="468">
                <stop offset="0%" stopColor="#c49a6b" stopOpacity="0.04" />
                <stop offset="38%" stopColor="#4a6f8a" stopOpacity="0.2" />
                <stop offset="76%" stopColor="#9fb9ca" stopOpacity="0.36" />
                <stop offset="100%" stopColor="#e8f0f5" stopOpacity="0.18" />
              </linearGradient>
              <linearGradient id="auth-flow-faint" gradientUnits="userSpaceOnUse" x1="80" y1="786" x2="24" y2="878">
                <stop offset="0%" stopColor="#c49a6b" stopOpacity="0.16" />
                <stop offset="100%" stopColor="#4a6f8a" stopOpacity="0.03" />
              </linearGradient>
            </defs>
            <g fill="none" strokeWidth="1" strokeLinecap="round">
              <path
                d="M 80 786 C 168 750, 242 702, 310 650 C 382 596, 448 536, 494 496 C 510 482, 522 474, 530 468"
                stroke="url(#auth-flow)"
              />
              <path d="M 530 468 C 548 454, 558 445, 574 438" stroke="url(#auth-flow)" strokeOpacity="0.7" />
              <path d="M 80 786 C 58 820, 40 848, 24 878" stroke="url(#auth-flow-faint)" strokeOpacity="0.5" />
              <path d="M 420 216 A 254 254 0 0 1 574 558" stroke="rgba(196,154,107,0.1)" />
              <path d="M 478 308 A 164 164 0 0 1 574 558" stroke="rgba(232,240,245,0.1)" />
              <circle cx="530" cy="468" r="12" stroke="rgba(232,240,245,0.16)" />
              <path
                className="auth-flow-line"
                d="M 80 786 C 168 750, 242 702, 310 650 C 382 596, 448 536, 494 496 C 510 482, 522 474, 530 468"
                stroke="#c6d5df"
                strokeOpacity="0.44"
                strokeWidth="1.25"
                strokeDasharray="2 18"
              />
              <g className="auth-orbit auth-orbit-slow">
                <circle cx="530" cy="468" r="64" stroke="rgba(198,213,223,0.14)" strokeDasharray="1 12" />
                <circle cx="530" cy="404" r="2.4" fill="#dce7ed" stroke="none" opacity="0.72" />
              </g>
              <g className="auth-orbit auth-orbit-reverse">
                <path d="M 530 376 A 92 92 0 0 1 622 468" stroke="rgba(196,154,107,0.18)" />
                <circle cx="530" cy="376" r="1.8" fill="#d8bfa3" stroke="none" opacity="0.66" />
              </g>
              <circle className="auth-beacon" cx="530" cy="468" r="17" stroke="rgba(232,240,245,0.28)" />
            </g>
            <g className="max-xl:opacity-50">
              <circle cx="530" cy="468" r="48" fill="url(#auth-glow-primary)" />
              <circle cx="80" cy="786" r="50" fill="url(#auth-glow-primary-soft)" />
            </g>
            <g className="max-xl:hidden">
              <circle cx="452" cy="186" r="32" fill="url(#auth-glow-sand)" />
              <circle cx="548" cy="640" r="18" fill="url(#auth-glow-primary-soft)" />
              <circle cx="186" cy="602" r="15" fill="url(#auth-glow-sand)" />
            </g>
            <g>
              <circle cx="530" cy="468" r="4.2" fill="#e8f0f5" opacity="0.94" />
              <circle cx="80" cy="786" r="3.8" fill="#c6d5df" opacity="0.88" />
              <circle cx="548" cy="640" r="2.2" fill="#d8e3ea" opacity="0.62" />
            </g>
            <g className="max-xl:hidden">
              <circle cx="452" cy="186" r="2.8" fill="#d8bfa3" opacity="0.86" />
              <circle cx="186" cy="602" r="2" fill="#c49a6b" opacity="0.5" />
            </g>
            <g fill="#c6d5df" className="max-xl:hidden">
              <circle cx="500" cy="240" r="1.3" opacity="0.36" />
              <circle cx="60" cy="300" r="1.2" opacity="0.28" />
            </g>
          </svg>
          <div className="auth-particles absolute inset-0">
            <span className="auth-particle auth-particle-a" />
            <span className="auth-particle auth-particle-b" />
            <span className="auth-particle auth-particle-c" />
            <span className="auth-particle auth-particle-d" />
            <span className="auth-particle auth-particle-e" />
          </div>
          <div className="absolute inset-0 shadow-[inset_0_0_150px_rgba(3,8,14,0.55)]" />
          {/* Soft seam: the panel's right edge crossfades into the warm canvas. */}
          <div className="auth-seam-fade" />
          <div className="auth-noise absolute inset-0" />
        </div>

        <div className="relative z-10">
          <BrandLockup />
        </div>

        <div className="auth-copy-enter auth-story-copy relative z-10 my-auto w-full max-w-[36rem] py-10 xl:py-12">
          <div className="flex items-center gap-3">
            <span aria-hidden className="h-px w-7 bg-[#c49a6b]/80" />
            <p className="text-[9px] font-medium uppercase tracking-[0.2em] text-[#a9c0d0] xl:text-[10px]">
              Question bank · control system
            </p>
          </div>

          <h1 className="auth-story-title mt-6 text-[40px] font-medium leading-[1.18] tracking-[-0.025em] text-white xl:text-[52px] xl:leading-[1.16]">
            <span className="block whitespace-nowrap">让每一道题，</span>
            <span className="mt-1 block whitespace-nowrap">
              都有<span className="auth-headline-accent relative inline-block text-[#d7e3ea]">迹可循</span>。
            </span>
          </h1>
          <p className="auth-story-description mt-6 max-w-[29rem] text-pretty text-[14px] font-normal leading-7 text-[#9aadb9]">
            从题库导入、内容审核到用户运营，把分散的工作收束成一条清晰路径。
            <span className="auth-story-description-secondary mt-1 block text-[#7f96a6]">
              AI 提供辅助，关键决策始终由人确认。
            </span>
          </p>

          <div
            className="auth-blueprint auth-product-scene relative mt-8 xl:mt-9"
            aria-label="题库处理工作台预览：智能识别、人工审核、确认入库"
          >
            <div className="auth-product-window">
              <div className="auth-product-topbar">
                <div className="auth-product-brand">
                  <span className="auth-product-appmark">
                    <Database aria-hidden className="h-3.5 w-3.5" strokeWidth={1.7} />
                  </span>
                  <span>
                    <strong>内容工作台</strong>
                    <small>QUESTION OPERATIONS</small>
                  </span>
                </div>
                <span className="auth-product-status">
                  <i aria-hidden />
                  Human in the loop
                </span>
              </div>

              <div className="auth-product-body">
                <div className="auth-product-rail" aria-hidden="true">
                  <span className="is-active"><ScanText />题库</span>
                  <span><ClipboardCheck />审核<i /></span>
                  <span><ShieldCheck />记录</span>
                </div>

                <div className="auth-product-main">
                  <div className="auth-product-heading">
                    <div>
                      <span>QUESTION LIFECYCLE</span>
                      <p>题目入库流程</p>
                    </div>
                    <span className="auth-product-preview">流程预览</span>
                  </div>

                  <div className="auth-product-flow">
                    <span className="auth-product-connector" aria-hidden />
                    <ol className="auth-product-steps">
                      <li>
                        <span className="auth-product-step-top">
                          <span className="auth-product-step-icon"><ScanText aria-hidden /></span>
                          <small>01</small>
                        </span>
                        <strong>智能识别</strong>
                        <span className="auth-product-step-sub">OCR / AI 解析</span>
                      </li>
                      <li className="is-review">
                        <span className="auth-product-step-top">
                          <span className="auth-product-step-icon"><ClipboardCheck aria-hidden /></span>
                          <small>02</small>
                        </span>
                        <strong>人工审核</strong>
                        <span className="auth-product-step-sub">关键内容确认</span>
                        <i className="auth-product-review-dot" aria-hidden />
                      </li>
                      <li>
                        <span className="auth-product-step-top">
                          <span className="auth-product-step-icon"><Database aria-hidden /></span>
                          <small>03</small>
                        </span>
                        <strong>确认入库</strong>
                        <span className="auth-product-step-sub">结构化题库资产</span>
                      </li>
                    </ol>
                  </div>

                  <div className="auth-product-audit">
                    <ShieldCheck aria-hidden />
                    <span>每一次关键操作，都有记录可回查</span>
                    <small>AUDIT READY</small>
                  </div>
                </div>
              </div>
            </div>

            <div className="auth-product-float" aria-hidden="true">
              <span><ShieldCheck /></span>
              <div>
                <strong>Human approval</strong>
                <small>AI 提供辅助，人来决策</small>
              </div>
            </div>
          </div>

          <dl className="auth-ledger relative z-10 mt-8 grid grid-cols-3 border-t border-white/[0.09] xl:mt-9">
            {capabilities.map((item, i) => (
              <div
                key={item.index}
                className={`flex flex-col gap-3 py-5 ${
                  i > 0 ? "border-l border-white/[0.09] pl-4 xl:pl-5" : "pr-3"
                }`}
              >
                <span className="auth-num text-[10px] font-medium tracking-[0.14em] text-[#a9c0d0]/90">
                  {item.index}
                </span>
                <div>
                  <dt className="text-[12.5px] font-medium leading-5 text-[#f3f6f8] xl:text-[13px]">{item.title}</dt>
                  <dd className="mt-1.5 text-[11px] leading-[1.65] text-[#8299a9] xl:text-[11.5px]">{item.detail}</dd>
                </div>
              </div>
            ))}
          </dl>
        </div>

        <div className="relative z-10 flex items-center gap-2 border-t border-white/[0.09] pt-4 text-xs text-[#6f8595]">
          <ShieldCheck aria-hidden className="h-3.5 w-3.5" strokeWidth={1.8} />
          内部系统 · 仅授权管理员访问
        </div>
      </section>

      <div className="auth-ambient relative flex min-h-dvh flex-col overflow-hidden bg-[#faf8f5]">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          {/* Warm ivory canvas matches the live admin workspace. */}
          <div className="absolute inset-0 bg-[linear-gradient(155deg,#fdfcf9_0%,#faf8f5_45%,#f2eee7_100%)]" />
          <div className="auth-right-breath absolute inset-0 bg-[radial-gradient(54%_48%_at_50%_44%,rgba(255,255,255,0.98)_0%,rgba(255,255,255,0.5)_48%,rgba(255,255,255,0)_78%)]" />
          {/* Muted primary and sand accents come from the admin palette. */}
          <div className="absolute inset-0 bg-[radial-gradient(52%_46%_at_0%_0%,rgba(74,111,138,0.1)_0%,rgba(74,111,138,0)_70%),radial-gradient(54%_48%_at_100%_0%,rgba(232,240,245,0.46)_0%,rgba(232,240,245,0)_72%),radial-gradient(64%_50%_at_100%_100%,rgba(196,154,107,0.1)_0%,rgba(196,154,107,0)_72%)]" />
          <svg className="absolute inset-0 h-full w-full opacity-[0.7]">
            <defs>
              <pattern id="auth-paper-grid" width="72" height="72" patternUnits="userSpaceOnUse">
                <path d="M 72 0 L 0 0 0 72" fill="none" stroke="rgba(100,116,139,0.07)" strokeWidth="1" />
              </pattern>
              <radialGradient id="auth-paper-fade" cx="50%" cy="44%" r="76%">
                <stop offset="0%" stopColor="white" stopOpacity="0.8" />
                <stop offset="58%" stopColor="white" stopOpacity="0.28" />
                <stop offset="100%" stopColor="white" stopOpacity="0" />
              </radialGradient>
              <mask id="auth-paper-mask">
                <rect width="100%" height="100%" fill="url(#auth-paper-fade)" />
              </mask>
            </defs>
            <rect width="100%" height="100%" fill="url(#auth-paper-grid)" mask="url(#auth-paper-mask)" />
          </svg>
          {/* Oversized geometry adds scale without competing with the controls. */}
          <svg
            className="absolute inset-0 h-full w-full"
            viewBox="0 0 842 900"
            preserveAspectRatio="xMidYMid slice"
          >
            <g fill="none" stroke="rgba(100,116,139,0.075)" strokeWidth="1">
              <circle cx="704" cy="408" r="182" />
              <circle cx="704" cy="408" r="292" />
              <circle cx="704" cy="408" r="404" />
            </g>
            <path
              d="M -40 748 C 150 700, 306 574, 408 402 C 474 292, 546 202, 676 152"
              fill="none"
              stroke="rgba(100,116,139,0.065)"
              strokeWidth="1"
            />
            <g stroke="rgba(100,116,139,0.1)" strokeWidth="1" fill="none">
              <path d="M 636 706 H 856" />
              <path d="M 660 706 v -5 M 708 706 v -5 M 756 706 v -5 M 804 706 v -5" />
              <path d="M 772 232 V 470" />
              <path d="M 758 340 h 28 M 772 326 v 28" stroke="rgba(74,111,138,0.16)" />
            </g>
          </svg>
          <div className="auth-noise absolute inset-0" />
        </div>

        <main
          aria-labelledby="login-heading"
          className="relative flex flex-1 items-center justify-center px-5 py-12 sm:px-8"
        >
          <div className="w-full max-w-[430px]">
            <div className="mb-8 lg:hidden">
              <BrandLockup tone="light" />
            </div>

            <div className="auth-card-stage relative isolate">
              <span
                aria-hidden
                className="pointer-events-none absolute -inset-x-14 -top-16 -bottom-20 rounded-[48px] bg-[radial-gradient(50%_46%_at_50%_50%,rgba(255,255,255,0.98)_0%,rgba(255,255,255,0.52)_48%,rgba(255,255,255,0)_76%),radial-gradient(78%_68%_at_50%_56%,rgba(74,111,138,0.12)_0%,rgba(74,111,138,0)_80%)]"
              />
              <span
                aria-hidden
                className="pointer-events-none absolute -bottom-9 left-1/2 h-14 w-[88%] -translate-x-1/2 rounded-[50%] bg-[radial-gradient(50%_50%_at_50%_50%,rgba(51,65,85,0.18)_0%,rgba(51,65,85,0)_74%)] blur-lg"
              />
              <span aria-hidden className="auth-card-layer auth-card-layer-back" />
              <span aria-hidden className="auth-card-layer auth-card-layer-front" />
              <div className="auth-card auth-card-enter relative z-10 overflow-hidden rounded-[24px] border border-white/90 bg-[linear-gradient(155deg,rgba(255,255,255,0.98)_0%,rgba(253,252,250,0.96)_58%,rgba(248,250,251,0.97)_100%)] shadow-[0_1px_2px_rgba(30,43,56,0.035),0_18px_36px_-22px_rgba(45,80,104,0.18),0_52px_90px_-48px_rgba(45,80,104,0.28)] backdrop-blur-2xl">
              <div className="auth-card-head relative border-b border-[#4a6f8a]/[0.08] px-7 pb-7 pt-7 sm:px-9 sm:pt-8">
                <div className="mb-7 flex items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <BrandMark size={44} />
                    <div className="leading-tight">
                      <p className="text-[15px] font-semibold tracking-[0.01em] text-[#263a49]">MemoGrad</p>
                      <p className="mt-1 text-[9px] font-semibold uppercase tracking-[0.2em] text-[#8a9ba9]">Admin Console</p>
                    </div>
                  </div>
                  <span className="auth-access-badge flex shrink-0 items-center gap-2 rounded-full border border-[#4a6f8a]/10 bg-white/60 px-3 py-1.5 text-[10px] font-medium tracking-[0.06em] text-[#647985] shadow-[0_1px_2px_rgba(30,43,56,0.025)]">
                    <span aria-hidden className="auth-access-dot h-1.5 w-1.5 rounded-full bg-[#4a6f8a]" />
                    内部系统
                  </span>
                </div>
                <h2 id="login-heading" className="text-[28px] font-semibold leading-9 tracking-[-0.035em] text-[#1e2b38]">
                  进入后台
                </h2>
                <p className="mt-2 text-[13.5px] font-normal leading-6 text-[#70818d]">
                  欢迎回来，使用管理员账号继续。
                </p>
              </div>

              <div className="px-7 pb-7 pt-7 sm:px-9 sm:pb-8">
                <form className="space-y-5" onSubmit={handleSubmit}>
                  <div>
                    <label htmlFor="username" className="mb-2 block text-[12.5px] font-medium text-[#334155]">
                      用户名
                    </label>
                    <div
                      className={`auth-field-control group relative flex h-[52px] items-center rounded-[12px] border transition-[border-color,background-color,box-shadow] duration-200 ${fieldShell}`}
                    >
                      <span aria-hidden className="auth-field-icon pointer-events-none ml-4 grid h-5 w-5 shrink-0 place-items-center">
                        <UserRound className="h-[17px] w-[17px]" strokeWidth={1.7} />
                      </span>
                      <input
                        id="username"
                        name="username"
                        className={fieldClassName}
                        value={username}
                        onChange={(event) => {
                          setUsername(event.target.value);
                          if (error) setError("");
                        }}
                        placeholder="请输入管理员账号"
                        autoComplete="username"
                        autoCapitalize="none"
                        spellCheck={false}
                        aria-invalid={hasError ? true : undefined}
                        aria-describedby={hasError ? "login-error" : undefined}
                        required
                      />
                    </div>
                  </div>

                  <div>
                    <label htmlFor="password" className="mb-2 block text-[12.5px] font-medium text-[#334155]">
                      密码
                    </label>
                    <div
                      className={`auth-field-control group relative flex h-[52px] items-center rounded-[12px] border transition-[border-color,background-color,box-shadow] duration-200 ${fieldShell}`}
                    >
                      <span aria-hidden className="auth-field-icon pointer-events-none ml-4 grid h-5 w-5 shrink-0 place-items-center">
                        <LockKeyhole className="h-[17px] w-[17px]" strokeWidth={1.7} />
                      </span>
                      <input
                        id="password"
                        name="password"
                        type={showPassword ? "text" : "password"}
                        className={`${fieldClassName} pr-1`}
                        value={password}
                        onChange={(event) => {
                          setPassword(event.target.value);
                          if (error) setError("");
                        }}
                        placeholder="请输入登录密码"
                        autoComplete="current-password"
                        aria-invalid={hasError ? true : undefined}
                        aria-describedby={hasError ? "login-error" : undefined}
                        required
                      />
                      <button
                        type="button"
                        aria-label={showPassword ? "隐藏密码" : "显示密码"}
                        aria-pressed={showPassword}
                        title={showPassword ? "隐藏密码" : "显示密码"}
                        onClick={() => setShowPassword((visible) => !visible)}
                        className="auth-password-toggle mr-2 grid h-9 w-9 shrink-0 place-items-center rounded-[9px] text-[#8a989f] transition-colors hover:bg-[#edf1f2] hover:text-[#4a6f8a] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#4a6f8a] motion-reduce:transition-none"
                      >
                        {showPassword ? (
                          <EyeOff aria-hidden className="h-[17px] w-[17px]" strokeWidth={1.7} />
                        ) : (
                          <Eye aria-hidden className="h-[17px] w-[17px]" strokeWidth={1.7} />
                        )}
                      </button>
                    </div>
                  </div>

                  {error ? (
                    <div
                      id="login-error"
                      role="alert"
                      className="flex items-center gap-2 rounded-[10px] bg-[#fff7f7] px-3.5 py-3 text-sm font-normal text-[#b91c1c] ring-1 ring-inset ring-[#fecaca]"
                    >
                      <AlertCircle aria-hidden className="h-4 w-4 shrink-0" strokeWidth={1.8} />
                      {error}
                    </div>
                  ) : null}

                  <button
                    type="submit"
                    aria-busy={loading}
                    disabled={loading}
                    className="auth-button auth-cta mt-2 inline-flex h-[52px] w-full items-center justify-center gap-2.5 rounded-[12px] text-white motion-reduce:transition-none"
                  >
                    {loading ? (
                      <>
                        <Loader2 aria-hidden className="h-[17px] w-[17px] animate-spin motion-reduce:animate-none" />
                        <span className="text-white/85">正在校验</span>
                      </>
                    ) : (
                      <>
                        <span>登录</span>
                        <span className="auth-cta-icon grid h-7 w-7 place-items-center rounded-full bg-white/10">
                          <ArrowRight aria-hidden className="h-[15px] w-[15px]" strokeWidth={1.8} />
                        </span>
                      </>
                    )}
                  </button>
                </form>
              </div>

              <div className="auth-card-footer border-t border-[#4a6f8a]/[0.08] px-7 py-5 sm:px-9">
                <p className="flex items-center justify-center gap-2.5 text-[11.5px] leading-5 text-[#70818d]">
                  <span aria-hidden className="grid h-7 w-7 place-items-center rounded-full border border-[#4a6f8a]/10 bg-white/60 text-[#4a6f8a]">
                    <ShieldCheck className="h-3.5 w-3.5" strokeWidth={1.7} />
                  </span>
                  <span>安全连接<span className="mx-2 text-[#b5c0c7]">·</span>登录行为将写入审计日志</span>
                </p>
              </div>
              </div>
            </div>

            <p className="mt-6 hidden text-center text-xs text-[#8a9ba9] sm:block">
              遇到问题？
              <a
                href="mailto:{{SECRET_d8zo1uvg}}"
                className="ml-1 font-medium text-[#52718a] underline decoration-[#c9d5de] underline-offset-4 transition-colors hover:text-[#2d5068] hover:decoration-[#52718a] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4a6f8a]"
              >
                联系管理员
              </a>
            </p>
          </div>
        </main>

        <AdminFooter variant="auth" />
      </div>
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
