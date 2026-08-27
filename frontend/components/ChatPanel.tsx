"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AttachmentTray, { type Attachment } from "@/components/AttachmentTray";
import { useAuth } from "@/components/AuthProvider";
import MessageBubble, { type ChatMessage } from "@/components/MessageBubble";
import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import ErrorNotice from "@/components/ui/ErrorNotice";
import { ApiError, sendChatMessage } from "@/lib/api";
import { listMessages } from "@/lib/conversations";
import { describeFailureDetail, type Failure } from "@/lib/errors";
import {
  ACCEPT_ATTRIBUTE,
  SUPPORTED_EXTENSIONS,
  uploadFile,
  validateFile,
} from "@/lib/files";

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
  const [failure, setFailure] = useState<Failure | null>(null);

  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  /** عمليات الرفع الجارية، ليُلغى أيّها عند إزالة ملفه. */
  const uploadControllers = useRef(new Map<string, AbortController>());
  /** عمق السحب: dragleave يُطلَق عند المرور فوق أي ابن، فلا يكفي عدّاد منطقي. */
  const dragDepth = useRef(0);

  const handleExpiredSession = useCallback(
    (caught: unknown) => {
      if (caught instanceof ApiError && caught.status === 401) void signOut();
    },
    [signOut],
  );

  const loadHistory = useCallback(
    (signal?: AbortSignal) => {
      if (!token || conversationId === null) return;

      setIsLoadingHistory(true);
      setFailure(null);

      listMessages(token, conversationId, signal)
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
          setFailure(describeFailureDetail(caught, "تعذّر تحميل رسائل المحادثة."));
          handleExpiredSession(caught);
        })
        .finally(() => setIsLoadingHistory(false));
    },
    [token, conversationId, handleExpiredSession],
  );

  // تبديل المحادثة يحمّل رسائلها المحفوظة من السيرفر.
  useEffect(() => {
    if (!token || conversationId === null) {
      // تفريغ اللوحة عند إلغاء اختيار المحادثة — مزامنة مع تغيّر خارجي
      // (اختيار في الشريط الجانبي) لا اشتقاق حالة من حالة.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessages([]);
      setFailure(null);
      return;
    }

    const controller = new AbortController();
    loadHistory(controller.signal);
    return () => controller.abort();
  }, [token, conversationId, loadHistory]);

  // التمرير إلى آخر رسالة بعد كل تغيّر في القائمة أو في حالة الانتظار.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, isSending]);

  // إلغاء كل رفع جارٍ عند مغادرة اللوحة، فلا يبقى طلب معلّق بلا مستقبِل.
  useEffect(() => {
    const controllers = uploadControllers.current;
    return () => {
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
    };
  }, []);

  /** حقل الكتابة يكبر مع النص إلى حدّ ثم يمرَّر. */
  function resizeInput() {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }

  /* --- المرفقات ---------------------------------------------------------- */

  function queueFiles(incoming: FileList | File[]) {
    const accepted: Attachment[] = [];
    const rejected: string[] = [];

    for (const file of Array.from(incoming)) {
      const invalid = validateFile(file);
      if (invalid) {
        rejected.push(invalid);
        continue;
      }
      accepted.push({
        // اسم الملف وحجمه ووقت الاختيار: كافٍ لتمييز ملفين في الطابور.
        id: `${file.name}-${file.size}-${Date.now()}-${accepted.length}`,
        file,
        status: "queued",
        progress: 0,
      });
    }

    // الملفات السليمة تُقبل ولو رُفض غيرها — رفض الدفعة كلها بسبب ملف
    // واحد يجبر الموظف على إعادة الاختيار من البداية.
    if (accepted.length > 0) {
      setAttachments((current) => [...current, ...accepted]);
    }
    setAttachmentError(rejected.length > 0 ? rejected.join(" ") : null);
  }

  function removeAttachment(id: string) {
    uploadControllers.current.get(id)?.abort();
    uploadControllers.current.delete(id);
    setAttachments((current) => current.filter((item) => item.id !== id));
    setAttachmentError(null);
  }

  function patchAttachment(id: string, patch: Partial<Attachment>) {
    setAttachments((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }

  /**
   * يرفع كل ملف في الطابور ويعيد `true` إن نجحت كلها.
   *
   * **الرفع قبل إرسال الرسالة، والفشل يوقف الإرسال:** الموظف يرفق ملفًا
   * ليُسأل عنه، فإرسال السؤال بعد فشل الرفع يعطيه جوابًا عن لا شيء.
   */
  async function uploadQueued(targetConversationId: number | null): Promise<boolean> {
    if (!token) return false;
    const pending = attachments.filter((item) => item.status !== "done");
    if (pending.length === 0) return true;

    let allSucceeded = true;

    // بالتسلسل لا بالتوازي: الرفع يستهلك عرض النطاق، ورفع أربعة ملفات معًا
    // على شبكة جهة بطيئة يجعل كل مؤشّر يزحف.
    for (const item of pending) {
      const controller = new AbortController();
      uploadControllers.current.set(item.id, controller);
      patchAttachment(item.id, { status: "uploading", progress: 0, error: null });

      try {
        const result = await uploadFile({
          token,
          file: item.file,
          conversationId: targetConversationId,
          signal: controller.signal,
          onProgress: (percent) => patchAttachment(item.id, { progress: percent }),
        });

        patchAttachment(item.id, {
          status: "done",
          progress: 100,
          // فشل الفهرسة لا يُفشل الرفع: الملف محفوظ لكنه خارج نتائج البحث.
          warning: result.indexing_error
            ? "الملف محفوظ لكن تعذّرت فهرسته، فلن يظهر في نتائج البحث."
            : null,
        });
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") {
          // أُزيل من الطابور أثناء رفعه — لا شيء يُحدَّث.
          continue;
        }
        allSucceeded = false;
        patchAttachment(item.id, {
          status: "failed",
          error: describeFailureDetail(caught, "تعذّر رفع الملف.").message,
        });
        handleExpiredSession(caught);
      } finally {
        uploadControllers.current.delete(item.id);
      }
    }

    return allSucceeded;
  }

  /* --- الإرسال ----------------------------------------------------------- */

  async function submit() {
    const text = input.trim();
    if (!text || isSending) return;

    setFailure(null);
    setIsSending(true);

    try {
      if (!(await uploadQueued(conversationId))) {
        setFailure({
          message: "تعذّر رفع بعض الملفات، فلم تُرسَل الرسالة. أزِل الملف المتعثّر أو أعد المحاولة.",
          action: "retry",
        });
        return;
      }

      // معرّف محلّي مؤقّت: الرسالة تظهر فورًا قبل أن يعطيها السيرفر معرّفها.
      const localId = `local-${Date.now()}`;
      setMessages((current) => [
        ...current,
        { id: localId, role: "user", content: text },
      ]);
      setInput("");
      requestAnimationFrame(resizeInput);

      try {
        const result = await sendChatMessage(text, token, conversationId);
        setMessages((current) => [
          ...current,
          { id: `${localId}-reply`, role: "assistant", content: result.reply },
        ]);
        setAttachments([]);
        // رسالة رفض ملف تخصّ اختيارًا انتهى؛ إبقاؤها بعد إرسال ناجح يقرأ
        // على أنه فشل.
        setAttachmentError(null);

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
        setFailure(describeFailureDetail(caught, "تعذّر إرسال الرسالة."));
        handleExpiredSession(caught);
      }
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
  const hasPendingUploads = attachments.some((item) => item.status === "uploading");

  return (
    <section
      className="relative flex min-w-0 flex-1 flex-col"
      onDragEnter={(event) => {
        // ملفات فقط: سحب نصّ داخل الصفحة يجب ألا يفتح منطقة الإفلات.
        if (!event.dataTransfer.types.includes("Files")) return;
        dragDepth.current += 1;
        setIsDragging(true);
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setIsDragging(false);
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        dragDepth.current = 0;
        setIsDragging(false);
        queueFiles(event.dataTransfer.files);
      }}
    >
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

      {isDragging && (
        <div className="gv-dropzone" aria-hidden="true">
          <p className="gv-dropzone__label">
            أفلت الملفات هنا
            <span className="mt-1 block text-xs font-normal">
              {SUPPORTED_EXTENSIONS.join(" · ")}
            </span>
          </p>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        {isLoadingHistory ? (
          <ul className="space-y-4" aria-label="جارٍ تحميل المحادثة">
            <li className="gv-skeleton ms-auto h-16 w-2/3" />
            <li className="gv-skeleton h-12 w-1/2" />
            <li className="gv-skeleton ms-auto h-20 w-3/4" />
          </ul>
        ) : isEmpty ? (
          <div className="mx-auto max-w-md py-10 text-center">
            <p className="text-lg font-bold">كيف أساعدك اليوم؟</p>
            <p className="mt-3 text-sm leading-relaxed text-muted">
              اسألني عن أي شيء يتعلق بعملك: صياغة خطاب، تلخيص مستند، ترجمة نص،
              أو سؤال برمجي. يمكنك إرفاق ملف لأجيبك من محتواه.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
          </div>
        )}

        {isSending && !hasPendingUploads && (
          <p
            className="mt-4 flex items-center gap-2 text-sm text-muted"
            role="status"
            aria-live="polite"
          >
            <span className="gv-spinner" aria-hidden="true" />
            جارٍ إعداد الرد…
          </p>
        )}

        {failure && (
          <ErrorNotice
            failure={failure}
            className="mt-4"
            onRetry={
              // تحميل المحادثة يُعاد، أما الرسالة فنصّها عاد إلى الحقل
              // فيعيدها الموظف بزر الإرسال نفسه.
              conversationId !== null && messages.length === 0
                ? () => loadHistory()
                : undefined
            }
          />
        )}

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
          <AttachmentTray items={attachments} onRemove={removeAttachment} />

          {attachmentError && (
            <Alert tone="error" className="mb-3">
              {attachmentError}
            </Alert>
          )}

          <div className="flex items-end gap-2">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPT_ATTRIBUTE}
              className="sr-only"
              onChange={(event) => {
                if (event.target.files) queueFiles(event.target.files);
                // تفريغ القيمة يسمح باختيار الملف نفسه مرة أخرى بعد إزالته.
                event.target.value = "";
              }}
            />

            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isSending}
              className="gv-icon-btn gv-icon-btn--lg"
              aria-label="إرفاق ملف"
              title={`إرفاق ملف (${SUPPORTED_EXTENSIONS.join("، ")})`}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
                <path
                  fill="currentColor"
                  d="M13.6 3.9a3.2 3.2 0 0 1 4.5 4.5l-7.6 7.6a4.7 4.7 0 1 1-6.6-6.6l6.9-6.9 1.1 1.1-6.9 6.9a3.2 3.2 0 0 0 4.5 4.5l7.6-7.6a1.7 1.7 0 0 0-2.4-2.4L7 12.5a.6.6 0 0 0 .9.9l6.4-6.4 1.1 1.1-6.4 6.4a2.1 2.1 0 1 1-3-3z"
                />
              </svg>
            </button>

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

            <Button
              type="submit"
              disabled={isSending || !input.trim()}
              isLoading={isSending}
              loadingLabel={hasPendingUploads ? "جارٍ الرفع…" : "جارٍ الإرسال…"}
            >
              إرسال
            </Button>
          </div>

          {/* الاختصار خارج الحقل لا داخله: نصّ توضيحي طويل يلتف داخل حقل
              بسطر واحد فيُقصّ، ويختفي أصلًا بمجرّد أن يكتب المستخدم. */}
          <p className="gv-hint mt-2 hidden sm:block" id="chat-input-hint">
            Enter للإرسال · Shift+Enter لسطر جديد · اسحب ملفًا وأفلته للإرفاق
          </p>
        </div>
      </form>
    </section>
  );
}
