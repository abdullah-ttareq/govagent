/*
 * Service Worker لـGovMind.
 *
 * **ما لا يفعله أهمّ ممّا يفعله.** هذا سيرفر جهة حكومية، فلا يُخزَّن هنا أي
 * ردّ من الـAPI إطلاقًا: المحادثات والملفات وسجل التدقيق تخصّ جهة بعينها،
 * وحفظها في ذاكرة المتصفح يجعلها تنجو من تسجيل الخروج ومن تبديل المستخدم على
 * جهاز مشترك. المخزَّن هنا هيكل التطبيق فقط: صفحة عدم الاتصال وأيقوناتها.
 *
 * التنقّل «الشبكة أولًا»: نسخة قديمة من صفحة تُعرض بدل الحيّة تصنع أعطالًا
 * يصعب تفسيرها بعد كل نشر. عند انقطاع الشبكة تُعرض صفحة عدم اتصال صريحة.
 */

//: ⚠️ **يُرفَع الرقم عند كل تغيير في هيكل التطبيق.**
//:
//: هذا إصلاح عطل حيّ: عامل خدمة قديم بقي مسجَّلًا على `127.0.0.1:8765` كان
//: يخدم هيكلًا قديمًا يحمل صفحة `/login/` — فظهر للمستخدم **نموذج دخول ثانٍ**
//: بعد أن ألغاه البناء الجديد أصلًا. والأصل واحد لكل المستخدمين، فمن يحدّث
//: من نسخة أقدم يقع في العطل نفسه ما لم يتغيّر هذا الاسم.
//:
//: تركُ الاسم كما هو يعني أن `activate` أدناه لا يجد شيئًا ليحذفه، فيبقى
//: المخزن القديم حيًّا بعد النشر. **رفعُ الرقم هو ما يُطلق التنظيف.**
const CACHE_NAME = "govagent-shell-v2";

//: مخازن أصدرتها نسخ سابقة. تُحذف صراحةً في `activate`.
const LEGACY_CACHES = ["govagent-shell-v1"];
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
  // ⚠️ **يُحذف كل مخزن لا يطابق الاسم الحالي** — والقدامى المعروفون معهم
  // صراحةً. الشرطان يغطّيان الحالة نفسها، والثاني مقصود: اسمٌ مذكور بنصّه
  // يُقرأ في المراجعة، ويبقى الحذف صحيحًا لو تغيّر ترتيب الأسماء يومًا.
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            // ⚠️ **الشرط الوحيد: ما لا يطابق الاسم الحالي يُحذف.**
            // و`LEGACY_CACHES` جزء منه بالضرورة ما دام الاسم الحالي ليس فيها
            // — وذلك ما يحرسه الاختبار. شرطٌ ثانٍ بـ`||` كان سيحذف المخزن
            // الحيّ نفسه لو أُدرج اسمه في القائمة سهوًا.
            .filter((name) => name !== CACHE_NAME)
            .map((name) => caches.delete(name)),
        ),
      )
      // `claim()` يجعل التبويبات المفتوحة تتبع هذا العامل فورًا، فلا يبقى
      // مستخدمٌ على الهيكل القديم حتى يغلق كل تبويباته.
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
