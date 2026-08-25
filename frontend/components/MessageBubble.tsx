export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

/** فقاعة رسالة واحدة. رسائل الموظف تظهر بلون العلامة. */
export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className={isUser ? "flex justify-start" : "flex justify-end"}>
      <div
        className={[
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-7 sm:max-w-[70%]",
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
