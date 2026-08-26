"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import MessageBubble, { type ChatMessage } from "@/components/MessageBubble";
import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import { describeFailure } from "@/components/Workspace";
import { ApiError, sendChatMessage } from "@/lib/api";
import { listMessages } from "@/lib/conversations";

/** أقصى ارتفاع لحقل الكتابة قبل أن يمرَّر بدل أن يستمر في التمدد. */
const MAX_INPUT_HEIGHT = 160;

type ChatPanelProps = {
  conversationId: number | null;
  onConversationCreated: (id: number) => void;
  onMessageSent: () => void;
  onOpenSidebar: () => void;
};

export default function ChatPanel({
  conversationId,
  onConversationCreated,
  onMessageSent,
  onOpenSidebar,
}: ChatPanelProps) {
  const { token, signOut } = useAuth();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleExpiredSession = useCallback(
    (caught: unknown) => {
      if (caught instanceof ApiError && caught.status === 401) void signOut();
    },
    [signOut],
  );

  // تبديل المحادثة يحمّل رسائلها المحفوظة من السيرفر.
  useEffect(() => {
    if (!token || conversationId === null) {
      // تفريغ اللوحة عند إلغاء اختيار المحادثة — مزامنة مع تغيّر خارجي
      // (اختيار في الشريط الجانبي) لا اشتقاق حالة من حالة.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessages([]);
      setError(null);
      return;
    }

    const controller = new AbortController();
    setIsLoadingHistory(true);
    setError(null);

    listMessages(token, conversationId, controller.signal)
      .then((result) => {
        setMessages(
          result.messages.map((message) => ({
            id: String(message.id),
            role: message.role,
            content: message.content,
          })),
        );
      })
      .catch((caught: unknown) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(describeFailure(caught, "تعذّر تحميل رسائل المحادثة."));
        handleExpiredSession(caught);
      })
      .finally(() => setIsLoadingHistory(false));

    return () => controller.abort();
  }, [token, conversationId, handleExpiredSession]);

  // التمرير إلى آخر رسالة بعد كل تغيّر في القائمة أو في حالة الانتظار.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, isSending]);

  /** حقل الكتابة يكبر مع النص إلى حدّ ثم يمرَّر. */
  function resizeInput() {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }

  async function submit() {
    const text = input.trim();
    if (!text || isSending) return;

    // معرّف محلّي مؤقّت: الرسالة تظهر فورًا قبل أن يعطيها السيرفر معرّفها.
    const localId = `local-${Date.now()}`;
    setMessages((current) => [
      ...current,
      { id: localId, role: "user", content: text },
    ]);
    setInput("");
    setError(null);
    setIsSending(true);
    requestAnimationFrame(resizeInput);

    try {
      const result = await sendChatMessage(text, token, conversationId);
      setMessages((current) => [
        ...current,
        { id: `${localId}-reply`, role: "assistant", content: result.reply },
      ]);

      if (conversationId === null && result.conversation_id !== null) {
        // أول رسالة فتحت محادثة جديدة في السيرفر: تُتبنّى هنا ويُحدَّث الشريط.
        onConversationCreated(result.conversation_id);
      } else {
        onMessageSent();
      }
    } catch (caught) {
      // الرسالة الفاشلة تُزال ويُعاد نصّها إلى الحقل، فلا يفقد الموظف ما كتبه.
      setMessages((current) => current.filter((item) => item.id !== localId));
      setInput(text);
      setError(describeFailure(caught, "تعذّر إرسال الرسالة."));
      handleExpiredSession(caught);
    } finally {
      setIsSending(false);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter يرسل، وShift+Enter سطر جديد. isComposing يستثني لحظة تأليف
    // الحرف في محرّرات الإدخال، وإلا أُرسلت الرسالة في منتصف كلمة.
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  }

  const isEmpty = messages.length === 0 && !isLoadingHistory;

  return (
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="flex items-center gap-3 border-b border-border-subtle bg-surface px-4 py-3 md:hidden">
        <button
          type="button"
          onClick={onOpenSidebar}
          className="gv-icon-btn"
          aria-label="فتح قائمة المحادثات"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
            <path
              fill="currentColor"
              d="M3 5.25h14v1.5H3zm0 4h14v1.5H3zm0 4h14v1.5H3z"
            />
          </svg>
        </button>
        <p className="text-base font-bold text-brand">GovAgent</p>
      </header>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {isLoadingHistory ? (
          <p
            className="flex items-center gap-2 text-sm text-muted"
            role="status"
            aria-live="polite"
          >
            <span className="gv-spinner" aria-hidden="true" />
            جارٍ تحميل المحادثة…
          </p>
        ) : isEmpty ? (
          <div className="mx-auto max-w-md py-10 text-center">
            <p className="text-lg font-bold">كيف أساعدك اليوم؟</p>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              اسألني عن أي شيء يتعلق بعملك: صياغة خطاب، تلخيص مستند، ترجمة نص،
              أو سؤال برمجي.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </div>
        )}

        {isSending && (
          <p
            className="mt-4 flex items-center gap-2 text-sm text-muted"
            role="status"
            aria-live="polite"
          >
            <span className="gv-spinner" aria-hidden="true" />
            جارٍ إعداد الرد…
          </p>
        )}

        {error && <Alert tone="error" className="mt-4">{error}</Alert>}

        {/* هدف التمرير التلقائي — يبقى بعد كل شيء في مجرى المحتوى. */}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="border-t border-border-subtle bg-surface p-3 sm:p-4"
      >
        <div className="mx-auto max-w-3xl">
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                resizeInput();
              }}
              onKeyDown={handleKeyDown}
              rows={1}
              placeholder="اكتب رسالتك هنا…"
              aria-label="نص الرسالة"
              aria-describedby="chat-input-hint"
              className="gv-input flex-1 resize-none"
            />
            <Button type="submit" disabled={isSending || !input.trim()}>
              إرسال
            </Button>
          </div>

          {/* الاختصار خارج الحقل لا داخله: نصّ توضيحي طويل يلتف داخل حقل
              بسطر واحد فيُقصّ، ويختفي أصلًا بمجرّد أن يكتب المستخدم. */}
          <p className="gv-hint mt-2 hidden sm:block" id="chat-input-hint">
            Enter للإرسال · Shift+Enter لسطر جديد
          </p>
        </div>
      </form>
    </section>
  );
}
