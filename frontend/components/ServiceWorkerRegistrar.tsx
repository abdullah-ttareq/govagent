"use client";

import { useEffect } from "react";

/**
 * يسجّل `public/sw.js` بعد اكتمال التحميل.
 *
 * **بعد `load` لا قبله:** التسجيل يتنافس على عرض النطاق مع أصول الصفحة،
 * وتأجيله يجعل أول عرض أسرع بلا خسارة — العامل يعمل من الزيارة الثانية
 * في كل الأحوال.
 *
 * التسجيل يفشل بهدوء: صفحة تعمل بلا Service Worker أفضل من خطأ في الـConsole
 * لا حيلة للموظف فيه. وفي `http://` غير `localhost` لا يسجَّل أصلًا — واجهة
 * الـSW تكون غائبة، فتكفي الحراسة على `"serviceWorker" in navigator`.
 */
export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;

    function register() {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* تجاهل: التطبيق يعمل بلا عامل خدمة. */
      });
    }

    if (document.readyState === "complete") {
      register();
      return;
    }

    window.addEventListener("load", register);
    return () => window.removeEventListener("load", register);
  }, []);

  return null;
}
