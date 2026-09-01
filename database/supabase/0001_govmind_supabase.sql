-- ============================================================================
-- GovMind — مخطط Supabase (PostgreSQL) — الهجرة رقم ١
--
-- **ملف واحد يُنفَّذ كما هو من Supabase SQL Editor.** انسخه كاملًا والصقه
-- واضغط Run. ينتهي بقسم اختبارات يثبت أن البيانات لا تتسرّب بين المستخدمين
-- ولا بين الجهات؛ فشل أي تأكيد فيه يُفشل الهجرة كلها ويتراجع عنها.
--
-- ----------------------------------------------------------------------------
-- المبادئ التي بُني عليها هذا المخطط
-- ----------------------------------------------------------------------------
-- ١) **المصادقة من `auth.users` وحدها.** لا يوجد عمود كلمة مرور في هذا الملف
--    ولا نظام تسجيل دخول مستقل. `public.profiles.id` هو **نفسه**
--    `auth.users.id`، فمن لا يملك حسابًا في `auth` لا يملك ملفًا هنا.
--
-- ٢) **كل صف مرتبط بـ`user_id` أو `organization_id` أو بكليهما.** لا يوجد
--    جدول واحد فيه صف «عائم» لا يُعرف صاحبه، لأن سياسة RLS تحتاج عمودًا
--    تقيس عليه، وصفٌ بلا مالك يعني صفًا بلا سياسة.
--
-- ٣) **RLS مفعّل على الجداول العشرة كلها، والافتراضي هو المنع.** تفعيل RLS
--    بلا سياسة يمنع كل شيء؛ ما يُسمح به مذكور صراحة في سياسة مكتوبة أدناه.
--
-- ٤) **`service_role` للـBackend وحده.** المفتاح لا يوضع في الواجهة ولا في
--    إضافة المتصفح إطلاقًا. هو يتجاوز RLS بحكم تعريفه، فوجوده في العميل
--    يُلغي كل ما في هذا الملف. العميل يستخدم `anon` ورمز المستخدم فقط.
--
-- ٥) **الاشتراك الواحد لجهاز واحد.** يفرضه فهرس فريد جزئي على
--    `device_activations` — قيد في القاعدة لا فحصٌ في الكود، فلا يمكن
--    الالتفاف عليه بطلبين متزامنين.
--
-- ٦) **لا تُخزَّن بصمة الجهاز الخام أبدًا.** العمود `device_id_hash` يقبل
--    تجزئة SHA-256 بست وستين خانة ست عشرية فقط، ويفرض ذلك قيد CHECK.
--
-- ----------------------------------------------------------------------------
-- المعرّفات: لماذا uuid للمستخدم و bigint لما عداه
-- ----------------------------------------------------------------------------
-- `auth.users.id` من نوع uuid ولا خيار في ذلك، فالمستخدم uuid في كل الجداول.
-- أما الجهات وما يتبعها فمعرّفاتها bigint مطابقةً لمخطط Oracle القائم
-- (`database/schema.sql`) ولنماذج الـBackend التي تتعامل مع أعداد صحيحة.
-- ولأن الـBackend يتعامل مع المستخدم بمعرّف عددي كذلك، يحمل `profiles`
-- عمودًا إضافيًا `app_user_id` عدديًا فريدًا — جسرٌ صريح ومعلَّق عليه، لا
-- معرّف ثانٍ منافس: **الهوية هي `id` الـuuid**، وكل سياسات RLS تقيس عليه.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- ٠) الإضافات
-- ----------------------------------------------------------------------------
-- pgcrypto لـgen_random_uuid() في الاختبارات أسفل الملف. متاحة افتراضيًا على
-- Supabase؛ السطر موجود ليعمل الملف على قاعدة PostgreSQL عادية كذلك.
create extension if not exists pgcrypto;


-- ----------------------------------------------------------------------------
-- ١) الأنواع المعدودة
-- ----------------------------------------------------------------------------
-- أنواع معدودة لا قيود CHECK نصية: قيمة خاطئة تُرفض عند الكتابة **وعند
-- تحليل الاستعلام**، والقائمة تظهر في أدوات القاعدة بلا قراءة الكود.

do $enums$
begin
  if not exists (select 1 from pg_type where typname = 'subscription_status') then
    -- الحالات الخمس المطلوبة. trial و active وحدهما يسمحان بالخدمة؛ الثلاث
    -- الباقية تمنعها لأسباب مختلفة يرى المستخدم لكل منها رسالة مختلفة.
    create type public.subscription_status as enum (
      'trial',      -- فترة تجريبية سارية
      'active',     -- اشتراك مدفوع ساري
      'expired',    -- انتهت مدته
      'suspended',  -- أُوقف إداريًا ويمكن استئنافه
      'cancelled'   -- أُلغي نهائيًا
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'member_role') then
    create type public.member_role as enum ('admin', 'employee');
  end if;

  if not exists (select 1 from pg_type where typname = 'message_role') then
    create type public.message_role as enum ('user', 'assistant');
  end if;

  if not exists (select 1 from pg_type where typname = 'file_status') then
    create type public.file_status as enum ('uploaded', 'processing', 'ready', 'failed');
  end if;
end
$enums$;


-- ----------------------------------------------------------------------------
-- ٢) الجداول
-- ----------------------------------------------------------------------------

-- ١/١٠ organizations — الجهة المشتركة في النظام.
-- الجدول الوحيد الذي لا يحمل organization_id: هو نفسه الجهة.
create table if not exists public.organizations (
  id          bigint generated always as identity primary key,
  name        text        not null check (length(btrim(name)) between 2 and 200),
  -- معرّف نصي قصير يُستخدم في الروابط، مثل: ministry-x
  slug        text        not null unique
              check (slug ~ '^[a-z0-9]([a-z0-9-]{0,58}[a-z0-9])?$'),
  is_active   boolean     not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

comment on table public.organizations is
  'الجهات الحكومية المشتركة. الجذر الذي تتفرّع منه كل بيانات النظام.';


-- ٢/١٠ profiles — الملف الشخصي، وهو امتداد auth.users لا بديل عنه.
--
-- id هو auth.users.id نفسه، و on delete cascade يجعل حذف الحساب من auth
-- يمحو ملفه هنا؛ لا يبقى ملف يتيم يشير إلى مستخدم غير موجود.
--
-- **لا عمود كلمة مرور هنا ولا في أي جدول في هذا الملف.**
create table if not exists public.profiles (
  id              uuid primary key references auth.users (id) on delete cascade,
  -- الجسر إلى نماذج الـBackend العددية. انظر تعليق المعرّفات أعلى الملف.
  app_user_id     bigint generated always as identity unique,
  organization_id bigint      not null references public.organizations (id) on delete restrict,
  email           text        not null check (position('@' in email) > 1),
  full_name       text        not null check (length(btrim(full_name)) between 2 and 200),
  role            public.member_role not null default 'employee',
  is_active       boolean     not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- البريد فريد على مستوى النظام لا داخل الجهة: تسجيل الدخول يبحث بالبريد
-- **قبل** أن تُعرف الجهة، فتكراره بين جهتين يجعل النظام يخمّن أيهما.
create unique index if not exists uq_profiles_email_lower
  on public.profiles (lower(email));

create index if not exists ix_profiles_organization
  on public.profiles (organization_id);

comment on table public.profiles is
  'امتداد auth.users ببيانات العمل. المصادقة كلها في auth — لا كلمات مرور هنا.';


-- ٣/١٠ organization_members — عضوية المستخدم في الجهة ودوره فيها.
--
-- **لماذا جدول مستقل و profiles.organization_id موجود؟** لأن الدور صفة
-- للعلاقة لا للشخص: المستخدم قد ينتقل بين جهات، ومسؤول في جهة ليس مسؤولًا
-- في غيرها. profiles.organization_id هي الجهة **الفعّالة** التي تُقرأ في
-- المسار السريع، وهذا الجدول هو مرجع الصلاحية الذي تقيس عليه سياسات RLS.
create table if not exists public.organization_members (
  id              bigint generated always as identity primary key,
  organization_id bigint      not null references public.organizations (id) on delete cascade,
  user_id         uuid        not null references public.profiles (id) on delete cascade,
  role            public.member_role not null default 'employee',
  created_at      timestamptz not null default now(),

  constraint uq_organization_members unique (organization_id, user_id)
);

create index if not exists ix_organization_members_user
  on public.organization_members (user_id);


-- ٤/١٠ subscriptions — اشتراك الجهة. صف واحد لكل جهة.
--
-- **الحالة والتاريخ يُفحصان معًا لا أحدهما.** لا يوجد Trigger يحوّل active
-- إلى expired عند مرور التاريخ، فالـBackend يفحص الاثنين: حالة سارية مع
-- تاريخ ماضٍ = منتهٍ.
create table if not exists public.subscriptions (
  id              bigint generated always as identity primary key,
  organization_id bigint      not null unique
                  references public.organizations (id) on delete cascade,
  status          public.subscription_status not null default 'trial',
  seats           integer     not null default 10 check (seats > 0),
  starts_at       timestamptz not null default now(),
  expires_at      timestamptz not null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint ck_subscriptions_window check (expires_at > starts_at)
);

comment on column public.subscriptions.status is
  'trial | active | expired | suspended | cancelled — يسمح بالخدمة أول اثنين فقط.';


-- ٥/١٠ device_activations — تفعيل الأجهزة. **جهاز واحد فعّال لكل اشتراك.**
--
-- الحدّ يفرضه الفهرس الفريد الجزئي uq_device_activations_one_active أدناه:
-- قيدٌ في القاعدة لا فحص في الكود. طلبان متزامنان لتفعيل جهازين ينجح أحدهما
-- ويفشل الآخر بخطأ تفرّد — لا يمكن أن ينجحا معًا مهما كان توقيتهما.
--
-- **تغيير الجهاز يحتاج إبطالًا من مسؤول:** الإبطال يملأ revoked_at، فيخرج
-- الصف من الفهرس الجزئي ويصير مكان جهاز جديد شاغرًا. الصف نفسه **يبقى**
-- ولا يُحذف: تاريخ الأجهزة جزء من سجل الاشتراك.
create table if not exists public.device_activations (
  id              bigint generated always as identity primary key,
  subscription_id bigint      not null references public.subscriptions (id) on delete cascade,

  -- ⚠️ **تجزئة لا بصمة.** بصمة الجهاز الخام لا تدخل القاعدة إطلاقًا: يجزّئها
  -- الـBackend بـSHA-256 مع مِلح سرّي من متغيرات البيئة، ويخزّن الناتج وحده.
  -- القيد يرفض أي قيمة ليست ٦٤ خانة ست عشرية، فلا يمكن تمرير نص خام سهوًا.
  device_id_hash  text        not null check (device_id_hash ~ '^[0-9a-f]{64}$'),

  -- اسم يعرضه المستخدم ليميّز جهازه. نص وصفي لا معرّف.
  device_name     text        not null default 'جهاز غير مسمّى'
                  check (length(btrim(device_name)) between 1 and 120),

  activated_at    timestamptz not null default now(),
  last_seen_at    timestamptz not null default now(),
  revoked_at      timestamptz
);

-- **جوهر «جهاز واحد لكل اشتراك».** الفهرس جزئي على الصفوف غير المبطلة وحدها،
-- فيسمح بأي عدد من الأجهزة المبطلة تاريخيًا ويمنع أكثر من فعّال واحد.
create unique index if not exists uq_device_activations_one_active
  on public.device_activations (subscription_id)
  where revoked_at is null;

create index if not exists ix_device_activations_hash
  on public.device_activations (subscription_id, device_id_hash);


-- ٦/١٠ conversations — محادثات الموظف.
--
-- **المحادثة خاصة بصاحبها لا بجهته:** زميل في الجهة نفسها — ولو كان
-- مسؤولها — لا يراها. organization_id محفوظ للفهرسة والحذف المتتالي، لكن
-- سياسة RLS تقيس على user_id.
create table if not exists public.conversations (
  id              bigint generated always as identity primary key,
  user_id         uuid        not null references public.profiles (id) on delete cascade,
  organization_id bigint      not null references public.organizations (id) on delete cascade,
  title           text        not null default 'محادثة جديدة'
                  check (length(btrim(title)) between 1 and 200),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists ix_conversations_user
  on public.conversations (user_id, updated_at desc);


-- ٧/١٠ messages — رسائل المحادثة.
--
-- user_id و organization_id مكرّران من المحادثة عمدًا: بدونهما تحتاج كل
-- سياسة RLS على هذا الجدول استعلامًا فرعيًا على conversations لكل صف، وهو
-- أبطأ وأهشّ. التكرار يجعل السياسة مقارنة عمود واحد.
create table if not exists public.messages (
  id              bigint generated always as identity primary key,
  conversation_id bigint      not null references public.conversations (id) on delete cascade,
  user_id         uuid        not null references public.profiles (id) on delete cascade,
  organization_id bigint      not null references public.organizations (id) on delete cascade,
  role            public.message_role not null,
  content         text        not null check (length(content) > 0),
  -- المصادر التي استند إليها الرد (أسماء ملفات ومقاطع). فارغ لرسائل المستخدم.
  sources         jsonb       not null default '[]'::jsonb,
  created_at      timestamptz not null default now()
);

create index if not exists ix_messages_conversation
  on public.messages (conversation_id, created_at);


-- ٨/١٠ files — الملفات المرفوعة. السجل هنا والمحتوى على التخزين.
create table if not exists public.files (
  id              bigint generated always as identity primary key,
  user_id         uuid        not null references public.profiles (id) on delete cascade,
  organization_id bigint      not null references public.organizations (id) on delete cascade,
  conversation_id bigint      references public.conversations (id) on delete set null,
  filename        text        not null check (length(btrim(filename)) between 1 and 255),
  content_type    text        not null,
  size_bytes      bigint      not null check (size_bytes > 0),
  storage_path    text        not null,
  status          public.file_status not null default 'uploaded',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists ix_files_user
  on public.files (user_id, created_at desc);


-- ٩/١٠ file_chunks — مقاطع الملف ومتجهاتها، للبحث الدلالي.
--
-- **المتجه jsonb لا vector:** إضافة pgvector قد لا تكون مفعّلة على كل مشروع،
-- وفشل جدول واحد يُفشل الهجرة كلها. التحويل إلى vector خطوة لاحقة مستقلة
-- عندما يُفعَّل البحث المتجهي على Supabase.
create table if not exists public.file_chunks (
  id              bigint generated always as identity primary key,
  file_id         bigint      not null references public.files (id) on delete cascade,
  user_id         uuid        not null references public.profiles (id) on delete cascade,
  organization_id bigint      not null references public.organizations (id) on delete cascade,
  chunk_index     integer     not null check (chunk_index >= 0),
  content         text        not null check (length(content) > 0),
  embedding       jsonb,
  created_at      timestamptz not null default now(),

  constraint uq_file_chunks_index unique (file_id, chunk_index)
);

create index if not exists ix_file_chunks_organization
  on public.file_chunks (organization_id);


-- ١٠/١٠ audit_logs — سجل التدقيق. **إضافة فقط.**
--
-- لا سياسة UPDATE ولا DELETE عليه لأي دور عميل: سجلٌ يمكن تعديله ليس سجل
-- تدقيق. الكتابة من الـBackend بـservice_role وحده.
create table if not exists public.audit_logs (
  id              bigint generated always as identity primary key,
  organization_id bigint      not null references public.organizations (id) on delete cascade,
  -- null إن كان الفاعل النظام نفسه لا مستخدمًا (مهمة مجدولة مثلًا).
  user_id         uuid        references public.profiles (id) on delete set null,
  action          text        not null check (length(btrim(action)) between 1 and 100),
  entity_type     text,
  entity_id       text,
  metadata        jsonb       not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);

create index if not exists ix_audit_logs_org_time
  on public.audit_logs (organization_id, created_at desc);


-- ----------------------------------------------------------------------------
-- ٣) دوال مساعدة لسياسات RLS
-- ----------------------------------------------------------------------------
-- **لماذا SECURITY DEFINER؟** سياسة على `profiles` تستعلم عن `profiles`
-- تدخل في **تكرار لا نهائي**: تقييم السياسة يشغّل الاستعلام الذي يشغّل
-- السياسة. الدالة بـSECURITY DEFINER تقرأ الجدول بصلاحيات مالكها فتتجاوز
-- RLS، فينكسر التكرار. هذا استثناء مقصود ومحصور في ثلاث دوال للقراءة فقط،
-- كل منها تجيب سؤالًا واحدًا عن **صاحب الطلب نفسه** ولا تُرجع بيانات غيره.
--
-- `search_path` مثبّت على أسماء صريحة: دالة SECURITY DEFINER بمسار بحث
-- قابل للتغيير ثغرة معروفة — يستطيع المستدعي زرع جدول باسم مطابق.

create or replace function public.current_org_id()
returns bigint
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select organization_id from public.profiles where id = auth.uid();
$$;

comment on function public.current_org_id() is
  'جهة صاحب الطلب الفعّالة، أو NULL إن لم يكن له ملف. أساس عزل الجهات.';


create or replace function public.is_org_member(target_org bigint)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from public.organization_members
    where organization_id = target_org
      and user_id = auth.uid()
  );
$$;


create or replace function public.is_org_admin(target_org bigint)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1
    from public.organization_members
    where organization_id = target_org
      and user_id = auth.uid()
      and role = 'admin'
  );
$$;

comment on function public.is_org_admin(bigint) is
  'هل صاحب الطلب مسؤول في هذه الجهة تحديدًا؟ مسؤول جهة ليس مسؤولًا في غيرها.';

-- الدوال متاحة للعميل المسجَّل وحده. `anon` لا يحتاجها: زائر بلا auth.uid()
-- تعيد له كل دالة NULL أو false على أي حال، ومنعها يقلّل سطح التعرّض.
revoke all on function public.current_org_id() from public, anon;
revoke all on function public.is_org_member(bigint) from public, anon;
revoke all on function public.is_org_admin(bigint) from public, anon;
grant execute on function public.current_org_id() to authenticated, service_role;
grant execute on function public.is_org_member(bigint) to authenticated, service_role;
grant execute on function public.is_org_admin(bigint) to authenticated, service_role;


-- ----------------------------------------------------------------------------
-- ٤) تفعيل RLS
-- ----------------------------------------------------------------------------
-- **`force row level security` كذلك، لا `enable` وحدها.** بدون `force` لا
-- تُطبَّق السياسات على **مالك الجدول** — ولو تسرّب اتصال بصلاحيات المالك
-- لسقط العزل كله بصمت. مع `force` يخضع المالك للسياسات أيضًا، ويبقى
-- `service_role` وحده متجاوزًا (له سمة BYPASSRLS بحكم تعريفه في Supabase).

alter table public.organizations        enable row level security;
alter table public.organizations        force  row level security;
alter table public.profiles             enable row level security;
alter table public.profiles             force  row level security;
alter table public.organization_members enable row level security;
alter table public.organization_members force  row level security;
alter table public.subscriptions        enable row level security;
alter table public.subscriptions        force  row level security;
alter table public.device_activations   enable row level security;
alter table public.device_activations   force  row level security;
alter table public.conversations        enable row level security;
alter table public.conversations        force  row level security;
alter table public.messages             enable row level security;
alter table public.messages             force  row level security;
alter table public.files                enable row level security;
alter table public.files                force  row level security;
alter table public.file_chunks          enable row level security;
alter table public.file_chunks          force  row level security;
alter table public.audit_logs           enable row level security;
alter table public.audit_logs           force  row level security;


-- ----------------------------------------------------------------------------
-- ٥) السياسات
-- ----------------------------------------------------------------------------
-- تُحذف قبل الإنشاء ليكون الملف قابلًا لإعادة التنفيذ بلا خطأ تكرار.
--
-- **كل سياسة هنا لدور `authenticated` وحده.** `anon` بلا سياسة واحدة، فهو
-- ممنوع من الجداول العشرة كلها — وهذا مقصود: لا شيء في هذا النظام عام.

-- ٥-١) organizations ------------------------------------------------------
drop policy if exists organizations_select_member on public.organizations;
create policy organizations_select_member
  on public.organizations for select to authenticated
  using (public.is_org_member(id));

-- التعديل لمسؤول الجهة **داخل جهته وحدها**. `with check` بالشرط نفسه يمنع
-- تحويل الصف إلى جهة أخرى بعد التعديل.
drop policy if exists organizations_update_admin on public.organizations;
create policy organizations_update_admin
  on public.organizations for update to authenticated
  using (public.is_org_admin(id))
  with check (public.is_org_admin(id));

-- لا سياسة INSERT ولا DELETE: تجهيز جهة جديدة وحذفها عمليتان يقوم بهما
-- الـBackend بـservice_role. لا يستطيع أي عميل إنشاء جهة لنفسه.


-- ٥-٢) profiles -----------------------------------------------------------
-- «المستخدم يصل إلى ملفه هو وحده»: القراءة والتعديل مقيّدان بـauth.uid().
drop policy if exists profiles_select_self on public.profiles;
create policy profiles_select_self
  on public.profiles for select to authenticated
  using (id = auth.uid());

-- المسؤول يقرأ ملفات موظفي **جهته** — يحتاج ذلك لإدارتهم. سياسة منفصلة لا
-- شرط `or` داخل الأولى: سياستا SELECT تُجمعان بـOR، والفصل يبقي كل قاعدة
-- مقروءة وقابلة للحذف وحدها.
drop policy if exists profiles_select_org_admin on public.profiles;
create policy profiles_select_org_admin
  on public.profiles for select to authenticated
  using (public.is_org_admin(organization_id));

-- التعديل على النفس فقط، و`with check` يمنع أمرين معًا: نقل الملف إلى جهة
-- أخرى، وأن يرفع المستخدم نفسه إلى admin — الدور يُغيَّر من الـBackend.
drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self
  on public.profiles for update to authenticated
  using (id = auth.uid())
  with check (
    id = auth.uid()
    and organization_id = public.current_org_id()
    and role = (select p.role from public.profiles p where p.id = auth.uid())
  );

-- لا سياسة INSERT: إنشاء الملف يتبع إنشاء الحساب في auth، ويقوم به
-- الـBackend بـservice_role بعد ربطه بجهته.


-- ٥-٣) organization_members ----------------------------------------------
drop policy if exists organization_members_select on public.organization_members;
create policy organization_members_select
  on public.organization_members for select to authenticated
  using (public.is_org_member(organization_id));

-- إدارة العضويات لمسؤول الجهة، داخل جهته وحدها في الاتجاهين.
drop policy if exists organization_members_write_admin on public.organization_members;
create policy organization_members_write_admin
  on public.organization_members for all to authenticated
  using (public.is_org_admin(organization_id))
  with check (public.is_org_admin(organization_id));


-- ٥-٤) subscriptions ------------------------------------------------------
-- **قراءة فقط للعميل.** عضو الجهة يرى اشتراكها ليعرف حالته وتاريخ انتهائه.
drop policy if exists subscriptions_select_member on public.subscriptions;
create policy subscriptions_select_member
  on public.subscriptions for select to authenticated
  using (public.is_org_member(organization_id));

-- **لا سياسة كتابة لأي دور عميل — ولا حتى للمسؤول.** تجديد الاشتراك وتغيير
-- حالته وعدد مقاعده قرار من يقدّم الخدمة لا من يستهلكها؛ لو مَلَكه مسؤول
-- الجهة لمنح نفسه مقاعد ومدة بلا حد. يكتبها الـBackend بـservice_role.


-- ٥-٥) device_activations -------------------------------------------------
-- عضو الجهة يرى أجهزة اشتراكه: منها يعرف أن حسابه مفعّل على جهاز آخر.
drop policy if exists device_activations_select_member on public.device_activations;
create policy device_activations_select_member
  on public.device_activations for select to authenticated
  using (
    exists (
      select 1
      from public.subscriptions s
      where s.id = device_activations.subscription_id
        and public.is_org_member(s.organization_id)
    )
  );

-- **الإبطال وحده متاح للمسؤول، والتفعيل ليس كذلك.** UPDATE بشرط `with
-- check` يمنع تعديل التجزئة أو الاشتراك: المسؤول يبطل جهازًا في جهته
-- فيسمح لموظفه بتفعيل جهاز بديل. التفعيل نفسه يمرّ بالـBackend لأنه يحتاج
-- تجزئة البصمة بمِلح لا يملكه العميل.
drop policy if exists device_activations_revoke_admin on public.device_activations;
create policy device_activations_revoke_admin
  on public.device_activations for update to authenticated
  using (
    exists (
      select 1
      from public.subscriptions s
      where s.id = device_activations.subscription_id
        and public.is_org_admin(s.organization_id)
    )
  )
  with check (
    exists (
      select 1
      from public.subscriptions s
      where s.id = device_activations.subscription_id
        and public.is_org_admin(s.organization_id)
    )
  );

-- لا INSERT ولا DELETE لأي عميل: التفعيل من الـBackend، والحذف ممنوع لأن
-- تاريخ الأجهزة جزء من سجل الاشتراك.


-- ٥-٦) conversations ------------------------------------------------------
-- **المالك وحده.** لا استثناء للمسؤول: محادثات الموظف ليست بيانات إدارية.
drop policy if exists conversations_own on public.conversations;
create policy conversations_own
  on public.conversations for all to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    -- يمنع إنشاء محادثة منسوبة إلى جهة أخرى.
    and organization_id = public.current_org_id()
  );


-- ٥-٧) messages -----------------------------------------------------------
drop policy if exists messages_own on public.messages;
create policy messages_own
  on public.messages for all to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and organization_id = public.current_org_id()
    -- والمحادثة نفسها ملك المستخدم: يمنع دسّ رسالة في محادثة غيره.
    and exists (
      select 1 from public.conversations c
      where c.id = messages.conversation_id and c.user_id = auth.uid()
    )
  );


-- ٥-٨) files --------------------------------------------------------------
drop policy if exists files_own on public.files;
create policy files_own
  on public.files for all to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and organization_id = public.current_org_id()
  );


-- ٥-٩) file_chunks --------------------------------------------------------
drop policy if exists file_chunks_own on public.file_chunks;
create policy file_chunks_own
  on public.file_chunks for all to authenticated
  using (user_id = auth.uid())
  with check (
    user_id = auth.uid()
    and organization_id = public.current_org_id()
  );


-- ٥-١٠) audit_logs --------------------------------------------------------
-- **قراءة لمسؤول الجهة وحده، ولا كتابة لأحد.** سجلٌ يستطيع الفاعل تعديله
-- ليس سجل تدقيق: الكتابة من الـBackend بـservice_role حصرًا.
drop policy if exists audit_logs_select_admin on public.audit_logs;
create policy audit_logs_select_admin
  on public.audit_logs for select to authenticated
  using (public.is_org_admin(organization_id));


-- ----------------------------------------------------------------------------
-- ٦) الصلاحيات
-- ----------------------------------------------------------------------------
-- الصلاحية شرط **أول**، وRLS شرط **ثانٍ**: من لا يملك GRANT لا تُقيَّم له
-- سياسة أصلًا. تُمنح هنا صراحة بدل الاعتماد على الافتراضيات.
--
-- **`anon` لا يُمنح شيئًا على أي جدول.** لا صفحة عامة في هذا النظام.

grant usage on schema public to anon, authenticated, service_role;

grant select                         on public.organizations        to authenticated;
grant update                         on public.organizations        to authenticated;
grant select, update                 on public.profiles             to authenticated;
grant select, insert, update, delete on public.organization_members to authenticated;
grant select                         on public.subscriptions        to authenticated;
grant select, update                 on public.device_activations   to authenticated;
grant select, insert, update, delete on public.conversations        to authenticated;
grant select, insert, update, delete on public.messages             to authenticated;
grant select, insert, update, delete on public.files                to authenticated;
grant select, insert, update, delete on public.file_chunks          to authenticated;
grant select                         on public.audit_logs           to authenticated;

-- التسلسلات لازمة مع أعمدة IDENTITY التي يكتبها العميل.
grant usage, select on all sequences in schema public to authenticated;

-- الـBackend: صلاحية كاملة. مفتاح service_role يتجاوز RLS بحكم تعريفه،
-- ولذلك **لا يوضع في الواجهة ولا في إضافة المتصفح إطلاقًا**.
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;


-- ============================================================================
-- ٧) اختبارات العزل — إثبات أن البيانات لا تتسرّب
-- ============================================================================
-- **تُنفَّذ ضمن الهجرة نفسها.** فشل أي تأكيد يرفع استثناءً فتتراجع الهجرة
-- كلها: لا يمكن أن يبقى في المشروع مخطط ثبت تسريبه.
--
-- كيف تعمل: تزرع الكتلة جهتين ومستخدمين ثلاثة، ثم تنتحل هوية كل مستخدم عبر
-- `set local role authenticated` مع `request.jwt.claims` — وهو المسار نفسه
-- الذي يسلكه طلب حقيقي عبر PostgREST، فما يُقاس هنا هو ما سيراه العميل
-- فعلًا. ثم تحذف كل ما زرعته فلا يبقى في القاعدة أثر.
--
-- الحذف في النهاية يتم بعد `reset role` بصلاحيات المُنفِّذ، ويمرّ عبر
-- `on delete cascade` من الجهتين.

do $isolation_tests$
declare
  org_a       bigint;
  org_b       bigint;
  admin_a     uuid := gen_random_uuid();
  employee_a  uuid := gen_random_uuid();
  admin_b     uuid := gen_random_uuid();
  sub_a       bigint;
  sub_b       bigint;
  conv_a      bigint;
  seen        integer;
  device_rows integer;
  raised      boolean;
begin
  raise notice 'GovMind: بدء اختبارات العزل...';

  -- ---------------------------------------------------------------------
  -- التجهيز — بصلاحيات المُنفِّذ (كما يفعل الـBackend بـservice_role)
  -- ---------------------------------------------------------------------
  insert into public.organizations (name, slug)
  values ('جهة الاختبار أ', 'rls-test-org-a') returning id into org_a;
  insert into public.organizations (name, slug)
  values ('جهة الاختبار ب', 'rls-test-org-b') returning id into org_b;

  -- حسابات auth حقيقية: profiles مرتبط بها بمفتاح أجنبي، فلا ملف بلا حساب.
  insert into auth.users (id, email) values
    (admin_a,    'rls-admin-a@govmind.test'),
    (employee_a, 'rls-employee-a@govmind.test'),
    (admin_b,    'rls-admin-b@govmind.test');

  insert into public.profiles (id, organization_id, email, full_name, role) values
    (admin_a,    org_a, 'rls-admin-a@govmind.test',    'مسؤول أ', 'admin'),
    (employee_a, org_a, 'rls-employee-a@govmind.test', 'موظف أ',  'employee'),
    (admin_b,    org_b, 'rls-admin-b@govmind.test',    'مسؤول ب', 'admin');

  insert into public.organization_members (organization_id, user_id, role) values
    (org_a, admin_a,    'admin'),
    (org_a, employee_a, 'employee'),
    (org_b, admin_b,    'admin');

  insert into public.subscriptions (organization_id, status, expires_at)
  values (org_a, 'active', now() + interval '365 days') returning id into sub_a;
  insert into public.subscriptions (organization_id, status, expires_at)
  values (org_b, 'active', now() + interval '365 days') returning id into sub_b;

  insert into public.conversations (user_id, organization_id, title)
  values (employee_a, org_a, 'محادثة الموظف أ') returning id into conv_a;

  insert into public.messages (conversation_id, user_id, organization_id, role, content)
  values (conv_a, employee_a, org_a, 'user', 'سؤال سرّي');

  insert into public.files
    (user_id, organization_id, filename, content_type, size_bytes, storage_path)
  values (employee_a, org_a, 'سرّي.pdf', 'application/pdf', 1024, 'a/secret.pdf');

  insert into public.audit_logs (organization_id, user_id, action)
  values (org_a, employee_a, 'login');

  -- ---------------------------------------------------------------------
  -- اختبار ١: مسؤول جهة ب لا يرى **أي** صف من بيانات جهة أ
  -- ---------------------------------------------------------------------
  set local role authenticated;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', admin_b, 'role', 'authenticated')::text,
                     true);

  select count(*) into seen from public.organizations where id = org_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى جهة أ (% صف)', seen;
  end if;

  select count(*) into seen from public.conversations where organization_id = org_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى محادثات جهة أ (% صف)', seen;
  end if;

  select count(*) into seen from public.messages where organization_id = org_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى رسائل جهة أ (% صف)', seen;
  end if;

  select count(*) into seen from public.files where organization_id = org_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى ملفات جهة أ (% صف)', seen;
  end if;

  select count(*) into seen from public.audit_logs where organization_id = org_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى سجل تدقيق جهة أ (% صف)', seen;
  end if;

  select count(*) into seen from public.subscriptions where organization_id = org_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى اشتراك جهة أ (% صف)', seen;
  end if;

  select count(*) into seen from public.profiles where organization_id = org_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى ملفات مستخدمي جهة أ (% صف)', seen;
  end if;

  select count(*) into seen from public.device_activations
   where subscription_id = sub_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة ب رأى أجهزة اشتراك جهة أ (% صف)', seen;
  end if;

  -- ويرى بياناته هو: الاختبار السالب وحده لا يثبت شيئًا — سياسة تمنع الجميع
  -- تجتازه ولا تصلح نظامًا.
  select count(*) into seen from public.organizations where id = org_b;
  if seen <> 1 then
    raise exception 'خلل: مسؤول جهة ب لا يرى جهته هو (% صف)', seen;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٢: مسؤول جهة ب لا يعدّل بيانات جهة أ
  -- ---------------------------------------------------------------------
  -- سياسة UPDATE تخفي الصف عن هذا المستخدم، فالأمر لا يطابق شيئًا ولا يرفع
  -- خطأً — والدليل هو أن الاسم لم يتغيّر، لا أن الأمر فشل.
  begin
    update public.organizations set name = 'اختُطفت' where id = org_a;
  exception when others then
    null;  -- الرفض بخطأ نتيجة مقبولة كذلك
  end;

  reset role;
  select count(*) into seen from public.organizations
   where id = org_a and name = 'جهة الاختبار أ';
  if seen <> 1 then
    raise exception 'تسريب: مسؤول جهة ب عدّل اسم جهة أ';
  end if;
  set local role authenticated;

  -- ---------------------------------------------------------------------
  -- اختبار ٣: زميل في الجهة نفسها لا يرى محادثات غيره
  -- ---------------------------------------------------------------------
  perform set_config('request.jwt.claims',
                     json_build_object('sub', admin_a, 'role', 'authenticated')::text,
                     true);

  select count(*) into seen from public.conversations where id = conv_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة أ رأى محادثة موظفه الخاصة (% صف)', seen;
  end if;

  select count(*) into seen from public.messages where conversation_id = conv_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة أ رأى رسائل موظفه الخاصة (% صف)', seen;
  end if;

  select count(*) into seen from public.files where user_id = employee_a;
  if seen <> 0 then
    raise exception 'تسريب: مسؤول جهة أ رأى ملفات موظفه الخاصة (% صف)', seen;
  end if;

  -- لكنه يرى ملفات موظفي جهته الشخصية (profiles) لأنه يديرهم، واشتراك جهته.
  select count(*) into seen from public.profiles where organization_id = org_a;
  if seen <> 2 then
    raise exception 'خلل: مسؤول جهة أ يجب أن يرى موظفَي جهته (% صف)', seen;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٤: الموظف لا يستطيع ترقية نفسه إلى مسؤول
  -- ---------------------------------------------------------------------
  perform set_config('request.jwt.claims',
                     json_build_object('sub', employee_a, 'role', 'authenticated')::text,
                     true);

  raised := false;
  begin
    update public.profiles set role = 'admin' where id = employee_a;
  exception when others then
    raised := true;
  end;

  reset role;
  select count(*) into seen from public.profiles
   where id = employee_a and role = 'admin';
  if seen <> 0 then
    raise exception 'ثغرة تصعيد صلاحيات: الموظف رقّى نفسه إلى مسؤول';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٥: الموظف لا ينسب محادثة إلى جهة أخرى
  -- ---------------------------------------------------------------------
  set local role authenticated;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', employee_a, 'role', 'authenticated')::text,
                     true);

  raised := false;
  begin
    insert into public.conversations (user_id, organization_id, title)
    values (employee_a, org_b, 'محادثة مدسوسة');
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'تسريب: الموظف أنشأ محادثة منسوبة إلى جهة أخرى';
  end if;

  -- ولا ينسب محادثة إلى مستخدم آخر.
  raised := false;
  begin
    insert into public.conversations (user_id, organization_id, title)
    values (admin_a, org_a, 'محادثة باسم غيري');
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'تسريب: الموظف أنشأ محادثة باسم مستخدم آخر';
  end if;

  reset role;

  -- ---------------------------------------------------------------------
  -- اختبار ٦: جهاز واحد فعّال لكل اشتراك
  -- ---------------------------------------------------------------------
  insert into public.device_activations (subscription_id, device_id_hash, device_name)
  values (sub_a, repeat('a', 64), 'حاسب المكتب');

  raised := false;
  begin
    insert into public.device_activations (subscription_id, device_id_hash, device_name)
    values (sub_a, repeat('b', 64), 'حاسب المنزل');
  exception when unique_violation then
    raised := true;
  end;
  if not raised then
    raise exception 'خلل: نجح تفعيل جهاز ثانٍ والأول ما زال فعّالًا';
  end if;

  -- بعد الإبطال يصير مكان جهاز جديد شاغرًا.
  update public.device_activations
     set revoked_at = now()
   where subscription_id = sub_a and revoked_at is null;

  insert into public.device_activations (subscription_id, device_id_hash, device_name)
  values (sub_a, repeat('b', 64), 'حاسب المنزل');

  select count(*) into device_rows from public.device_activations
   where subscription_id = sub_a;
  if device_rows <> 2 then
    raise exception 'خلل: سجل الأجهزة يجب أن يحتفظ بالمبطل والفعّال (% صف)', device_rows;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٧: البصمة الخام مرفوضة — التجزئة وحدها تُقبل
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    insert into public.device_activations (subscription_id, device_id_hash, device_name)
    values (sub_b, 'DESKTOP-ABC123-raw-fingerprint', 'جهاز ببصمة خام');
  exception when check_violation then
    raised := true;
  end;
  if not raised then
    raise exception 'خلل: قُبلت بصمة جهاز خام بدل تجزئة SHA-256';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٨: الزائر (anon) لا يرى شيئًا على الإطلاق
  -- ---------------------------------------------------------------------
  set local role anon;
  raised := false;
  begin
    select count(*) into seen from public.organizations;
    if seen <> 0 then
      raise exception 'تسريب: الزائر رأى % جهة', seen;
    end if;
  exception
    when insufficient_privilege then
      raised := true;  -- ممنوع بالصلاحيات قبل RLS — نتيجة مقبولة كذلك
  end;
  reset role;

  -- ---------------------------------------------------------------------
  -- التنظيف — لا يبقى أثر للاختبارات في القاعدة
  -- ---------------------------------------------------------------------
  delete from public.organizations where id in (org_a, org_b);
  delete from auth.users where id in (admin_a, employee_a, admin_b);

  raise notice 'GovMind: اجتازت اختبارات العزل الثمانية جميعها ✔';
end
$isolation_tests$;


-- ============================================================================
-- بعد التنفيذ
-- ============================================================================
-- ١) أنشئ أول جهة وأول مسؤول من الـBackend بـservice_role، أو يدويًا هنا:
--
--      insert into public.organizations (name, slug)
--      values ('اسم الجهة', 'org-slug');
--
--    ثم أنشئ المستخدم من Supabase Dashboard ← Authentication ← Add user،
--    وانسخ معرّفه (uuid) وأدرج له صفًا في profiles و organization_members
--    بدور 'admin'، ثم أدرج صف subscriptions للجهة.
--
-- ٢) الاشتراك **لا يُنشأ تلقائيًا**: جهة بلا صف اشتراك ممنوعة من الخدمة
--    عمدًا (فشل مغلق). أدرجه صراحة:
--
--      insert into public.subscriptions (organization_id, status, seats, expires_at)
--      values (<org_id>, 'trial', 10, now() + interval '30 days');
--
-- ٣) **لا تضع `service_role` في أي عميل.** الواجهة وإضافة المتصفح تستخدمان
--    الـBackend وحده، والـBackend وحده يحمل المفتاح في متغير بيئة.
-- ============================================================================
