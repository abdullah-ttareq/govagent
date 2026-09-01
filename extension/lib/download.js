/**
 * تنزيل المثبّت عبر `chrome.downloads`، مع تقدّم وإلغاء ومعالجة فشل.
 *
 * **لماذا `chrome.downloads` لا رابط `<a download>`؟** لأن النافذة
 * المنبثقة تُغلق بمجرد أن يفقد المستخدم تركيزها، وتنزيلٌ بدأته الصفحة يموت
 * معها. `chrome.downloads` يسلّم التنزيل إلى المتصفح فيكمل ولو أُغلقت
 * النافذة، ويعطينا تقدّمًا حقيقيًا بالبايت.
 *
 * ⚠️ **لا تشغيل تلقائي لأي ملف `.exe`.** لا يوجد في هذا الملف — ولا في
 * الإضافة كلها — أي استدعاء يفتح المثبّت أو ينفّذه. الإضافة تنزّل الملف ثم
 * تطلب من المستخدم فتحه بنفسه والموافقة على نافذة ويندوز. تشغيل ملف تنفيذي
 * بلا فعل صريح من المستخدم سلوك برمجية خبيثة، لا سلوك منتج.
 *
 * ⚠️ **الرابط لا يُعرض ولا يُسجَّل.** يدخل هنا ويخرج إلى المتصفح، ولا يظهر
 * في أي نصّ ولا رسالة خطأ.
 */

/** حالة التنزيل كما تعرضها النافذة. */
export const DOWNLOAD_STATES = Object.freeze({
  RUNNING: "in_progress",
  DONE: "complete",
  FAILED: "interrupted",
});

/** رسائل أسباب الانقطاع التي يعطيها Chrome، مترجمة وبإجراء مفهوم. */
const INTERRUPT_MESSAGES = {
  USER_CANCELED: "أُلغي التنزيل. يمكنك بدؤه من جديد في أي وقت.",
  NETWORK_FAILED:
    "انقطع الاتصال أثناء التنزيل. تأكد من الشبكة ثم أعد المحاولة.",
  NETWORK_TIMEOUT: "انتهت مهلة التنزيل. أعد المحاولة عند تحسّن الشبكة.",
  NETWORK_DISCONNECTED:
    "انقطع الاتصال بالإنترنت أثناء التنزيل. أعد المحاولة بعد عودته.",
  SERVER_FAILED: "تعذّر على الخادم إرسال الملف. أعد المحاولة بعد قليل.",
  SERVER_FORBIDDEN:
    "انتهت صلاحية رابط التنزيل قبل أن يبدأ. أعد المحاولة للحصول على رابط جديد.",
  SERVER_UNAUTHORIZED:
    "انتهت صلاحية رابط التنزيل. أعد المحاولة للحصول على رابط جديد.",
  FILE_NO_SPACE: "لا توجد مساحة كافية على القرص لإكمال التنزيل.",
  FILE_ACCESS_DENIED:
    "منع النظام حفظ الملف. تحقق من صلاحيات مجلد التنزيلات ثم أعد المحاولة.",
  FILE_FAILED: "تعذّر حفظ الملف على القرص. أعد المحاولة.",
  USER_SHUTDOWN: "توقّف التنزيل مع إغلاق المتصفح. أعد المحاولة.",
};

/** يترجم سبب الانقطاع إلى رسالة عربية، أو رسالة عامة إن كان مجهولًا. */
export function describeInterruption(reason) {
  return (
    INTERRUPT_MESSAGES[reason] ??
    "توقّف التنزيل قبل أن يكتمل. أعد المحاولة، وإن تكرر فراجع مسؤول النظام."
  );
}

/** يحوّل البايتات إلى نصّ عربي مقروء: «١٢٤ م.ب». */
export function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "غير معروف";
  if (value < 1024) return `${value} بايت`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} ك.ب`;
  if (value < 1024 * 1024 * 1024)
    return `${(value / (1024 * 1024)).toFixed(1)} م.ب`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} ج.ب`;
}

/**
 * النسبة المئوية المكتملة، أو `null` إن كان الحجم الكلي مجهولًا.
 *
 * `null` **لا صفر**: خادم لا يرسل `Content-Length` يترك `totalBytes = 0`،
 * وعرض «٠٪» عليه يوهم بأن شيئًا لم يبدأ بينما التنزيل يجري.
 */
export function percentOf({ bytesReceived = 0, totalBytes = 0 } = {}) {
  if (!totalBytes || totalBytes <= 0) return null;
  return Math.min(100, Math.round((bytesReceived / totalBytes) * 100));
}

/**
 * يبدأ التنزيل ويعيد معرّفه.
 *
 * `saveAs: false` يحفظ في مجلد التنزيلات المعتاد بلا نافذة اختيار: نافذة
 * النظام تسرق التركيز فتُغلق النافذة المنبثقة معه، فيضيع سياق الخطوة.
 *
 * @throws {Error} برسالة عربية إن رفض المتصفح بدء التنزيل.
 */
export async function startDownload(url, fileName) {
  const downloadId = await new Promise((resolve, reject) => {
    chrome.downloads.download({ url, filename: fileName, saveAs: false }, (id) => {
      const failure = chrome.runtime?.lastError;
      // ⚠️ رسالة `lastError` قد تحتوي الرابط الموقّع. **لا تُعرض ولا تُمرَّر.**
      if (failure || id === undefined) {
        reject(
          new Error(
            "تعذّر بدء التنزيل. تأكد من أن المتصفح يسمح بالتنزيل ثم أعد المحاولة.",
          ),
        );
        return;
      }
      resolve(id);
    });
  });
  return downloadId;
}

/** يستعلم عن حالة تنزيل واحد، أو `null` إن لم يعد موجودًا. */
export async function queryDownload(downloadId) {
  const items = await new Promise((resolve) => {
    chrome.downloads.search({ id: downloadId }, (found) => resolve(found ?? []));
  });
  return items[0] ?? null;
}

/** يلغي تنزيلًا جاريًا. لا يرمي إن كان قد انتهى أصلًا. */
export async function cancelDownload(downloadId) {
  await new Promise((resolve) => {
    chrome.downloads.cancel(downloadId, () => {
      // قراءة `lastError` تمنع تحذير Chrome، والفشل هنا لا يعني شيئًا:
      // «لم أستطع إلغاء ما انتهى» نتيجةٌ مقبولة.
      void chrome.runtime?.lastError;
      resolve();
    });
  });
}

/**
 * يفتح مجلد التنزيلات على الملف المنزَّل.
 *
 * **يُظهره ولا يشغّله:** `chrome.downloads.show` يفتح المجلد ويحدّد الملف،
 * ولا ينفّذ شيئًا. تشغيل المثبّت فعلُ المستخدم وحده.
 */
export function showInFolder(downloadId) {
  chrome.downloads.show(downloadId);
}

/**
 * يتابع تقدّم تنزيل ويستدعي `onProgress` عند كل تغيّر.
 *
 * **الاستطلاع (polling) لا `onChanged` وحده:** حدث `onChanged` لا يُطلق مع
 * كل بايت، فشريط التقدّم يقف ساكنًا بين الحدثين. الاستطلاع كل نصف ثانية
 * يعطي حركة متصلة، والحدث يعطي النهاية فورًا.
 *
 * @returns {() => void} دالة إيقاف المتابعة.
 */
export function watchDownload(downloadId, { onProgress, onDone, onFail }) {
  let stopped = false;

  const finish = (item) => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    if (item?.state === DOWNLOAD_STATES.DONE) onDone?.(item);
    else onFail?.(describeInterruption(item?.error), item);
  };

  const tick = async () => {
    if (stopped) return;
    const item = await queryDownload(downloadId);
    if (!item) {
      // اختفى السجل: حُذف من قائمة التنزيلات أثناء العمل.
      finish(null);
      return;
    }
    if (item.state === DOWNLOAD_STATES.RUNNING) {
      onProgress?.(item);
      return;
    }
    finish(item);
  };

  const timer = setInterval(tick, 500);
  void tick();

  return () => {
    stopped = true;
    clearInterval(timer);
  };
}
