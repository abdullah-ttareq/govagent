"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Alert from "@/components/ui/Alert";
import Button from "@/components/ui/Button";
import ThemeToggle from "@/components/ThemeToggle";
import {
  RUNTIME_OFFLINE_MESSAGE,
  RuntimeError,
  SUBSCRIPTION_LABELS,
  fetchSession,
  formatBytes,
  recheckSession,
  sendMessage,
  createConversation,
  deleteConversation,
  fetchConversation,
  listConversations,
  type ConversationSummary,
  type RuntimeSession,
} from "@/lib/runtime-client";

/**
 * تطبيق GovMind المثبَّت على جهاز العميل.
 *
 * ⚠️ **لا نموذج تسجيل دخول في هذا الملف ولا في شيء يستورده.** هذا هو
 * العطل الذي يعالجه: كان التطبيق المثبَّت يفتح `/login/` ويطلب بريدًا
 * وكلمة مرور من عميل **سجّل دخوله في الإضافة قبل قليل**، ثم يردّ على
 * الإرسال بـ«Method Not Allowed». الصحيح أن الربط قد تمّ، وأن التطبيق
 * يفتح مباشرة.
 *
 * **مصدر الحقيقة الوحيد:** `GET /api/app/session` من الـRuntime على الأصل
 * نفسه. `linked` تقول إن كان استبدال جلسة التركيب قد تمّ:
 *
 * * `linked === false` ⇒ تعليمة واحدة وزرّ «إعادة التحقق». **لا نموذج
 *   دخول، ولا رسالة خطأ HTTP.**
 * * `linked === true` وجاهز ⇒ التطبيق مباشرة.
 * * بينهما ⇒ تقدّم التجهيز، بنصّ من الـRuntime لا مخترع هنا.
 *
 * ⚠️ **بلا أي ذكر لجهة أو مسؤول أو دور أو بريد عمل.** المنتج حساب فردي
 * واحد واشتراك واحد وجهاز فعّال واحد.
 *
 * ⚠️ **لا يصل هذا الملف بيان اعتماد الجهاز ولا يطلبه.** الـRuntime يحتفظ
 * به محميًّا بـDPAPI ويلصقه بطلباته في جانب الخادم.
 */

/**
 * فاصل قراءة الحالة أثناء انتظار الربط أو التجهيز — حين يتغيّر شيء فعلًا.
 */
const POLL_BUSY_MS = 3000;

/**
 * الفاصل بعد الجهوزية.
 *
 * **لا يُوقف الاستطلاع تمامًا:** الاشتراك قد ينتهي، أو يُستبدل الجهاز من
 * حاسب آخر، والتطبيق مفتوح أمام العميل. لكن لا شيء يتغيّر كل ثلاث ثوانٍ
 * في تلك الحالة، فالاستطلاع السريع يوقظ القرص بلا فائدة.
 */
const POLL_IDLE_MS = 60000;

type ChatTurn = { role: "user" | "assistant"; text: string };

export default function DesktopApp() {
  const [session, setSession] = useState<RuntimeSession | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [isChecking, setIsChecking] = useState(false);

  const load = useCallback(async (signal?: { aborted: boolean }) => {
    try {
      const next = await fetchSession();
      if (signal?.aborted) return;
      setSession(next);
      setFailure(null);
    } catch (caught) {
      if (signal?.aborted) return;
      setFailure(
        caught instanceof RuntimeError ? caught.message : RUNTIME_OFFLINE_MESSAGE,
      );
    }
  }, []);

  // اشتراك في نظام خارجي — خدمة GovMind المحلية — لا اشتقاق حالة من حالة:
  // قراءة أولى ثم استطلاع، وإلغاءٌ عند التفكيك.
  //
  // الفاصل يتبع ما ننتظره: سريعٌ ما دام هناك ما يتغيّر (ربط، أو تنزيل
  // مودل)، وبطيءٌ بعد الجهوزية.
  const interval = session?.is_ready ? POLL_IDLE_MS : POLL_BUSY_MS;

  useEffect(() => {
    const signal = { aborted: false };
    // القاعدة تمنع setState متزامنًا داخل الأثر تفاديًا للتصيير المتتالي.
    // هنا لا تزامن: `load` غير متزامنة ولا تكتب شيئًا قبل أن يعود الطلب
    // من الـRuntime — وهي الاشتراك نفسه، فلا موضع لها غير هذا.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(signal);

    const timer = setInterval(() => {
      if (signal.aborted) return;
      void load(signal);
    }, interval);

    return () => {
      signal.aborted = true;
      clearInterval(timer);
    };
  }, [load, interval]);

  const recheck = useCallback(async () => {
    setIsChecking(true);
    try {
      const next = await recheckSession();
      setSession(next);
      setFailure(null);
    } catch (caught) {
      setFailure(
        caught instanceof RuntimeError ? caught.message : RUNTIME_OFFLINE_MESSAGE,
      );
    } finally {
      setIsChecking(false);
    }
  }, []);

  // ⚠️ **المحادثة تملك الشاشة كلها، فتُرسم قبل الغلاف لا داخله.**
  //
  // كان التطبيق كله داخل `max-w-3xl mx-auto`، فبقي عمودًا ضيقًا في وسط
  // شاشة عريضة — والشريط الجانبي يزاحمه بدل أن يجاوره. الحالات الأخرى
  // (بانتظار الربط، التجهيز، التوقف) بطاقات قصيرة، والتوسيط يخدمها.
  const isReady =
    session !== null && session.linked && session.phase !== "blocked" && session.is_ready;

  if (isReady) {
    return (
      <Chat
        session={session}
        failure={failure}
        onRecheck={recheck}
        isChecking={isChecking}
      />
    );
  }

  return (
    <main className="flex h-dvh w-full flex-col overflow-hidden bg-background">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border-subtle px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="gv-brand__mark" aria-hidden="true">
            G
          </span>
          <h1 className="text-lg font-bold">GovMind</h1>
        </div>
        <ThemeToggle />
      </header>

      <div className="flex flex-1 items-center justify-center overflow-y-auto p-6">
        <div className="w-full max-w-lg">
          {failure ? (
            <Alert tone="error" className="mb-4">
              {failure}
            </Alert>
          ) : null}
          <Body session={session} onRecheck={recheck} isChecking={isChecking} />
        </div>
      </div>
    </main>
  );
}

function Body({
  session,
  onRecheck,
  isChecking,
}: {
  session: RuntimeSession | null;
  onRecheck: () => void;
  isChecking: boolean;
}) {
  if (session === null) {
    return (
      <p
        className="flex items-center gap-3 text-sm text-muted"
        role="status"
        aria-live="polite"
      >
        <span className="gv-spinner" aria-hidden="true" />
        جارٍ فتح GovMind…
      </p>
    );
  }

  // ① لم يكتمل الربط بعد — **الحالة التي كانت تعرض نموذج دخول ثانيًا**.
  if (!session.linked) {
    return <NotLinked onRecheck={onRecheck} isChecking={isChecking} />;
  }

  // ② الاشتراك لا يسمح: يُقال السبب كما جاء من الخادم، بلا اختراع.
  if (session.phase === "blocked") {
    return (
      <section className="rounded-lg border border-border-subtle bg-surface p-6">
        <h2 className="text-base font-bold">GovMind متوقف حاليًا</h2>
        <p className="mt-2 text-sm text-muted">{session.message}</p>
        <div className="mt-5">
          <Button
            variant="secondary"
            onClick={onRecheck}
            isLoading={isChecking}
            loadingLabel="جارٍ التحقق…"
          >
            إعادة التحقق
          </Button>
        </div>
      </section>
    );
  }

  // ③ مربوط ويجهّز نفسه: تقدّم حقيقي بنصّ الـRuntime.
  if (!session.is_ready) {
    return <Preparing session={session} onRecheck={onRecheck} isChecking={isChecking} />;
  }

  // ④ جاهز — **لا يصل هنا**: `DesktopApp` ترسم `Chat` قبل الغلاف لأنها
  // تملك الشاشة كلها. تبقى هذه الحارسة لئلا يعيد أحد ترتيب الفروع فيقع
  // على `undefined` بلا رسالة.
  return null;
}

/**
 * ⚠️ **الشاشة التي حلّت محلّ نموذج الدخول الثاني.**
 *
 * تقع حين يفتح العميل GovMind قبل أن يكتمل تسليم جلسة التركيب — بأن فتح
 * الاختصار قبل أن تنتهي الإضافة، أو أن التسليم تعثّر. لا تطلب شيئًا لا
 * يملكه: تقول أين يُكمل، وتعطيه زرًّا يعيد الفحص فورًا.
 */
function NotLinked({
  onRecheck,
  isChecking,
}: {
  onRecheck: () => void;
  isChecking: boolean;
}) {
  return (
    <section className="rounded-lg border border-border-subtle bg-surface p-6">
      <h2 className="text-base font-bold">أكمل تثبيت وربط GovMind</h2>
      <p className="mt-2 text-sm text-muted">
        أكمل تثبيت وربط GovMind من إضافة المتصفح.
      </p>
      <p className="mt-3 text-sm text-muted">
        لا حاجة إلى تسجيل الدخول هنا — حسابك مسجَّل في الإضافة، وهي تربط هذا
        الجهاز تلقائيًا. ستفتح هذه الصفحة على GovMind فور اكتمال الربط.
      </p>
      <div className="mt-5">
        <Button onClick={onRecheck} isLoading={isChecking} loadingLabel="جارٍ التحقق…">
          إعادة التحقق
        </Button>
      </div>
    </section>
  );
}

function Preparing({
  session,
  onRecheck,
  isChecking,
}: {
  session: RuntimeSession;
  onRecheck: () => void;
  isChecking: boolean;
}) {
  const percent = session.progress;
  const label =
    typeof percent === "number" && session.total_bytes > 0
      ? `${percent}٪ — ${formatBytes(session.downloaded_bytes)} من ${formatBytes(session.total_bytes)}`
      : typeof percent === "number"
        ? `${percent}٪`
        : "";

  return (
    <section className="rounded-lg border border-border-subtle bg-surface p-6">
      <h2 className="text-base font-bold">جارٍ تجهيز GovMind على هذا الجهاز</h2>
      <p className="mt-2 text-sm text-muted">{session.message}</p>

      <div
        className="gv-progress mt-5"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={typeof percent === "number" ? percent : undefined}
      >
        {/* مرحلة بلا نسبة (تحقّق أو تحميل في الذاكرة): نبضٌ ممتدّ لا رقم
            مخترع. عرض «٠٪» على عملية جارية يوهم بأن شيئًا لم يبدأ. */}
        <div
          className={`gv-progress__bar${typeof percent === "number" ? "" : " animate-pulse"}`}
          style={{ inlineSize: typeof percent === "number" ? `${percent}%` : "100%" }}
        />
      </div>
      {label ? <p className="mt-2 text-xs text-muted">{label}</p> : null}

      <div className="mt-5">
        <Button
          variant="secondary"
          onClick={onRecheck}
          isLoading={isChecking}
          loadingLabel="جارٍ التحقق…"
        >
          إعادة التحقق
        </Button>
      </div>
    </section>
  );
}

/** وقتٌ عربي موجز للشريط الجانبي: «الآن»، «قبل ٣ س»، ثم الساعة. */
function shortWhen(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.floor((Date.now() - then) / 60000);
  if (minutes < 1) return "الآن";
  if (minutes < 60) return `قبل ${minutes} د`;
  if (minutes < 24 * 60) return `قبل ${Math.floor(minutes / 60)} س`;
  return new Date(then).toLocaleTimeString("ar", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * عنوان المجموعة الزمنية في الشريط: «اليوم» ثم «الأمس» ثم «أقدم».
 *
 * التصميم المعتمد يفصل المحادثات بعناوين لا بخطوط. الحساب بالتقويم
 * المحلي لا بفارق ٢٤ ساعة: محادثةٌ عند منتصف الليل تصير «الأمس» بمجرد
 * تغيّر اليوم، وهو ما يتوقّعه القارئ.
 */
function dayBucket(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "أقدم";
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  if (then.getTime() >= startOfToday.getTime()) return "اليوم";
  if (then.getTime() >= startOfToday.getTime() - 86400000) return "الأمس";
  return "أقدم";
}

/** حلقة GovMind الذهبية — علامة المنتج في التصميم المعتمد. */
function BrandRing({ hollow = false }: { hollow?: boolean }) {
  return (
    <span
      className={`gv-brand__mark${hollow ? " gv-brand__mark--hollow" : ""}`}
      aria-hidden="true"
    />
  );
}

function Chat({
  session,
  failure,
  onRecheck,
  isChecking,
}: {
  session: RuntimeSession;
  failure: string | null;
  onRecheck: () => void;
  isChecking: boolean;
}) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // ⚠️ **القيمة الأولى من الجلسة لا من افتراض**: تُعرض قبل أول رسالة.
  const [isCloud, setIsCloud] = useState(session.cloud_mode === true);
  // ⚠️ **مصدر المحادثات هو الـRuntime لا `localStorage`.**
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (session.cloud_mode !== undefined) setIsCloud(session.cloud_mode);
  }, [session.cloud_mode]);

  // مربّع الكتابة ينمو مع النصّ حتى سقف، ثم يمرّر داخله.
  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 200)}px`;
  }, [draft]);

  useEffect(() => {
    if (!menuFor) return;
    const close = () => setMenuFor(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menuFor]);

  const refreshList = useCallback(async () => {
    try {
      const { conversations: items } = await listConversations();
      setConversations(items);
      return items;
    } catch {
      return [] as ConversationSummary[];
    }
  }, []);

  // ⚠️ **الاستعادة بعد التحديث**: بلا هذا تُظهر إعادةُ التحميل محادثة
  // فارغة رغم أن السجلّ محفوظ.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const items = await refreshList();
      if (cancelled || items.length === 0) return;
      const newest = items[0];
      setActiveId(newest.id);
      try {
        const full = await fetchConversation(newest.id);
        if (cancelled) return;
        setTurns(full.messages.map((m) => ({ role: m.role, text: m.content })));
      } catch {
        /* محادثة حُذفت من مكان آخر — تُترك فارغة */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshList]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns, isSending]);

  async function startNew() {
    setError(null);
    try {
      const created = await createConversation();
      setActiveId(created.id);
      setTurns([]);
      setDraft("");
      await refreshList();
    } catch (caught) {
      setError(
        caught instanceof RuntimeError ? caught.message : RUNTIME_OFFLINE_MESSAGE,
      );
    }
  }

  async function openConversation(id: string) {
    if (id === activeId) return;
    setError(null);
    try {
      const full = await fetchConversation(id);
      setActiveId(id);
      setTurns(full.messages.map((m) => ({ role: m.role, text: m.content })));
    } catch (caught) {
      setError(
        caught instanceof RuntimeError ? caught.message : RUNTIME_OFFLINE_MESSAGE,
      );
      await refreshList();
    }
  }

  async function confirmDelete(id: string) {
    setError(null);
    try {
      await deleteConversation(id);
      const items = await refreshList();
      if (id === activeId) {
        const next = items[0] ?? null;
        setActiveId(next?.id ?? null);
        setTurns(
          next
            ? (await fetchConversation(next.id)).messages.map((m) => ({
                role: m.role,
                text: m.content,
              }))
            : [],
        );
      }
    } catch (caught) {
      setError(
        caught instanceof RuntimeError ? caught.message : RUNTIME_OFFLINE_MESSAGE,
      );
    } finally {
      setPendingDelete(null);
    }
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || isSending) return;

    setTurns((current) => [...current, { role: "user", text: message }]);
    setDraft("");
    setError(null);
    setIsSending(true);

    try {
      let target = activeId;
      if (!target) {
        target = (await createConversation()).id;
        setActiveId(target);
      }
      const { reply, cloud } = await sendMessage(
        message,
        turns.map((turn) => ({ role: turn.role, content: turn.text })),
        target,
      );
      if (cloud !== undefined) setIsCloud(cloud);
      setTurns((current) => [...current, { role: "assistant", text: reply }]);
      await refreshList();
    } catch (caught) {
      setError(
        caught instanceof RuntimeError ? caught.message : RUNTIME_OFFLINE_MESSAGE,
      );
    } finally {
      setIsSending(false);
    }
  }

  /**
   * Enter يرسل، و Shift+Enter يفتح سطرًا.
   *
   * `isComposing` شرطٌ لازم: لوحات الإدخال العربية والصينية تستعمل Enter
   * لتثبيت الحرف، وإرسالٌ عندها يقطع الكلمة.
   */
  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  const status = session.subscription_status
    ? SUBSCRIPTION_LABELS[session.subscription_status] ?? session.subscription_status
    : "";
  const active = conversations.find((c) => c.id === activeId);
  const activeTitle = active?.title ?? "محادثة جديدة";

  // التجميع بالترتيب الوارد — الـRuntime يرتّب الأحدث أولًا، فتأتي
  // «اليوم» قبل «الأمس» طبعًا بلا فرز ثانٍ.
  const groups: { label: string; items: ConversationSummary[] }[] = [];
  for (const item of conversations) {
    const label = dayBucket(item.updated_at);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }

  const sidebar = (
    <div className="flex h-full w-70 shrink-0 flex-col bg-surface-sidebar">
      {/* رأس الشريط: المبدّل يسار، والهوية يمين — كما في التصميم. */}
      <div className="flex items-center justify-between gap-3 px-4 pb-4 pt-4">
        {/* ⚠️ ترتيب RTL: أول عنصر في الـDOM يقع **يمينًا**. الهوية أولًا
            لتكون في يمين الشريط كما في التصميم، والمبدّل آخرًا فيقع يسارًا. */}
        <div className="flex items-center gap-2.5">
          <BrandRing />
          <div className="text-start leading-tight">
            <div className="text-base font-bold">GovMind</div>
            <div className="text-[10px] tracking-[0.18em] text-muted">
              GOVERNMENT AI
            </div>
          </div>
        </div>
        <ThemeToggle />
      </div>

      <div className="px-4 pb-4">
        <button
          type="button"
          onClick={() => {
            setDrawerOpen(false);
            void startNew();
          }}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-3 text-sm font-semibold text-brand-contrast transition-opacity hover:opacity-90"
        >
          <span
            className="size-1.5 rounded-full bg-accent"
            aria-hidden="true"
          />
          محادثة جديدة
        </button>
      </div>

      <nav aria-label="المحادثات" className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
        {conversations.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted">لا محادثات بعد.</p>
        ) : null}

        {groups.map((group) => (
          <div key={group.label} className="mb-4">
            <p className="px-2 pb-1.5 text-[11px] text-muted">{group.label}</p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = item.id === activeId;
                return (
                  <li key={item.id} className="relative">
                    {pendingDelete === item.id ? (
                      /* ⚠️ تأكيد داخل السطر لا `confirm()`: نافذة المتصفح
                         المشروطة تجمّد الصفحة، والحذف لا رجعة فيه. */
                      <div className="rounded-xl border border-border-subtle bg-surface p-2.5">
                        <p className="mb-2 text-xs leading-5">
                          تُحذف «{item.title}» نهائيًا؟
                        </p>
                        <div className="flex gap-1.5">
                          <button
                            type="button"
                            className="flex-1 rounded-lg bg-danger px-2 py-1 text-xs text-danger-contrast"
                            onClick={() => void confirmDelete(item.id)}
                          >
                            حذف
                          </button>
                          <button
                            type="button"
                            className="flex-1 rounded-lg border border-border-subtle px-2 py-1 text-xs"
                            onClick={() => setPendingDelete(null)}
                          >
                            إلغاء
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* النشط: بطاقة مرتفعة بحدّ ذهبيّ على حافة البداية
                         (اليمين في RTL) — إبرازٌ بلا لون واسع. */
                      <div
                        className={
                          "group flex items-center rounded-xl transition-colors " +
                          (isActive
                            ? "border-s-2 border-accent bg-surface-raised shadow-sm"
                            : "hover:bg-surface-muted")
                        }
                      >
                        <button
                          type="button"
                          className="min-w-0 flex-1 px-3 py-2.5 text-start"
                          aria-current={isActive ? "true" : undefined}
                          onClick={() => {
                            setDrawerOpen(false);
                            void openConversation(item.id);
                          }}
                        >
                          <span
                            className={
                              "block truncate text-[13px] " +
                              (isActive ? "font-bold" : "")
                            }
                          >
                            {item.title}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-muted">
                            {shortWhen(item.updated_at)}
                          </span>
                        </button>

                        {/* ⚠️ «حذف» لا يظهر دائمًا — انظر التعليق في الإصدار
                            السابق: زرٌّ دائم يجعل الشريط قائمة إدارة. */}
                        <button
                          type="button"
                          aria-label={`خيارات ${item.title}`}
                          aria-haspopup="menu"
                          aria-expanded={menuFor === item.id}
                          className={
                            "me-1.5 shrink-0 rounded-md px-1.5 py-1 text-muted opacity-0 transition-opacity hover:text-foreground focus:opacity-100 group-hover:opacity-100 " +
                            (menuFor === item.id ? "opacity-100" : "")
                          }
                          onClick={(event) => {
                            event.stopPropagation();
                            setMenuFor(menuFor === item.id ? null : item.id);
                          }}
                        >
                          <span aria-hidden="true">⋯</span>
                        </button>

                        {menuFor === item.id ? (
                          <div
                            role="menu"
                            className="absolute end-2 top-full z-20 mt-1 w-32 overflow-hidden rounded-xl border border-border-subtle bg-surface-raised py-1 shadow-lg"
                          >
                            <button
                              type="button"
                              role="menuitem"
                              className="block w-full px-3 py-1.5 text-start text-xs text-danger hover:bg-surface-muted"
                              onClick={(event) => {
                                event.stopPropagation();
                                setMenuFor(null);
                                setPendingDelete(item.id);
                              }}
                            >
                              حذف المحادثة
                            </button>
                          </div>
                        ) : null}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* تذييل مضغوط: الحساب والاشتراك — بلا جهة ولا دور. */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-t border-border-subtle px-4 py-3">
        <span
          className="size-6 shrink-0 rounded-full border border-border-subtle bg-surface-muted"
          aria-hidden="true"
        />
        <div className="min-w-0 text-end">
          {session.account_email ? (
            <p className="truncate text-xs" dir="ltr" title={session.account_email}>
              {session.account_email}
            </p>
          ) : null}
          <p className="mt-0.5 truncate text-[11px] text-muted">
            {status}
            {session.device_name ? ` · ${session.device_name}` : ""}
          </p>
        </div>
      </div>
    </div>
  );

  return (
    /* التطبيق بطاقةٌ مستديرة على أرضية أغمق بدرجة — كما في التصميم. */
    <div className="h-dvh w-full overflow-hidden bg-background p-2 sm:p-3">
      <div className="flex h-full w-full overflow-hidden rounded-2xl border border-border-subtle bg-surface">
        {/* ⚠️ `sm` لا `lg`: نافذة GovMind المثبَّتة نحو ٧٦٧ بكسل. */}
        <aside className="hidden sm:flex">{sidebar}</aside>

        {drawerOpen ? (
          <div className="fixed inset-0 z-40 sm:hidden">
            <button
              type="button"
              aria-label="إغلاق قائمة المحادثات"
              className="absolute inset-0 bg-scrim"
              onClick={() => setDrawerOpen(false)}
            />
            <div className="absolute inset-y-0 end-0 shadow-xl">{sidebar}</div>
          </div>
        ) : null}

        <main className="flex min-w-0 flex-1 flex-col border-e border-border-subtle">
          <header className="flex shrink-0 items-center gap-3 px-5 py-3.5">
            <button
              type="button"
              aria-label="عرض المحادثات"
              className="rounded-md p-1.5 text-muted hover:text-foreground sm:hidden"
              onClick={() => setDrawerOpen(true)}
            >
              <span aria-hidden="true">☰</span>
            </button>

            {/* شريحة المحرّك: **معلومة حقيقية من الـRuntime**، لا رقم إصدار
                مكتوب. تقول للعميل أين يُعالَج نصّه قبل أن يكتب. */}
            <span className="hidden shrink-0 rounded-full border border-border-subtle px-3 py-1 text-[11px] text-muted sm:inline-flex">
              {isCloud ? "استدلال سحابي" : "معالجة على هذا الجهاز"}
            </span>

            <div className="min-w-0 flex-1 text-end">
              <h1 className="truncate text-sm font-bold">{activeTitle}</h1>
              {active ? (
                <p className="mt-0.5 truncate text-[11px] text-muted">
                  محادثة نشطة · {shortWhen(active.updated_at)}
                </p>
              ) : null}
            </div>
          </header>

          {failure ? (
            <div className="mx-auto w-full max-w-[820px] px-5 pb-2">
              <Alert tone="error">{failure}</Alert>
              <div className="mt-2">
                <Button
                  variant="secondary"
                  onClick={onRecheck}
                  isLoading={isChecking}
                  loadingLabel="جارٍ التحقق…"
                >
                  إعادة التحقق
                </Button>
              </div>
            </div>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto" aria-live="polite">
            {turns.length === 0 ? (
              <div className="flex h-full items-center justify-center px-6">
                <div className="max-w-md text-center">
                  <span className="mx-auto mb-4 block w-fit">
                    <BrandRing />
                  </span>
                  <h2 className="text-xl font-bold">كيف أساعدك اليوم؟</h2>
                  <p className="mt-2 text-sm leading-6 text-muted">
                    {/* ⚠️ الجملة تتبع مكان المعالجة الفعلي. */}
                    {isCloud
                      ? "تُعالَج الردود عبر خدمة استدلال سحابية، فيغادر نصّك هذا الجهاز."
                      : "المعالجة تتم على هذا الجهاز ولا يغادره نصّك."}
                  </p>
                </div>
              </div>
            ) : (
              <div className="mx-auto w-full max-w-[820px] px-5 py-6">
                {turns.map((turn, index) =>
                  turn.role === "user" ? (
                    /* المستخدم: فقاعة مصمتة بلون الفعل، محاذاة النهاية. */
                    <div key={index} className="mb-7 flex justify-start">
                      <div className="max-w-[80%] rounded-2xl bg-brand px-5 py-3 text-sm leading-7 text-brand-contrast">
                        <p className="whitespace-pre-wrap">{turn.text}</p>
                      </div>
                    </div>
                  ) : (
                    /* المساعد: اسمٌ وحلقة، ثم نصّ بعرض العمود بلا إطار. */
                    <div key={index} className="mb-8">
                      <div className="mb-2.5 flex items-center justify-start gap-2">
                        <BrandRing hollow />
                        <span className="text-xs font-bold">GovMind</span>
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-8">
                        {turn.text}
                      </p>
                    </div>
                  ),
                )}

                {isSending ? (
                  <p
                    className="flex items-center gap-2 text-sm text-muted"
                    role="status"
                  >
                    <span className="gv-spinner" aria-hidden="true" />
                    {isCloud
                      ? "جارٍ توليد الرد…"
                      : "جارٍ توليد الرد على هذا الجهاز…"}
                  </p>
                ) : null}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <div className="shrink-0 px-5 pb-4">
            <form onSubmit={submit} className="mx-auto w-full max-w-[820px]">
              {error ? (
                <Alert tone="error" className="mb-2">
                  {error}
                </Alert>
              ) : null}

              <div className="rounded-2xl border border-border-subtle bg-surface-raised px-4 pb-3 pt-3 focus-within:border-border-strong">
                <label className="sr-only" htmlFor="desktop-chat-input">
                  رسالتك
                </label>
                <textarea
                  id="desktop-chat-input"
                  ref={inputRef}
                  className="max-h-50 w-full resize-none border-0 bg-transparent text-sm leading-7 outline-none placeholder:text-muted"
                  value={draft}
                  rows={1}
                  placeholder="اكتب سؤالك…"
                  disabled={isSending}
                  onKeyDown={onKeyDown}
                  onChange={(event) => setDraft(event.target.value)}
                />
                <div className="mt-2 flex items-center justify-end">
                  <button
                    type="submit"
                    aria-label="إرسال"
                    disabled={isSending || draft.trim().length === 0}
                    className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-brand-contrast transition-opacity disabled:opacity-40"
                  >
                    {isSending ? (
                      <span className="gv-spinner" aria-hidden="true" />
                    ) : (
                      <svg
                        viewBox="0 0 24 24"
                        className="size-4"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M12 19V5M5 12l7-7 7 7" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>

              <p className="mt-2 text-center text-[11px] text-muted">
                Enter للإرسال · Shift+Enter لسطر جديد
              </p>
            </form>
          </div>
        </main>
      </div>
    </div>
  );
}
