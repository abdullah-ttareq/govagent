/**
 * الوضع الفاتح والداكن — مصدر واحد للاختيار وتطبيقه.
 *
 * **ثلاث قيم لا اثنتان:** `system` ليست حالة وسطى بل «اتبع الجهاز»، وهي
 * الافتراضية في أول زيارة. لولاها لاضطررنا إلى تخمين وضعٍ أوّليّ ثم تثبيته،
 * فيبقى الموظف على وضع لم يختره حتى لو غيّر إعداد جهازه.
 *
 * التخزين في `localStorage` لا في كوكي أو حالة React: السكربت الذي يمنع
 * الوميض في `layout.tsx` يعمل **قبل** أن يقلع React، ويحتاج قراءة متزامنة.
 */

export type ThemeChoice = "light" | "dark" | "system";
/** الوضع المطبَّق فعلًا بعد حلّ `system`. */
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "govagent.theme";

export const THEME_CHOICES: ThemeChoice[] = ["light", "dark", "system"];

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "light" || value === "dark" || value === "system";
}

/** يقرأ اختيار الموظف، أو `system` إن لم يختر أو تعذّر التخزين. */
export function readStoredTheme(): ThemeChoice {
  if (typeof window === "undefined") return "system";
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(stored) ? stored : "system";
  } catch {
    // وضع التصفّح الخاص قد يمنع التخزين — الاختيار يعمل للجلسة فقط.
    return "system";
  }
}

export function storeTheme(choice: ThemeChoice): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    /* تجاهل: الاختيار مطبَّق على الصفحة ولو لم يُحفظ. */
  }
}

/* ---------------------------------------------------------------------------
   مخزن خارجي للاختيار

   `localStorage` مصدرٌ خارج React، فيُقرأ بـ`useSyncExternalStore` لا بـ
   `useState` داخل `useEffect`: الثاني يفرض رسمًا ثانيًا بعد كل إماهة،
   والأول يعطي React قيمة السيرفر وقيمة العميل فيتولّى الفرق بنفسه.
   --------------------------------------------------------------------------- */

const listeners = new Set<() => void>();

export function subscribeToTheme(listener: () => void): () => void {
  listeners.add(listener);
  // تبديل الوضع في تبويب آخر ينعكس هنا كذلك.
  const onStorage = (event: StorageEvent) => {
    if (event.key === THEME_STORAGE_KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function getThemeSnapshot(): ThemeChoice {
  return readStoredTheme();
}

/** قيمة الإماهة: السيرفر لا يعرف تخزين المتصفح، فيبدأ الجميع من `system`. */
export function getThemeServerSnapshot(): ThemeChoice {
  return "system";
}

/** يحفظ الاختيار ويطبّقه ويُعلم المشتركين — نقطة التغيير الوحيدة. */
export function setThemeChoice(choice: ThemeChoice): void {
  storeTheme(choice);
  applyTheme(resolveTheme(choice));
  listeners.forEach((listener) => listener());
}

/** إعداد الجهاز الحالي. */
export function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  return choice === "system" ? systemTheme() : choice;
}

/**
 * يطبّق الوضع على المستند.
 *
 * السمة على `<html>` لا صنف على `<body>`: متغيّرات النظام معرّفة على
 * `:root`، ولون خلفية الصفحة نفسها يُقرأ من هناك قبل رسم الجسم.
 */
export function applyTheme(resolved: ResolvedTheme): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = resolved;

  // شريط المتصفح على الجوال يتبع الوضع كذلك، وإلا بقي أخضر فاتحًا فوق
  // واجهة داكنة.
  const meta = document.querySelector<HTMLMetaElement>(
    'meta[name="theme-color"]',
  );
  if (meta) meta.content = resolved === "dark" ? "#0a1020" : "#1e50c8";
}

/**
 * سكربت يُحقن في `<head>` ويُنفَّذ **قبل أول رسم**.
 *
 * بدونه ترسم الصفحة بالوضع الفاتح ثم تقفز إلى الداكن بعد إقلاع React —
 * وميضٌ أبيض في وجه من اختار الداكن. مكتوب كنصّ لأنه يسبق أي حزمة.
 */
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    var resolved =
      stored === "light" || stored === "dark"
        ? stored
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    document.documentElement.dataset.theme = resolved;
  } catch (e) {
    document.documentElement.dataset.theme = "light";
  }
})();
`.trim();
