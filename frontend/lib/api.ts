/**
 * عميل بسيط للاتصال بـGovAgent Backend.
 * رابط السيرفر يأتي من NEXT_PUBLIC_BACKEND_URL، وسيصبح قابلًا للتعديل من
 * صفحة الإعدادات في مهمة FE-08.
 */

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export type ChatResponse = {
  reply: string;
  provider: string;
};

export async function sendChatMessage(message: string): Promise<ChatResponse> {
  let response: Response;

  try {
    response = await fetch(`${BACKEND_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
  } catch {
    throw new Error("تعذّر الاتصال بسيرفر الجهة. تأكد من تشغيل الـBackend.");
  }

  if (!response.ok) {
    throw new Error(
      response.status === 503
        ? "مزود المودل غير متاح حاليًا. راجع إعداد MODEL_PROVIDER."
        : "حدث خطأ أثناء إرسال الرسالة. حاول مرة أخرى.",
    );
  }

  return (await response.json()) as ChatResponse;
}
