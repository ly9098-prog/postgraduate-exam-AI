export const reviewPageStyles = `
@keyframes loadingBar { 0% { transform: translateX(-100%); } 50% { transform: translateX(100%); } 100% { transform: translateX(300%); } }
@keyframes slideInRight { from { transform: translateX(100%); } to { transform: translateX(0); } }
@keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes inkSpread { 0% { transform: scale(0.3); opacity: 0.8; } 50% { transform: scale(1); opacity: 0.4; } 100% { transform: scale(1.3); opacity: 0; } }
@keyframes stampPop { 0% { transform: scale(0.8) rotate(-3deg); opacity: 0; } 60% { transform: scale(1.05) rotate(0.5deg); opacity: 1; } 100% { transform: scale(1) rotate(0deg); opacity: 1; } }
@keyframes paperSlide { 0% { transform: translateX(100%) rotate(2deg); opacity: 0; } 100% { transform: translateX(0) rotate(0deg); opacity: 1; } }
@keyframes sealStamp { 0% { transform: scale(2) rotate(-8deg); opacity: 0; } 50% { transform: scale(1.1) rotate(1deg); opacity: 1; } 100% { transform: scale(1) rotate(0deg); opacity: 1; } }
@keyframes cardLift { 0% { box-shadow: var(--shadow-card); transform: translateY(0); } 100% { box-shadow: 0 20px 50px rgba(45, 62, 80, 0.12), 0 6px 14px rgba(45, 62, 80, 0.06); transform: translateY(-2px); } }
@keyframes shimmer { 0% { background-position: -200% center; } 100% { background-position: 200% center; } }
.animate-slide-in { animation: slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1); }
.animate-fade-up { animation: fadeUp 0.5s cubic-bezier(0.16, 1, 0.3, 1) both; }
.animate-ink-spread { animation: inkSpread 1.5s ease-out infinite; }
.animate-paper-slide { animation: paperSlide 0.35s cubic-bezier(0.16, 1, 0.3, 1) both; }
.animate-seal-stamp { animation: sealStamp 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) both; }
.drawer-section-delay-1 { animation-delay: 0.05s; }
.drawer-section-delay-2 { animation-delay: 0.1s; }
.drawer-section-delay-3 { animation-delay: 0.15s; }
.drawer-section-delay-4 { animation-delay: 0.2s; }
.drawer-section-delay-5 { animation-delay: 0.25s; }
.bg-noise { background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E"); background-size: 128px 128px; }
.risk-seal { display: inline-flex; align-items: center; gap: 4px; padding: 2px 10px 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 700; letter-spacing: 0.03em; border: 1.5px solid; }
.risk-seal-high { color: #b03a3a; border-color: #b03a3a; background: linear-gradient(135deg, #fef2f2, #fde8e8); }
.risk-seal-medium { color: #b87a30; border-color: #b87a30; background: linear-gradient(135deg, #fffbeb, #fef3c7); }
.risk-seal-low { color: #3a7a5a; border-color: #3a7a5a; background: linear-gradient(135deg, #f0fdf4, #dcfce7); }
.card-hover { transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1); }
.card-hover:hover { animation: cardLift 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards; border-color: rgba(91, 123, 154, 0.25); }
.card-linen { background-image: url("data:image/svg+xml,%3Csvg width='100' height='100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='l'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='1.5' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100' height='100' filter='url(%23l)' opacity='0.03'/%3E%3C/svg%3E"); background-size: 100px 100px; }
.scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
.scrollbar-hide::-webkit-scrollbar { display: none; }
.card-risk-border { position: relative; overflow: hidden; }
.card-risk-border::before { content: ""; position: absolute; top: 0; left: 0; width: 4px; height: 100%; border-radius: 2px 0 0 2px; }
.card-risk-high::before { background: linear-gradient(180deg, #b03a3a, #c47a7a); }
.card-risk-medium::before { background: linear-gradient(180deg, #b87a30, #c49a6b); }
.card-risk-low::before { background: linear-gradient(180deg, #3a7a5a, #6b9b6b); }
.card-risk-none::before { background: linear-gradient(180deg, transparent, rgba(91,123,154,0.15)); }
.section-scroll { position: relative; overflow: hidden; padding-left: 16px; }
.section-scroll::before { content: ""; position: absolute; top: 0; left: 0; width: 3px; height: 100%; border-radius: 0 2px 2px 0; }
.section-scroll-warm::before { background: linear-gradient(180deg, transparent, rgba(196, 154, 107, 0.4), rgba(196, 154, 107, 0.2), transparent); }
.section-scroll-ink::before { background: linear-gradient(180deg, transparent, rgba(91, 123, 154, 0.35), rgba(91, 123, 154, 0.15), transparent); }
.section-scroll-jade::before { background: linear-gradient(180deg, transparent, rgba(107, 155, 107, 0.35), rgba(107, 155, 107, 0.15), transparent); }
.section-scroll-purple::before { background: linear-gradient(180deg, transparent, rgba(154, 122, 186, 0.3), rgba(154, 122, 186, 0.12), transparent); }
.stem-text { font-size: 0.9375rem; line-height: 1.75; color: var(--ink); white-space: pre-wrap; }
.stem-text code { font-family: var(--font-mono); font-size: 0.8125rem; background: rgba(91,123,154,0.08); padding: 1px 5px; border-radius: 4px; }
.stem-text pre { font-family: var(--font-mono); font-size: 0.8125rem; background: rgba(45,62,80,0.04); border: 1px solid rgba(232,229,224,0.6); border-radius: 10px; padding: 12px 14px; overflow-x: auto; white-space: pre-wrap; margin: 8px 0; line-height: 1.6; }
.option-chip { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 8px; font-size: 11px; font-weight: 700; background: rgba(196,154,107,0.12); color: #8a6a3a; flex-shrink: 0; }
.answer-box { display: inline-flex; align-items: center; gap: 8px; border: 1.5px solid rgba(107,155,107,0.2); background: rgba(107,155,107,0.06); border-radius: 10px; padding: 6px 14px; font-family: var(--font-mono); font-size: 0.875rem; font-weight: 700; color: #3a7a5a; }
/* ── Segment Editor ── */
@keyframes segLiftIn { from { opacity: 0; transform: translateY(6px) scale(0.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
@keyframes segPopOut { from { opacity: 1; transform: scale(1); max-height: 120px; } to { opacity: 0; transform: scale(0.92); max-height: 0; margin-top: 0; margin-bottom: 0; padding-top: 0; padding-bottom: 0; } }
@keyframes imageGlow { 0% { box-shadow: 0 0 0 0 rgba(196,154,107,0.0); } 50% { box-shadow: 0 0 0 3px rgba(196,154,107,0.25), 0 4px 20px rgba(196,154,107,0.08); } 100% { box-shadow: 0 0 0 0 rgba(196,154,107,0.0); } }
@keyframes gripPulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.7; } }
.seg-card { transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.18s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.18s ease, background-color 0.18s ease; }
.seg-card:hover { transform: translateY(-1px); }
.seg-card.dragging { transform: scale(0.97); opacity: 0.6; filter: grayscale(0.1); }
.seg-card.drop-target { transform: translateY(0); border-color: var(--color-warning); background: rgba(196,154,107,0.04); box-shadow: 0 0 0 2px rgba(196,154,107,0.15), 0 4px 16px rgba(196,154,107,0.08); }
.seg-card.drop-target::before { content: ""; position: absolute; top: -2px; left: 8px; right: 8px; height: 2px; background: linear-gradient(90deg, transparent, var(--color-warning), transparent); border-radius: 1px; }
.seg-image-preview { transition: all 0.25s ease; }
.seg-image-preview:hover { transform: scale(1.02); box-shadow: 0 4px 20px rgba(27,39,51,0.1), 0 1px 4px rgba(27,39,51,0.06); }
.seg-section-header { position: relative; }
.seg-section-header::after { content: ""; position: absolute; bottom: -8px; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, rgba(196,154,107,0.3), transparent 70%); }
`;
