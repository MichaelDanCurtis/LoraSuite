import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Native modal placement keeps dialogs above transformed and sticky workspaces. */
export function AppDialog({ children, className, label, onClose }: {
  children: ReactNode;
  className: string;
  label: string;
  onClose(): void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const previousFocus = document.activeElement;
    if (!element) return;
    if (typeof element.showModal === "function") element.showModal();
    else element.setAttribute("open", "");
    return () => {
      if (typeof element.close === "function") element.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, []);
  return createPortal(
    <dialog ref={dialog} className={`app-dialog ${className}`} aria-label={label}
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const rect = event.currentTarget.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose();
      }}>
      {children}
    </dialog>, document.body,
  );
}
