/** محادثات تجريبية للعرض فقط — ستُستبدل بمحادثات حقيقية في مهمة FE-04. */

export type MockConversation = {
  id: string;
  title: string;
  updatedAt: string;
};

export const mockConversations: MockConversation[] = [
  { id: "1", title: "تلخيص تقرير الأداء الربعي", updatedAt: "اليوم" },
  { id: "2", title: "صياغة خطاب تعميم إداري", updatedAt: "أمس" },
  { id: "3", title: "ترجمة مذكرة تفاهم", updatedAt: "قبل ٣ أيام" },
];
