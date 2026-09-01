/**
 * `chrome` مزيّف لاختبارات الإضافة.
 *
 * **يحاكي السلوك لا الشكل فقط:** التخزين قاموس حقيقي، والتنزيلات تحفظ
 * سجلًّا بحالة تتغيّر — فاختبار «شريط التقدّم يتحرّك ثم ينتهي» يمرّ على
 * المنطق نفسه الذي يعمل في المتصفح، لا على استدعاء مزيّف يعيد رقمًا.
 *
 * الاستدعاءات بنمط رد النداء (callback) كما في Manifest V3 لا الوعود:
 * `chrome.downloads.download` يأخذ `callback`، وكودنا يلفّه بوعد. لو زيّفناه
 * بوعد لاختبرنا شيئًا لا وجود له.
 */

import { beforeEach, vi } from "vitest";

/** يعيد تعيين التخزين والتنزيلات — يُستدعى قبل كل اختبار. */
export function resetChrome() {
  const store = new Map();
  const downloads = new Map();
  let nextDownloadId = 1;

  globalThis.chrome = {
    runtime: { lastError: undefined },

    storage: {
      local: {
        async get(keys) {
          const wanted =
            keys === undefined || keys === null
              ? [...store.keys()]
              : Array.isArray(keys)
                ? keys
                : [keys];
          const result = {};
          for (const key of wanted) {
            if (store.has(key)) result[key] = store.get(key);
          }
          return result;
        },
        async set(values) {
          for (const [key, value] of Object.entries(values)) {
            store.set(key, value);
          }
        },
        async remove(keys) {
          for (const key of Array.isArray(keys) ? keys : [keys]) {
            store.delete(key);
          }
        },
      },
    },

    downloads: {
      /** يسجّل تنزيلًا جديدًا بحالة «جارٍ» وبلا بايتات بعد. */
      download: vi.fn((options, callback) => {
        if (chrome.downloads.__refuse) {
          chrome.runtime.lastError = { message: "Download refused" };
          callback(undefined);
          chrome.runtime.lastError = undefined;
          return;
        }
        const id = nextDownloadId++;
        downloads.set(id, {
          id,
          url: options.url,
          filename: options.filename,
          state: "in_progress",
          bytesReceived: 0,
          totalBytes: 0,
        });
        callback(id);
      }),

      search: vi.fn(({ id }, callback) => {
        const item = downloads.get(id);
        callback(item ? [item] : []);
      }),

      cancel: vi.fn((id, callback) => {
        const item = downloads.get(id);
        if (item) {
          item.state = "interrupted";
          item.error = "USER_CANCELED";
        }
        callback?.();
      }),

      show: vi.fn(),

      // -- أدوات للاختبارات لا للإضافة --------------------------------
      /** يجعل الطلب التالي يفشل، كما يفعل متصفح يمنع التنزيل. */
      __refuse: false,
      /** يقدّم تنزيلًا جاريًا إلى بايتات معيّنة. */
      __advance(id, bytesReceived, totalBytes) {
        const item = downloads.get(id);
        if (!item) return;
        item.bytesReceived = bytesReceived;
        if (totalBytes !== undefined) item.totalBytes = totalBytes;
      },
      /** ينهي التنزيل بنجاح أو بانقطاع لسبب معلوم. */
      __finish(id, { error } = {}) {
        const item = downloads.get(id);
        if (!item) return;
        item.state = error ? "interrupted" : "complete";
        if (error) item.error = error;
        else item.bytesReceived = item.totalBytes || item.bytesReceived;
      },
      /** يحذف سجل التنزيل، كمن يمسحه من قائمة المتصفح. */
      __forget(id) {
        downloads.delete(id);
      },
      __all() {
        return [...downloads.values()];
      },
    },
  };

  return { store, downloads };
}

beforeEach(() => {
  resetChrome();
  window.localStorage?.clear();
});
