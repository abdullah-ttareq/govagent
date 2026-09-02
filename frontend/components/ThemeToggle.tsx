"use client";

import { useEffect, useSyncExternalStore } from "react";
import {
  applyTheme,
  getThemeServerSnapshot,
  getThemeSnapshot,
  setThemeChoice,
  subscribeToTheme,
} from "@/lib/theme";

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

/**
 * مبدّل المظهر — **شريحتان: قمر وشمس، والفعّالة مُبرَزة**.
 *
 * هذا شكل التصميم المعتمد: الخياران ظاهران معًا في غلاف واحد، والوضع
 * الحالي مُبرَز بقرص داكن. وهو يحفظ ما طُلب سابقًا: **وضعان لا ثلاثة**،
 * وأيقونتان لا غير، ونقرةٌ واحدة تكفي للانتقال.
 *
 * ⚠️ **لا «تلقائي» ولا «الجهاز» ولا أيقونة شاشة.** وضعٌ يتبع الجهاز
 * يتبدّل تحت يد الموظف بلا فعل منه — عند غروب الشمس أو حين يغيّر ويندوز
 * مظهره. القيم القديمة (`system`/`auto`) تُهاجَر إلى «فاتح» في `lib/theme`.
 *
 * ⚠️ **كل شريحة تحمل نصّ فعلها**: «تفعيل الوضع الفاتح» على الشمس،
 * و«تفعيل الوضع الداكن» على القمر — فيقرأ مستخدم قارئ الشاشة ما سيحدث،
 * و`aria-pressed` يقول له أين هو الآن.
 *
 * التخزين في `localStorage` عبر `lib/theme`، ويقرؤه سكربتٌ في `<head>`
 * **قبل أول رسم** — فيبقى الاختيار بعد تحديث الصفحة وبعد إعادة تشغيل
 * الـRuntime، بلا وميض في وجه من اختار الداكن.
 */
export default function ThemeToggle({ className = "" }: { className?: string }) {
  // `localStorage` مخزن خارج React: يُقرأ هكذا لا بـ`useState` في `useEffect`.
  const choice = useSyncExternalStore(
    subscribeToTheme,
    getThemeSnapshot,
    getThemeServerSnapshot,
  );

  useEffect(() => {
    // يُطبَّق كلما استقرّ الاختيار: أثناء الإماهة يعطي `useSyncExternalStore`
    // قيمة السيرفر (الافتراضي) ثم يعيد الرسم بقيمة المتصفح.
    applyTheme(choice);
  }, [choice]);

  return (
    <div className={`gv-theme__seg ${className}`.trim()}>
      <button
        type="button"
        aria-label="تفعيل الوضع الفاتح"
        title="تفعيل الوضع الفاتح"
        aria-pressed={choice === "light"}
        onClick={() => setThemeChoice("light")}
      >
        <SunIcon />
      </button>
      <button
        type="button"
        aria-label="تفعيل الوضع الداكن"
        title="تفعيل الوضع الداكن"
        aria-pressed={choice === "dark"}
        onClick={() => setThemeChoice("dark")}
      >
        <MoonIcon />
      </button>
    </div>
  );
}
