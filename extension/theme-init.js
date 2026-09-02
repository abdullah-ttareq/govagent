/**
 * ضبط المظهر **قبل أول رسم** — يُحمَّل في `<head>` قبل ورقة الأنماط.
 *
 * سكربت منفصل لا وسمٌ داخل الصفحة: `manifest_version: 3` يمنع السكربت
 * السطري (`inline`) بسياسة المحتوى الافتراضية للإضافات، فالوسم السطري لا
 * ينفَّذ إطلاقًا.
 *
 * **`localStorage` لا `chrome.storage.local`:** الأول متزامن فيُقرأ قبل
 * الرسم، والثاني غير متزامن فيصل بعد أن تُرسم النافذة بالوضع الخطأ —
 * وذلك هو الوميض نفسه الذي نتجنّبه. ولا يحتاج أيٌّ منهما صلاحية جديدة:
 * `localStorage` متاح لصفحات الإضافة بلا إعلان.
 */

(function () {
  var KEY = "govagent.theme";
  try {
    // ⚠️ خياران فقط. أي قيمة أخرى — بما فيها `system` أو `auto` المخزّنة
    // في تركيبة قديمة — تُقرأ «فاتحًا»، فلا يبقى للخيار المحذوف أثر.
    var stored = localStorage.getItem(KEY);
    document.documentElement.dataset.theme =
      stored === "dark" ? "dark" : "light";
  } catch (error) {
    document.documentElement.dataset.theme = "light";
  }
})();
