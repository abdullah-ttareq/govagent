"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import AttachmentTray, { type Attachment } from "@/components/AttachmentTray";
import { useAuth } from "@/components/AuthProvider";
import MessageBubble, { type ChatMessage } from "@/components/MessageBubble";
import Alert from "@/components/ui/Alert";
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

/**
 * أمثلة تملأ الحالة الفارغة وتشرح ما يصلح له الإيجنت.
 *
 * الضغط عليها يملأ حقل الكتابة **ولا يرسل**: الإرسال قرار الموظف، وبدء
 * محادثة بضغطة عابرة يفتح محادثات لم يقصدها.
 */
const SUGGESTIONS = [
  "اكتب خطابًا رسميًا لطلب إجازة",
  "لخّص لي هذا المستند في نقاط",
  "ما إجراءات اعتماد طلب داخلي؟",
  "أعد صياغة هذه الفقرة بلغة رسمية",
];

type ChatPanelProps = {
  conversationId: number | null;
  /** عنوان المحادثة المعروضة — يظهر في ترويسة اللوحة. */
  conversationTitle: string | null;
  onConversationCreated: (id: number) => void;
  onMessageSent: () => void;
  onOpenSidebar: () => void;
};

export default function ChatPanel({
  conversationId,
  conversationTitle,
  onConversationCreated,
  onMessageSent,
  onOpenSidebar,
}: ChatPanelProps) {
  const { token, endExpiredSession } = useAuth();

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
  /**
   * معرّف المحادثة التي أنشأتها هذه اللوحة للتوّ.
   *
   * **يمنع إعادة تحميلٍ يمحو مصادر أول رد.** أول رسالة تفتح محادثة جديدة،
   * فيتغيّر `conversationId` من `null` إلى معرّفها، فيُشغّل أثرُ التبديل
   * `loadHistory` فيستبدل الرسائل بنسخة السيرفر — ونسخة السيرفر **لا تحفظ
   * `sources`**، فتختفي شريحة المصادر من أول رد وحده بينما تبقى في كل رد
   * بعده (لأن المحادثة لا تتبدّل عندها فلا إعادة تحميل).
   *
   * الحالة المحلية هنا **أحدث** من نسخة السيرفر وتطابقها نصًّا، فتخطّي
   * التحميل مرة واحدة لا يفقد شيئًا ويحفظ المصادر.
   */
  const selfCreatedRef = useRef<number | null>(null);

  const handleExpiredSession = useCallback(
    (caught: unknown) => {
      if (caught instanceof ApiError && caught.status === 401) endExpiredSession();
    },
    [endExpiredSession],
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

    // المحادثة التي أنشأتها هذه اللوحة للتوّ: الرسائل معروضة أصلًا ومعها
    // مصادرها. تُستهلك العلامة مرة واحدة، فالعودة إلى المحادثة لاحقًا
    // تُحمّلها من السيرفر كأي محادثة أخرى.
    if (selfCreatedRef.current === conversationId) {
      selfCreatedRef.current = null;
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
          {
            id: `${localId}-reply`,
            role: "assistant",
            content: result.reply,
            sources: result.sources,
          },
        ]);
        setAttachments([]);
        // رسالة رفض ملف تخصّ اختيارًا انتهى؛ إبقاؤها بعد إرسال ناجح يقرأ
        // على أنه فشل.
        setAttachmentError(null);

        if (conversationId === null && result.conversation_id !== null) {
          // أول رسالة فتحت محادثة جديدة في السيرفر: تُتبنّى هنا ويُحدَّث الشريط.
          // تُرفع العلامة **قبل** التبنّي حتى يقرأها الأثر الناتج عنه.
          selfCreatedRef.current = result.conversation_id;
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
      {/* ترويسة واحدة للجوال والمكتب: زر الدرج للجوال وحده، والعنوان يخبر
          الموظف أيّ محادثة يقرأ بلا أن ينظر إلى الشريط الجانبي. */}
      <header className="flex items-center gap-3 border-b border-border-subtle bg-surface px-4 py-3">
        <button
          type="button"
          onClick={onOpenSidebar}
          className="gv-icon-btn md:hidden"
          aria-label="فتح قائمة المحادثات"
        >
          <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
            <path
              fill="currentColor"
              d="M3 5.25h14v1.5H3zm0 4h14v1.5H3zm0 4h14v1.5H3z"
            />
          </svg>
        </button>

        <p className="text-base font-bold md:hidden">GovMind</p>

        <div className="hidden min-w-0 md:block">
          <h1 className="truncate text-sm font-bold leading-tight">
            {conversationTitle ?? "محادثة جديدة"}
          </h1>
          <p className="text-xs text-muted">
            {conversationId === null
              ? "لم تُحفظ بعد — تُنشأ عند أول رسالة"
              : "محفوظة على سيرفر جهتك"}
          </p>
        </div>
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

      {/* الحالة الفارغة تتوسّط ارتفاع اللوحة بدل أن تتعلّق بأعلاها وتترك
          فراغًا شاسعًا تحتها. وعند وجود رسائل يعود التدفّق من الأعلى. */}
      <div
        className={`flex-1 overflow-y-auto p-4 sm:p-6 ${
          isEmpty && !isLoadingHistory ? "flex flex-col justify-center" : ""
        }`}
      >
        {/* عمود واحد بعرض محدود، يحاذي صندوق الكتابة أسفله: الرسائل الممتدة
            بعرض الشاشة كلها تفقد خيط المحادثة على الشاشات العريضة. */}
        <div className="mx-auto w-full max-w-3xl">
          {isLoadingHistory ? (
            <ul className="space-y-4" aria-label="جارٍ تحميل المحادثة">
              <li className="gv-skeleton ms-auto h-16 w-2/3" />
              <li className="gv-skeleton h-12 w-1/2" />
              <li className="gv-skeleton ms-auto h-20 w-3/4" />
            </ul>
          ) : isEmpty ? (
            <div className="text-center">
              {/* زخرفي: الحرف لا يحمل معنى لقارئ الشاشة، والعنوان تحته
                  يقول المقصود. */}
              <p className="gv-brand__mark mx-auto !size-11 !text-lg" aria-hidden="true">
                G
              </p>
              <p className="mt-4 text-xl font-bold">كيف أساعدك اليوم؟</p>
              <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
                اسألني عن أي شيء يتعلق بعملك، أو أرفق ملفًا لأجيبك من محتواه.
              </p>

              <ul className="mt-6 grid gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((suggestion) => (
                  <li key={suggestion} className="flex">
                    <button
                      type="button"
                      className="gv-suggestion w-full"
                      onClick={() => {
                        setInput(suggestion);
                        // التركيز بعد الرسم حتى يقيس الحقل ارتفاعه الجديد.
                        requestAnimationFrame(() => {
                          textareaRef.current?.focus();
                          resizeInput();
                        });
                      }}
                    >
                      {suggestion}
                    </button>
                  </li>
                ))}
              </ul>
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

          <div className="gv-composer">
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
              className="gv-composer__btn"
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
              className="gv-composer__input"
            />

            {/* أيقونة لا كلمة: زر بعرض «جارٍ الإرسال…» يتمدّد ويتقلّص مع
                الحالة فيقفز الصندوق. النص للقارئ في aria-label. */}
            <button
              type="submit"
              disabled={isSending || !input.trim()}
              className="gv-composer__btn gv-composer__send"
              aria-label={
                isSending
                  ? hasPendingUploads
                    ? "جارٍ الرفع…"
                    : "جارٍ الإرسال…"
                  : "إرسال"
              }
              title="إرسال"
              aria-busy={isSending || undefined}
            >
              {isSending ? (
                <span className="gv-spinner" aria-hidden="true" />
              ) : (
                <svg viewBox="0 0 20 20" aria-hidden="true" className="size-5">
                  {/* سهم نحو جهة البداية (اليمين في RTL) — اتجاه الإرسال. */}
                  <path
                    fill="currentColor"
                    d="M17.3 10.7 4.6 16.4a.7.7 0 0 1-1-.8L5.2 10 3.6 4.4a.7.7 0 0 1 1-.8l12.7 5.7a.75.75 0 0 1 0 1.4M6.4 10.75l-1 3.6 9.2-4.35-9.2-4.35 1 3.6H11a.75.75 0 0 1 0 1.5z"
                  />
                </svg>
              )}
            </button>
          </div>

          {/* الاختصار خارج الحقل لا داخله: نصّ توضيحي طويل يلتف داخل حقل
              بسطر واحد فيُقصّ، ويختفي أصلًا بمجرّد أن يكتب المستخدم. */}
          {/* مسافة سفلية تفصله عن حافة الشاشة: كان يلتصق بأسفلها على
              الشاشات القصيرة فيبدو مقصوصًا. */}
          <p className="gv-hint mt-2 mb-1 hidden sm:block" id="chat-input-hint">
            Enter للإرسال · Shift+Enter لسطر جديد · اسحب ملفًا وأفلته للإرفاق
          </p>
        </div>
      </form>
    </section>
  );
}
