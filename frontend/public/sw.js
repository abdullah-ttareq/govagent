/*
 * Service Worker لـGovAgent.
 *
 * **ما لا يفعله أهمّ ممّا يفعله.** هذا سيرفر جهة حكومية، فلا يُخزَّن هنا أي
 * ردّ من الـAPI إطلاقًا: المحادثات والملفات وسجل التدقيق تخصّ جهة بعينها،
 * وحفظها في ذاكرة المتصفح يجعلها تنجو من تسجيل الخروج ومن تبديل المستخدم على
 * جهاز مشترك. المخزَّن هنا هيكل التطبيق فقط: صفحة عدم الاتصال وأيقوناتها.
 *
 * التنقّل «الشبكة أولًا»: نسخة قديمة من صفحة تُعرض بدل الحيّة تصنع أعطالًا
 * يصعب تفسيرها بعد كل نشر. عند انقطاع الشبكة تُعرض صفحة عدم اتصال صريحة.
 */

const CACHE_NAME = "govagent-shell-v1";
const OFFLINE_URL = "/offline.html";

const SHELL_ASSETS = [
  OFFLINE_URL,
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      // تفعيل فوري: لا فائدة من انتظار إغلاق كل التبويبات لأول تثبيت.
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  // طلبات الكتابة لا تُخزَّن ولا تُعاد أبدًا.
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // كل ما ليس من أصل هذه الصفحة يمرّ كما هو: سيرفر الجهة على أصل آخر،
  // ولا يجوز أن يمرّ ردّه من هنا.
  if (url.origin !== self.location.origin) return;

  // التنقّل: الشبكة أولًا، وصفحة عدم الاتصال عند الفشل.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match(OFFLINE_URL, { ignoreSearch: true }).then(
          (cached) =>
            cached ??
            new Response("تعذّر الاتصال.", {
              status: 503,
              headers: { "Content-Type": "text/plain; charset=utf-8" },
            }),
        ),
      ),
    );
    return;
  }

  // أصول الهيكل الثابتة: من المخزن إن وُجدت، وإلا من الشبكة.
  if (SHELL_ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request)));
  }
});
