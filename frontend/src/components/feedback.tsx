import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

// ---------------------------------------------------------------------------- toasts
type ToastKind = "ok" | "fail" | "info" | "warn";
interface Toast { id: number; kind: ToastKind; text: string }
const ToastCtx = createContext<(text: string, kind?: ToastKind) => void>(() => undefined);

/** Short pop-up messages in the corner ("Email settings saved."). Errors stay longer than successes. */
export function useToast() {
  return useContext(ToastCtx);
}

// ---------------------------------------------------------------------------- confirm dialog
interface ConfirmOptions { title: string; message: ReactNode; confirmLabel?: string; danger?: boolean }
const ConfirmCtx = createContext<(o: ConfirmOptions) => Promise<boolean>>(async () => false);

/** `if (await confirm({title, message, danger: true})) …` - a proper dialog instead of the browser's confirm box. */
export function useConfirm() {
  return useContext(ConfirmCtx);
}

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const toast = useCallback((text: string, kind: ToastKind = "ok") => {
    const id = next.current++;
    setToasts((t) => [...t.slice(-3), { id, kind, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "fail" ? 9000 : 4500);
  }, []);

  const [dialog, setDialog] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);
  const confirm = useCallback((o: ConfirmOptions) => new Promise<boolean>((resolve) => setDialog({ ...o, resolve })), []);
  const close = (v: boolean) => { dialog?.resolve(v); setDialog(null); };
  const okRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!dialog) return;
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <ToastCtx.Provider value={toast}>
      <ConfirmCtx.Provider value={confirm}>
        {children}
        <div className="toasts" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast toast-${t.kind}`} role={t.kind === "fail" ? "alert" : "status"}>
              <span>{t.text}</span>
              <button type="button" aria-label="Dismiss" onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}>×</button>
            </div>
          ))}
        </div>
        {dialog && (
          <div className="modal-scrim" onClick={() => close(false)}>
            <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="modal-title" onClick={(e) => e.stopPropagation()}>
              <h3 id="modal-title">{dialog.title}</h3>
              <div className="modal-body">{dialog.message}</div>
              <div className="modal-actions">
                <button type="button" className="btn btn-ghost btn-inline" onClick={() => close(false)}>Cancel</button>
                <button type="button" ref={okRef} className={`btn btn-inline ${dialog.danger ? "btn-danger" : "btn-primary"}`} onClick={() => close(true)}>
                  {dialog.confirmLabel ?? "Confirm"}
                </button>
              </div>
            </div>
          </div>
        )}
      </ConfirmCtx.Provider>
    </ToastCtx.Provider>
  );
}
