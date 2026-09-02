import type { ChatSource } from "@/lib/api";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** ملفات الجهة التي استُند إليها في الرد — لرسائل الإيجنت وحدها. */
  sources?: ChatSource[];
};

/**
 * فقاعة رسالة واحدة. رسائل الموظف تظهر بلون العلامة على جهة بداية السطر
 * (اليمين في RTL)، ورد الإيجنت على الجهة المقابلة.
 *
 * `justify-start` / `justify-end` منطقيتان في Flexbox فتتبعان `dir` تلقائيًا،
 * و`break-words` تمنع رابطًا أو كلمة طويلة من كسر التخطيط.
 */
export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={isUser ? "flex justify-start" : "flex justify-end"}>
      <div
        className={[
          "gv-bubble",
          isUser ? "gv-bubble--user" : "gv-bubble--assistant",
        ].join(" ")}
      >
        {message.content}

        {/* المصادر: الـAPI يعيدها منذ P2-02 ولم تكن الواجهة تعرضها، فيقرأ
            الموظف ردًّا مبنيًا على ملفات جهته بلا أن يعرف أيّها. أسماء
            الملفات مكرَّرة عبر المقاطع، فتُختصر إلى مجموعة فريدة. */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <div className="gv-sources">
            <span className="text-xs font-semibold text-muted">المصادر:</span>
            {[...new Set(message.sources.map((source) => source.file_name))].map(
              (name) => (
                <span key={name} className="gv-source-chip" title={name}>
                  <svg viewBox="0 0 20 20" aria-hidden="true" className="size-3 shrink-0">
                    <path
                      fill="currentColor"
                      d="M5 2.5h6.2L16 7.3V17a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 4 17V3a.5.5 0 0 1 .5-.5zm5.8 1.6V7.5h3.4z"
                    />
                  </svg>
                  <span>{name}</span>
                </span>
              ),
            )}
          </div>
        )}
      </div>
    </div>
  );
}
