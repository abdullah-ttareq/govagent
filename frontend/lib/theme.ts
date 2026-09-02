/**
 * الوضع الفاتح والداكن — مصدر واحد للاختيار وتطبيقه.
 *
 * **خياران لا ثلاثة:** «فاتح» و«داكن» فقط. خيار «تلقائي / الجهاز» أُزيل من
 * الموقع: المظهر إعدادٌ يضبطه الموظف مرة، وحالةٌ ثالثة تتبع الجهاز تجعل
 * الواجهة تتبدّل تحت يده بلا فعل منه، وتُظهر في الزرّ أيقونة لا تصف ما يراه.
 *
 * ⚠️ **الإضافة (Chrome Extension) تحتفظ بالخيارات الثلاثة** — لها كودها
 * المستقل في `extension/popup.js` ومخزنها منفصل عن مخزن الموقع، فلا يؤثر
 * هذا الملف فيها.
 *
 * **القيم القديمة تُهاجَر عند القراءة:** متصفّح موظف حفظ `system` أو `auto`
 * قبل هذا التغيير يقرأها هذا الملف على أنها `light`. لولا ذلك لبقيت قيمة لا
 * يقابلها خيار في القائمة، فلا يظهر صحٌّ على شيء ولا يعرف الموظف أين هو.
 * **مفتاح التخزين نفسه لم يتغيّر** حتى لا يفقد أحد اختياره.
 *
 * التخزين في `localStorage` لا في كوكي أو حالة React: السكربت الذي يمنع
 * الوميض في `layout.tsx` يعمل **قبل** أن يقلع React، ويحتاج قراءة متزامنة.
 */

export type ThemeChoice = "light" | "dark";
/** الوضع المطبَّق فعلًا. لم يعد يختلف عن الاختيار بعد إزالة «تلقائي». */
export type ResolvedTheme = ThemeChoice;

export const THEME_STORAGE_KEY = "govagent.theme";

export const THEME_CHOICES: ThemeChoice[] = ["light", "dark"];

/** الوضع عند أول زيارة، وعند أي قيمة مخزّنة لا نعرفها. */
export const DEFAULT_THEME: ThemeChoice = "light";

/** القيم التي كانت تعني «اتبع الجهاز» قبل إزالة الخيار. */
const LEGACY_AUTO_VALUES = ["system", "auto"];

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "light" || value === "dark";
}

/**
 * يحوّل أي قيمة مخزّنة إلى اختيار صالح.
 *
 * `system` و`auto` — وأي قيمة غريبة أو `null` — تصير `light`. دالة نقية
 * حتى تُختبر بلا متصفح.
 */
export function normalizeStoredTheme(value: unknown): ThemeChoice {
  if (isThemeChoice(value)) return value;
  if (typeof value === "string" && LEGACY_AUTO_VALUES.includes(value)) {
    return DEFAULT_THEME;
  }
  return DEFAULT_THEME;
}

/** يقرأ اختيار الموظف، مُهاجرًا القيم القديمة، أو الافتراضي إن تعذّر. */
export function readStoredTheme(): ThemeChoice {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    return normalizeStoredTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    // وضع التصفّح الخاص قد يمنع التخزين — الاختيار يعمل للجلسة فقط.
    return DEFAULT_THEME;
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

/** قيمة الإماهة: السيرفر لا يعرف تخزين المتصفح، فيبدأ الجميع من الافتراضي. */
export function getThemeServerSnapshot(): ThemeChoice {
  return DEFAULT_THEME;
}

/** يحفظ الاختيار ويطبّقه ويُعلم المشتركين — نقطة التغيير الوحيدة. */
export function setThemeChoice(choice: ThemeChoice): void {
  storeTheme(choice);
  applyTheme(choice);
  listeners.forEach((listener) => listener());
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
 *
 * يهاجر القيم القديمة كما تفعل `normalizeStoredTheme` تمامًا: `system`
 * و`auto` وأي قيمة غريبة كلها تعني الوضع الفاتح.
 */
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
    document.documentElement.dataset.theme = stored === "dark" ? "dark" : "light";
  } catch (e) {
    document.documentElement.dataset.theme = "light";
  }
})();
`.trim();
