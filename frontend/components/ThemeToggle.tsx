"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import {
  applyTheme,
  getThemeServerSnapshot,
  getThemeSnapshot,
  setThemeChoice,
  type ThemeChoice,
} from "@/lib/theme";
import { subscribeToTheme } from "@/lib/theme";

function SunIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4">
      <path
        fill="currentColor"
        d="M10 6a4 4 0 1 0 0 8 4 4 0 0 0 0-8m0 1.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5M10 1.5a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 1.5m0 14a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 10 15.5M18.5 10a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m-14 0a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5a.75.75 0 0 1 .75.75m11.5-6a.75.75 0 0 1 0 1.06l-1.06 1.06a.75.75 0 1 1-1.06-1.06L14.94 4a.75.75 0 0 1 1.06 0M6.62 13.38a.75.75 0 0 1 0 1.06L5.56 15.5A.75.75 0 0 1 4.5 14.44l1.06-1.06a.75.75 0 0 1 1.06 0m9.38 2.12a.75.75 0 0 1-1.06 0l-1.06-1.06a.75.75 0 0 1 1.06-1.06l1.06 1.06a.75.75 0 0 1 0 1.06M6.62 6.62a.75.75 0 0 1-1.06 0L4.5 5.56A.75.75 0 0 1 5.56 4.5l1.06 1.06a.75.75 0 0 1 0 1.06"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true" className="size-4">
      <path
        fill="currentColor"
        d="M16.3 12.6a6.6 6.6 0 0 1-8.9-8.9.75.75 0 0 0-.98-.98 8.1 8.1 0 1 0 10.86 10.86.75.75 0 0 0-.98-.98M10 16.6a6.6 6.6 0 0 1-4.6-11.3 8.1 8.1 0 0 0 9.9 9.9A6.57 6.57 0 0 1 10 16.6"
      />
    </svg>
  );
}

const OPTIONS: {
  value: ThemeChoice;
  label: string;
  Icon: () => React.ReactElement;
}[] = [
  { value: "light", label: "فاتح", Icon: SunIcon },
  { value: "dark", label: "داكن", Icon: MoonIcon },
];

/**
 * مبدّل المظهر — زرّ أيقونة صغير يفتح قائمة بخيارين: فاتح وداكن.
 *
 * **زرّ وقائمة لا زرّان ظاهران:** المظهر إعدادٌ يُضبط مرة ثم يُنسى، فلا
 * يستحق عرضًا دائمًا في زاوية أو في شريط جانبي. الزرّ يعرض أيقونة الوضع
 * الفعّال — شمسًا في الفاتح وقمرًا في الداكن — فتبقى الحالة مقروءة بلا فتح.
 *
 * ⚠️ خيار «تلقائي» أُزيل من الموقع وبقي في الإضافة وحدها — انظر `lib/theme`.
 */
export default function ThemeToggle({ className = "" }: { className?: string }) {
  // `localStorage` مخزن خارج React: يُقرأ هكذا لا بـ`useState` في `useEffect`.
  const choice = useSyncExternalStore(
    subscribeToTheme,
    getThemeSnapshot,
    getThemeServerSnapshot,
  );

  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const active = OPTIONS.find((option) => option.value === choice) ?? OPTIONS[0];

  useEffect(() => {
    // يُطبَّق كلما استقرّ الاختيار: أثناء الإماهة يعطي `useSyncExternalStore`
    // قيمة السيرفر (الافتراضي) ثم يعيد الرسم بقيمة المتصفح، فلولا التطبيق
    // هنا لبقيت الصفحة على الوضع الافتراضي بعد أن استقرّ الاختيار على غيره.
    applyTheme(choice);
  }, [choice]);

  // القائمة تُغلق بالنقر خارجها وبـEscape، كأي طبقة عائمة في الواجهة.
  useEffect(() => {
    if (!isOpen) return;

    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setIsOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
        rootRef.current?.querySelector("button")?.focus();
      }
    }

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isOpen]);

  return (
    <div ref={rootRef} className={`gv-theme ${className}`.trim()}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="gv-theme__trigger"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls={menuId}
        aria-label={`المظهر: ${active.label}`}
        title={`المظهر: ${active.label}`}
      >
        <active.Icon />
      </button>

      {isOpen && (
        <div id={menuId} role="menu" className="gv-theme__menu">
          {OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="menuitemradio"
              aria-checked={choice === option.value}
              onClick={() => {
                setThemeChoice(option.value);
                setIsOpen(false);
              }}
              className="gv-theme__item"
            >
              <option.Icon />
              <span>{option.label}</span>
              {choice === option.value && (
                <svg
                  viewBox="0 0 20 20"
                  aria-hidden="true"
                  className="size-4 shrink-0"
                >
                  <path
                    fill="currentColor"
                    d="M16.7 5.3a.75.75 0 0 1 0 1.06l-8 8a.75.75 0 0 1-1.06 0l-4-4a.75.75 0 1 1 1.06-1.06L8.17 12.8l7.47-7.47a.75.75 0 0 1 1.06 0"
                  />
                </svg>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
