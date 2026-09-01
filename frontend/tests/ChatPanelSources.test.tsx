/**
 * حراسة مصادر **أول** رد في محادثة جديدة.
 *
 * الخلل الذي تمنعه: أول رسالة تفتح محادثة على السيرفر، فيتغيّر
 * `conversationId` من `null` إلى معرّفها، فيُعاد تحميل الرسائل من
 * `/api/conversations/:id/messages` — وهي **لا تحفظ `sources`** — فتُستبدل
 * الرسالة المحلية بنسخة بلا مصادر وتختفي الشريحة من أول رد وحده.
 */

import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const sendChatMessage = vi.fn();
const listMessages = vi.fn();

// بدائل كاملة بلا `importOriginal`: لوحة المحادثة لا تستعمل من الوحدتين
// غير هذين، والاستيراد الأصلي يجرّ سلسلة وحدات لا حاجة إليها هنا.
vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status = 500) {
      super(message);
      this.status = status;
    }
  },
  sendChatMessage: (...args: unknown[]) => sendChatMessage(...args),
}));

vi.mock("@/lib/conversations", () => ({
  listMessages: (...args: unknown[]) => listMessages(...args),
}));

/**
 * **قيمة ثابتة الهوية عمدًا.**
 *
 * `useAuth` يعيد كائنًا واحدًا لا كائنًا جديدًا كل رسمة: اللوحة تبني
 * `useCallback` فوق `endExpiredSession`، وبديلٌ يولّد دالة جديدة كل مرة
 * يغيّر هوية الاعتماديات في كل رسمة فيعيد تشغيل الأثر بلا نهاية — وهو ما
 * يعلّق الاختبار بلا رسالة خطأ.
 */
const AUTH = {
  token: "test-token",
  endExpiredSession: () => {},
  user: { id: 1, full_name: "سارة", role: "admin", organization_name: "جهة" },
};

vi.mock("@/components/AuthProvider", () => ({ useAuth: () => AUTH }));

import ChatPanel from "@/components/ChatPanel";

const SOURCE = {
  file_id: 1,
  file_name: "تعميم_تجريبي.txt",
  chunk_index: 0,
  score: 0.31,
};

/** يحاكي `Workspace`: يتبنّى معرّف المحادثة الجديد كما يفعل فعلًا. */
function Harness() {
  const [conversationId, setConversationId] = useState<number | null>(null);
  return (
    <ChatPanel
      conversationId={conversationId}
      conversationTitle={null}
      onConversationCreated={setConversationId}
      onMessageSent={() => {}}
      onOpenSidebar={() => {}}
    />
  );
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  // نسخة السيرفر: بلا حقل sources إطلاقًا — وهذا أصل المشكلة.
  listMessages.mockResolvedValue({
    messages: [
      { id: 1, role: "user", content: "سؤال" },
      { id: 2, role: "assistant", content: "جواب من المودل" },
    ],
  });
});

async function sendFirstMessage() {
  render(<Harness />);
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "سؤال" } });
  await act(async () => {
    fireEvent.keyDown(input, { key: "Enter" });
  });
}

describe("مصادر أول رد", () => {
  it("تبقى ظاهرة بعد إنشاء المحادثة", async () => {
    sendChatMessage.mockResolvedValue({
      reply: "جواب من المودل",
      provider: "lmstudio",
      sources: [SOURCE],
      conversation_id: 7,
    });

    await sendFirstMessage();

    await waitFor(() => {
      expect(screen.getByText("جواب من المودل")).toBeDefined();
    });
    // الشريحة تحمل اسم الملف — هي ما كان يختفي.
    expect(screen.getByText(SOURCE.file_name)).toBeDefined();
  });

  it("لا يُعاد تحميل المحادثة التي أنشأها هذا المكوّن للتوّ", async () => {
    sendChatMessage.mockResolvedValue({
      reply: "جواب من المودل",
      provider: "lmstudio",
      sources: [SOURCE],
      conversation_id: 7,
    });

    await sendFirstMessage();

    await waitFor(() => expect(screen.getByText(SOURCE.file_name)).toBeDefined());
    // لو أُعيد التحميل لعادت نسخة السيرفر بلا مصادر.
    expect(listMessages).not.toHaveBeenCalled();
  });

  it("رد بلا مصادر لا يعرض شريحة", async () => {
    sendChatMessage.mockResolvedValue({
      reply: "جواب بلا مصادر",
      provider: "lmstudio",
      sources: [],
      conversation_id: 7,
    });

    await sendFirstMessage();

    await waitFor(() => expect(screen.getByText("جواب بلا مصادر")).toBeDefined());
    expect(screen.queryByText(SOURCE.file_name)).toBeNull();
  });
});

describe("تحميل محادثة قائمة", () => {
  it("ما زال يقرأ الرسائل من السيرفر", async () => {
    render(
      <ChatPanel
        conversationId={42}
        conversationTitle="محادثة سابقة"
        onConversationCreated={() => {}}
        onMessageSent={() => {}}
        onOpenSidebar={() => {}}
      />,
    );

    await waitFor(() => {
      expect(listMessages).toHaveBeenCalled();
      expect(screen.getByText("جواب من المودل")).toBeDefined();
    });
  });
});
