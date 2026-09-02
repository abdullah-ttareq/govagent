import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

/**
 * إعداد اختبارات الواجهة.
 *
 * jsdom لا متصفح حقيقي: هذه الاختبارات تحرس **منطق** الواجهة (أي خيارات
 * تُعرض، وهل تبقى المصادر بعد إنشاء المحادثة)، أما المظهر والقياسات فتُفحص
 * في المتصفح يدويًا — jsdom لا يحسب تخطيطًا ولا يطبّق CSS خارجيًا.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
