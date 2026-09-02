"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

/**
 * نافذة حوارية داخل الواجهة — البديل عن `confirm()` و `prompt()` المتصفح،
 * فهما بلا تنسيق ولا تعريب ولا تحكّم في الاتجاه.
 *
 * تغلق بـEscape وبالنقر على الخلفية، وتعيد التركيز إلى العنصر الذي فتحها.
 */
export default function Modal({
  isOpen,
  onClose,
  title,
  children,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    openerRef.current = document.activeElement as HTMLElement | null;

    // التركيز ينتقل إلى أول عنصر داخل النافذة، وإلا بقي خلفها فتصرّف
    // لوحة المفاتيح على محتوى لا يراه المستخدم.
    const focusable = panelRef.current?.querySelector<HTMLElement>(
      "input, button, textarea, select, [tabindex]:not([tabindex='-1'])",
    );
    focusable?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    document.addEventListener("keydown", handleKeyDown);
    // منع تمرير الصفحة خلف النافذة.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      openerRef.current?.focus();
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="gv-modal-backdrop"
      // النقر على الخلفية وحدها يغلق، لا النقر داخل اللوحة.
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="gv-modal"
      >
        <h2 className="text-lg font-bold" id={titleId}>
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
