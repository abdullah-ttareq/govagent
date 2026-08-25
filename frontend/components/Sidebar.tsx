import { mockConversations } from "@/lib/mock-conversations";

/** قائمة جانبية بسيطة تعرض محادثات تجريبية. */
export default function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-l border-border-subtle bg-surface md:flex">
      <div className="border-b border-border-subtle p-4">
        <h1 className="text-lg font-bold text-brand">GovAgent</h1>
        <p className="mt-1 text-xs text-foreground/60">المساعد الذكي للموظف</p>
      </div>

      <button
        type="button"
        className="m-3 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white transition hover:opacity-90"
      >
        + محادثة جديدة
      </button>

      <nav className="flex-1 overflow-y-auto px-3 pb-3">
        <p className="px-1 pb-2 text-xs font-medium text-foreground/50">
          المحادثات
        </p>
        <ul className="space-y-1">
          {mockConversations.map((conversation) => (
            <li key={conversation.id}>
              <button
                type="button"
                className="w-full rounded-lg px-3 py-2 text-right text-sm transition hover:bg-background"
              >
                <span className="block truncate">{conversation.title}</span>
                <span className="block text-xs text-foreground/50">
                  {conversation.updatedAt}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
