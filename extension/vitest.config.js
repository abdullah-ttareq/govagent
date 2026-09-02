import { defineConfig } from "vitest/config";

/**
 * إعداد اختبارات الإضافة.
 *
 * `jsdom` لأن النافذة صفحة HTML كاملة، و`setup.js` يركّب `chrome` المزيّف
 * قبل كل ملف: الوحدات تستورد `chrome.storage` عند التحميل، فتركيبه داخل
 * الاختبار وحده يأتي متأخرًا.
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.js"],
    include: ["tests/**/*.test.js"],
    restoreMocks: true,
  },
});
