export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
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
          "max-w-[85%] whitespace-pre-wrap break-words rounded-lg px-4 py-3 text-sm sm:max-w-[70%]",
          isUser
            ? "bg-brand text-white"
            : "border border-border-subtle bg-surface text-foreground",
        ].join(" ")}
      >
        {message.content}
      </div>
    </div>
  );
}
