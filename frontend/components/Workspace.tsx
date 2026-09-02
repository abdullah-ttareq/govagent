"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import ChatPanel from "@/components/ChatPanel";
import Sidebar from "@/components/Sidebar";
import { ApiError } from "@/lib/api";
import {
  createConversation,
  deleteConversation,
  listConversations,
  renameConversation,
  type Conversation,
} from "@/lib/conversations";
import { describeFailureDetail, type Failure } from "@/lib/errors";

/**
 * مالك حالة مساحة العمل: قائمة المحادثات والمحادثة النشطة.
 *
 * الحالة هنا لا في `Sidebar` ولا في `ChatPanel` لأن الاثنين يقرآنها ويكتبان
 * فيها: إرسال رسالة في محادثة جديدة يضيف صفًّا إلى الشريط، وحذف صفّ من
 * الشريط يفرّغ لوحة الشات.
 */
export default function Workspace() {
  const { token, endExpiredSession } = useAuth();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [listFailure, setListFailure] = useState<Failure | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  /** جلسة انتهت أثناء العمل: تُنهى محليًا فيحوّل RequireAuth إلى /login. */
  const handleExpiredSession = useCallback(
    (caught: unknown) => {
      if (caught instanceof ApiError && caught.status === 401) endExpiredSession();
    },
    [endExpiredSession],
  );

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      if (!token) return;
      try {
        const result = await listConversations(token, signal);
        setConversations(result.conversations);
        setListFailure(null);
      } catch (caught) {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setListFailure(describeFailureDetail(caught, "تعذّر تحميل المحادثات."));
        handleExpiredSession(caught);
      } finally {
        setIsLoadingList(false);
      }
    },
    [token, handleExpiredSession],
  );

  useEffect(() => {
    const controller = new AbortController();
    // جلب أولي من السيرفر — النمط الذي تستثنيه القاعدة نفسها: مزامنة مع
    // نظام خارجي، والكتابة تحدث بعد انتهاء الطلب لا داخل التصيير.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  /** يُستدعى من لوحة الشات بعد أول رسالة في محادثة جديدة. */
  const adoptConversation = useCallback(
    (conversationId: number) => {
      setActiveId(conversationId);
      void refresh();
    },
    [refresh],
  );

  /** يحدّث ترتيب القائمة وعدّاد الرسائل بعد كل تبادل داخل محادثة قائمة. */
  const notifyMessageSent = useCallback(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = useCallback(async () => {
    if (!token) return;
    try {
      const conversation = await createConversation(token);
      setConversations((current) => [conversation, ...current]);
      setActiveId(conversation.id);
      setListFailure(null);
      setIsSidebarOpen(false);
    } catch (caught) {
      setListFailure(describeFailureDetail(caught, "تعذّر إنشاء المحادثة."));
      handleExpiredSession(caught);
    }
  }, [token, handleExpiredSession]);

  const handleRename = useCallback(
    async (id: number, title: string) => {
      if (!token) return;
      const updated = await renameConversation(token, id, title);
      setConversations((current) =>
        current.map((item) => (item.id === id ? updated : item)),
      );
    },
    [token],
  );

  const handleDelete = useCallback(
    async (id: number) => {
      if (!token) return;
      await deleteConversation(token, id);
      setConversations((current) => current.filter((item) => item.id !== id));
      // المحادثة المحذوفة كانت معروضة: تُفرَّغ اللوحة بدل عرض محتوى زائل.
      setActiveId((current) => (current === id ? null : current));
    },
    [token],
  );

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        isLoading={isLoadingList}
        failure={listFailure}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onSelect={(id) => {
          setActiveId(id);
          setIsSidebarOpen(false);
        }}
        onCreate={handleCreate}
        onRename={handleRename}
        onDelete={handleDelete}
        onRetry={() => {
          setIsLoadingList(true);
          void refresh();
        }}
      />

      <ChatPanel
        conversationId={activeId}
        conversationTitle={
          conversations.find((item) => item.id === activeId)?.title ?? null
        }
        onConversationCreated={adoptConversation}
        onMessageSent={notifyMessageSent}
        onOpenSidebar={() => setIsSidebarOpen(true)}
      />
    </div>
  );
}
