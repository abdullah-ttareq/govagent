"use client";

import { useState } from "react";
import MessageBubble, { type ChatMessage } from "@/components/MessageBubble";
import { sendChatMessage } from "@/lib/api";

const initialMessages: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    content:
      "أهلًا بك في GovAgent. اسألني عن أي شيء يتعلق بعملك: صياغة خطاب، تلخيص مستند، ترجمة نص، أو سؤال برمجي.",
  },
];

export default function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isLoading) return;

    setMessages((current) => [
      ...current,
      { id: `u-${current.length}`, role: "user", content: text },
    ]);
    setInput("");
    setError(null);
    setIsLoading(true);

    try {
      const result = await sendChatMessage(text);
      setMessages((current) => [
        ...current,
        { id: `a-${current.length}`, role: "assistant", content: result.reply },
      ]);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "حدث خطأ غير متوقع.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <section className="flex min-h-dvh flex-1 flex-col">
      <header className="border-b border-border-subtle bg-surface px-4 py-3 md:hidden">
        <h1 className="text-base font-bold text-brand">GovAgent</h1>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {isLoading && (
          <p className="text-sm text-foreground/60">جارٍ إعداد الرد…</p>
        )}

        {error && (
          <p
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {error}
          </p>
        )}
      </div>

      <form
        onSubmit={handleSubmit}
        className="border-t border-border-subtle bg-surface p-3 sm:p-4"
      >
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            rows={2}
            placeholder="اكتب رسالتك هنا…"
            aria-label="نص الرسالة"
            className="flex-1 resize-none rounded-xl border border-border-subtle bg-background px-4 py-3 text-sm outline-none focus:border-brand"
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="rounded-xl bg-brand px-5 py-3 text-sm font-medium text-white transition hover:opacity-90 disabled:opacity-40"
          >
            إرسال
          </button>
        </div>
      </form>
    </section>
  );
}
