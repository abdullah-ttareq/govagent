/**
 * المحادثات والرسائل — نداءات `/api/conversations` الموجودة فعلًا في
 * `backend/app/api/conversations.py`.
 *
 * لا يُرسل أي نداء هنا `organization_id` ولا `user_id`: الجهة والمالك
 * يُشتقان من رمز الدخول في السيرفر.
 */

import { apiRequest } from "@/lib/api";

/** يطابق `ConversationOut` في `backend/app/schemas/workspace.py`. */
export type Conversation = {
  id: number;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

/** يطابق `MessageOut`. */
export type Message = {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

export type PageMeta = { total: number; limit: number; offset: number };

type ConversationListResponse = {
  conversations: Conversation[];
  page: PageMeta;
};

type MessageListResponse = {
  messages: Message[];
  page: PageMeta;
};

export function listConversations(
  token: string,
  signal?: AbortSignal,
): Promise<ConversationListResponse> {
  return apiRequest<ConversationListResponse>("/api/conversations", {
    token,
    signal,
  });
}

export function createConversation(
  token: string,
  title?: string,
): Promise<Conversation> {
  return apiRequest<Conversation>("/api/conversations", {
    method: "POST",
    body: { title: title ?? null },
    token,
  });
}

export function renameConversation(
  token: string,
  id: number,
  title: string,
): Promise<Conversation> {
  return apiRequest<Conversation>(`/api/conversations/${id}`, {
    method: "PATCH",
    body: { title },
    token,
  });
}

/** يعيد 204 بلا جسم — لذلك `void`. */
export function deleteConversation(token: string, id: number): Promise<void> {
  return apiRequest<void>(`/api/conversations/${id}`, {
    method: "DELETE",
    token,
  });
}

export function listMessages(
  token: string,
  id: number,
  signal?: AbortSignal,
): Promise<MessageListResponse> {
  return apiRequest<MessageListResponse>(`/api/conversations/${id}/messages`, {
    token,
    signal,
  });
}

/** أقصى طول عنوان، مطابق لـ`MAX_TITLE_LENGTH` في الـBackend. */
export const MAX_TITLE_LENGTH = 300;

export function validateTitle(value: string): string | null {
  const cleaned = value.trim();
  if (!cleaned) return "عنوان المحادثة لا يمكن أن يكون فارغًا.";
  if (cleaned.length > MAX_TITLE_LENGTH) {
    return `العنوان أطول من ${MAX_TITLE_LENGTH} حرفًا.`;
  }
  return null;
}
