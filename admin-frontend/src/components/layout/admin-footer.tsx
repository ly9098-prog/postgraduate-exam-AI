export function AdminFooter() {
  return (
    <footer className="border-t border-[var(--color-border)] bg-[rgba(255,253,248,0.84)] px-4 py-5 backdrop-blur-xl lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-center gap-1 text-center text-xs leading-5 text-[var(--color-text-hint)] sm:flex-row sm:gap-3">
        <span>© {new Date().getFullYear()} MemoGrad</span>
        <span className="hidden h-3 w-px bg-[var(--color-border)] sm:block" />
        <a className="font-medium transition hover:text-[var(--color-primary-dark)]" href="https://beian.miit.gov.cn/" target="_blank" rel="noreferrer">
          桂ICP备2026003057号-1
        </a>
      </div>
    </footer>
  );
}
