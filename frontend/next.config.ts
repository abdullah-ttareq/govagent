import type { NextConfig } from "next";

/**
 * بناءان من مصدر واحد:
 *
 * * **الويب** (الافتراضي) — كما كان، بلا تغيير.
 * * **سطح المكتب** (`GOVMIND_DESKTOP=1`) — تصدير ساكن إلى `out/` يخدمه
 *   GovMind Runtime من جهاز العميل. ممكن لأن كل صفحات التطبيق صفحات عميل:
 *   لا مسارات API ولا middleware ولا أي ميزة خادم.
 *
 * **النتيجة: لا Node.js على جهاز العميل.** لو احتجنا `next start` لاحتاج
 * كل عميل تثبيت Node، وهو ما يمنعه الشرط صراحة.
 */
const isDesktop = process.env.GOVMIND_DESKTOP === "1";

const nextConfig: NextConfig = {
  // لا نحتاج توليد AGENTS.md و CLAUDE.md تلقائيًا داخل frontend/.
  agentRules: false,

  ...(isDesktop
    ? {
        output: "export" as const,
        // ملفات تُفتح من الـRuntime بمسارات مجلدات — `/settings/` لا
        // `/settings.html`. هذا ما يخدمه `StaticFiles(html=True)`.
        trailingSlash: true,
        // لا مُحسِّن صور: يحتاج خادم Node، ولا وجود له على جهاز العميل.
        images: { unoptimized: true },
      }
    : {}),
};

export default nextConfig;
