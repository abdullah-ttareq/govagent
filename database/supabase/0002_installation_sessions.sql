-- ============================================================================
-- GovMind — مخطط Supabase — الهجرة رقم ٢: جلسات التركيب
--
-- **نفّذ `0001_govmind_supabase.sql` أولًا.** هذا الملف يبني عليه ولا يغني
-- عنه. يُنفَّذ كما هو من Supabase SQL Editor، وهو **تحديثي (idempotent)**
-- وينتهي باختبارات تُفشل الهجرة إن اختلّ شرط أمني.
--
-- ----------------------------------------------------------------------------
-- المشكلة التي يحلّها
-- ----------------------------------------------------------------------------
-- في المرحلة الأولى كانت هوية الجهاز معرّفًا عشوائيًا داخل
-- `chrome.storage.local`. **لا يصلح هوية نهائية:** المثبَّت على ويندوز لا
-- يستطيع قراءة تخزين المتصفح، فلا سبيل آمنًا لتسليم الهوية إليه، وهي تموت
-- بتغيّر ملف تعريف المتصفح على جهاز لم يتغيّر.
--
-- البديل: **رمز تركيب لمرة واحدة**. الإضافة تطلبه قبل التنزيل، وتسلّمه إلى
-- الـRuntime على `127.0.0.1` بعد التثبيت، فيولّد الـRuntime هويته بنفسه على
-- الجهاز ويستبدل الرمز بتفعيل. الإضافة لا تعرف هوية الجهاز إطلاقًا.
--
-- ----------------------------------------------------------------------------
-- خصائص الرمز
-- ----------------------------------------------------------------------------
-- * يولّده الـBackend بـ`secrets.token_urlsafe(32)` — ٢٥٦ بت عشوائية.
-- * **لا يُخزَّن خامًا**: يُخزَّن SHA-256 له وحده، كما لا تُخزَّن بصمة الجهاز.
-- * قصير العمر (١٥ دقيقة افتراضًا) — نافذة تركيب لا جلسة.
-- * **لمرة واحدة**: `used_at` يُملأ عند الاستهلاك، وإعادة إرساله تفشل.
-- * مربوط بالمستخدم والجهة والاشتراك معًا، فلا يُستعمل لتفعيل اشتراك آخر.
--
-- ⚠️ **لا مِلح مع التجزئة هنا، بخلاف بصمة الجهاز.** المِلح يلزم حين يكون
-- المُجزَّأ قليل العشوائية وقابلًا للتخمين بجدول مسبق (بصمة جهاز، كلمة مرور).
-- رمزٌ عشوائي ٢٥٦ بت لا يُخمَّن، فـSHA-256 عليه كافية، وإضافة مِلح تضيف
-- سرًّا يجب حفظه بلا أن تزيد أمانًا.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- ١) فحص أوّلي — لا يغيّر شيئًا
-- ----------------------------------------------------------------------------
do $preflight$
begin
  if to_regclass('public.subscriptions') is null then
    raise exception
      'GovMind: نفّذ 0001_govmind_supabase.sql أولًا — جدول subscriptions غير موجود.';
  end if;

  if to_regclass('public.installation_sessions') is null then
    raise notice 'GovMind: تنفيذ أول للهجرة ٢.';
  else
    raise notice 'GovMind: جدول installation_sessions موجود — هذا التنفيذ تحديثي.';
  end if;
end
$preflight$;


-- ----------------------------------------------------------------------------
-- ٢) الجدول
-- ----------------------------------------------------------------------------
-- **لا شيء زائد عن الحاجة.** لا عنوان IP ولا وكيل مستخدم ولا اسم جهاز: هذا
-- صفٌّ عمره دقائق، وكل عمود فيه بيانات عن عميل يجب أن يبرّر وجوده.
create table if not exists public.installation_sessions (
  id              bigint generated always as identity primary key,

  -- الثلاثة معًا: الرمز لا يفعّل اشتراكًا غير الذي صدر له.
  user_id         uuid        not null references public.profiles (id) on delete cascade,
  organization_id bigint      not null references public.organizations (id) on delete cascade,
  subscription_id bigint      not null references public.subscriptions (id) on delete cascade,

  -- ⚠️ تجزئة لا رمز. ٦٤ خانة ست عشرية = SHA-256، ويفرض القيد الشكل فلا
  -- يمكن تمرير رمز خام سهوًا.
  token_hash      text        not null unique
                  check (token_hash ~ '^[0-9a-f]{64}$'),

  expires_at      timestamptz not null,
  --: يُملأ لحظة الاستهلاك. وجوده يعني أن الرمز أُحرق.
  used_at         timestamptz,
  created_at      timestamptz not null default now(),

  constraint ck_installation_sessions_window check (expires_at > created_at)
);

comment on table public.installation_sessions is
  'رموز تركيب لمرة واحدة تنقل الثقة من الإضافة إلى الـRuntime. تُخزَّن مجزّأة.';

-- البحث يتم بالتجزئة دائمًا؛ القيد الفريد يوفّر فهرسه.
-- وهذا الفهرس الجزئي يخدم تنظيف المنتهية.
create index if not exists ix_installation_sessions_open
  on public.installation_sessions (expires_at)
  where used_at is null;


-- ----------------------------------------------------------------------------
-- ٣) RLS — الجدول مغلق تمامًا أمام العملاء
-- ----------------------------------------------------------------------------
-- **لا سياسة واحدة، ولا `grant` لأي دور عميل.** لا يقرأ العميل رموز تركيبه
-- ولا يكتبها: يصدرها الـBackend ويستهلكها الـBackend. القراءة المسموحة
-- الوحيدة هي للـ`service_role`.
--
-- تفعيل RLS بلا سياسة = منع الجميع. هذا مقصود وليس سهوًا.
alter table public.installation_sessions enable row level security;
alter table public.installation_sessions force  row level security;

revoke all on public.installation_sessions from anon, authenticated;
grant all on public.installation_sessions to service_role;


-- ----------------------------------------------------------------------------
-- ٤) الاستهلاك الذرّي — قلب هذه الهجرة
-- ----------------------------------------------------------------------------
-- **لماذا دالة في القاعدة لا خطوتان في بايثون؟**
--
-- استهلاك الرمز وإنشاء تفعيل الجهاز يجب أن ينجحا معًا أو يفشلا معًا. عبر
-- PostgREST لا توجد معاملة تمتدّ عبر طلبين، فطلبان متتاليان يتركان نافذة
-- حقيقية:
--
--   * رمز استُهلك ثم فشل التفعيل ⇒ العميل يملك مثبّتًا لا يعمل ورمزًا محروقًا.
--   * تفعيل نجح ثم فشل الاستهلاك ⇒ الرمز يبقى صالحًا للاستعمال مرة أخرى.
--
-- هذه الدالة تفعل الاثنين في معاملة واحدة (جسم الدالة معاملة ضمنية).
--
-- **`security definer` مقصود ومحصور:** تكتب في جدولين عليهما RLS يمنع
-- الجميع. لا تُمنح لأي دور عميل — `service_role` وحده ينفّذها، وهو يتجاوز
-- RLS أصلًا؛ الـ`definer` هنا يجعل الدالة تعمل كذلك لو استُدعيت من سياق
-- آخر مستقبلًا. `search_path` مثبّت لأن دالة definer بمسار متغيّر ثغرة.
--
-- **المدخلات مجزّأة سلفًا:** الدالة لا ترى رمزًا خامًا ولا بصمة جهاز خامة.
-- التجزئة تتم في الـBackend (بمِلح للجهاز، بلا مِلح للرمز).

create or replace function public.redeem_installation_session(
  p_token_hash     text,
  p_device_hash    text,
  p_device_name    text default 'جهاز غير مسمّى'
)
-- ⚠️ **أسماء المخرجات مسبوقة بـ`out_` عمدًا.** أعماد `returns table` متغيّرات
-- داخل جسم الدالة، فاسمٌ منها يطابق عمودًا في جدول مستعمَل يجعل كل إشارة
-- إليه ملتبسة ويفشل التنفيذ بـ`column reference ... is ambiguous`.
returns table (
  out_activation_id   bigint,
  out_subscription_id bigint,
  out_organization_id bigint,
  out_user_id         uuid
)
language plpgsql
security definer
set search_path = public, pg_temp
as $redeem$
declare
  session_row public.installation_sessions%rowtype;
  sub_row     public.subscriptions%rowtype;
  existing    public.device_activations%rowtype;
  new_id      bigint;
begin
  -- ① احجز الرمز. `for update` يمنع طلبين متزامنين من قراءته معًا،
  --    والشروط الثلاثة تُفحص في الجملة نفسها لا قبلها.
  select * into session_row
  from public.installation_sessions
  where token_hash = p_token_hash
    and used_at is null
    and expires_at > now()
  for update;

  if not found then
    -- رمز خاطئ أو منتهٍ أو مستعمَل — **لا يُفرَّق بينها**: التفريق يخبر
    -- من يجرّب الرموز أيّها كان صحيحًا يومًا.
    raise exception 'invalid_installation_token'
      using errcode = '28000',
            hint = 'رمز التركيب غير صالح أو انتهت صلاحيته. أعد الخطوات من الإضافة.';
  end if;

  -- ② الاشتراك يجب أن يسمح بالخدمة **الآن**، لا لحظة إصدار الرمز.
  select * into sub_row
  from public.subscriptions
  where id = session_row.subscription_id;

  if sub_row.status not in ('trial', 'active') or sub_row.expires_at <= now() then
    raise exception 'subscription_not_serviceable'
      using errcode = '22023',
            hint = 'الاشتراك لا يسمح بالتفعيل حاليًا.';
  end if;

  -- ③ الجهاز نفسه مفعّل مسبقًا؟ عملية مُعادة التنفيذ لا خطأ: الـRuntime
  --    قد يعيد المحاولة بعد انقطاع شبكة بين النجاح ووصول الرد.
  select * into existing
  from public.device_activations
  where subscription_id = session_row.subscription_id
    and device_id_hash = p_device_hash
    and revoked_at is null;

  if found then
    update public.installation_sessions
       set used_at = coalesce(used_at, now())
     where id = session_row.id;

    return query select existing.id, session_row.subscription_id,
                        session_row.organization_id, session_row.user_id;
    return;
  end if;

  -- ④ التفعيل. **جهاز ثانٍ يفشل هنا على الفهرس الفريد الجزئي**
  --    `uq_device_activations_one_active`، لا على فحص في بايثون.
  insert into public.device_activations
    (subscription_id, device_id_hash, device_name)
  values
    (session_row.subscription_id, p_device_hash,
     coalesce(nullif(btrim(p_device_name), ''), 'جهاز غير مسمّى'))
  returning id into new_id;

  -- ⑤ احرق الرمز. لو فشل ④ لما وصلنا هنا، ولو فشل ⑤ لتراجع ④ معه.
  update public.installation_sessions
     set used_at = now()
   where id = session_row.id;

  insert into public.audit_logs (organization_id, user_id, action, entity_type, entity_id)
  values (session_row.organization_id, session_row.user_id,
          'device.activated', 'device_activation', new_id::text);

  return query select new_id, session_row.subscription_id,
                      session_row.organization_id, session_row.user_id;
end
$redeem$;

comment on function public.redeem_installation_session(text, text, text) is
  'يستهلك رمز تركيب وينشئ تفعيل الجهاز في معاملة واحدة. للـBackend وحده.';

revoke all on function public.redeem_installation_session(text, text, text)
  from public, anon, authenticated;
grant execute on function public.redeem_installation_session(text, text, text)
  to service_role;


-- ----------------------------------------------------------------------------
-- ٥) تنظيف الرموز المنتهية
-- ----------------------------------------------------------------------------
-- صفٌّ عمره دقائق لا يبقى في القاعدة شهورًا. تُستدعى من الـBackend عند إصدار
-- رمز جديد — لا تحتاج مهمة مجدولة.
create or replace function public.purge_expired_installation_sessions()
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $purge_sessions$
declare
  removed integer;
begin
  delete from public.installation_sessions
   where (used_at is not null and used_at < now() - interval '7 days')
      or (used_at is null and expires_at < now() - interval '1 day');
  get diagnostics removed = row_count;
  return removed;
end
$purge_sessions$;

revoke all on function public.purge_expired_installation_sessions()
  from public, anon, authenticated;
grant execute on function public.purge_expired_installation_sessions()
  to service_role;


-- ============================================================================
-- ٦) اختبارات — رمز لمرة واحدة، وجهاز واحد
-- ============================================================================
-- تفشل الهجرة كلها إن اختلّ شرط. المعرّفات ثابتة ومعلومة كما في الهجرة ١،
-- والتنظيف من الابن إلى الأب.

create or replace function public.govmind_purge_session_fixtures()
returns void
language plpgsql
as $purge_fx$
declare
  test_users constant uuid[] := array[
    '00000000-0000-4000-8000-0000000c0001'
  ]::uuid[];
  test_slugs constant text[] := array['rls-test-org-sessions'];
  test_orgs  bigint[];
begin
  select coalesce(array_agg(id), '{}'::bigint[]) into test_orgs
  from public.organizations where slug = any (test_slugs);

  delete from public.installation_sessions
   where organization_id = any (test_orgs) or user_id = any (test_users);
  delete from public.audit_logs
   where organization_id = any (test_orgs) or user_id = any (test_users);
  delete from public.device_activations
   where subscription_id in (
     select id from public.subscriptions where organization_id = any (test_orgs)
   );
  delete from public.subscriptions where organization_id = any (test_orgs);
  delete from public.organization_members
   where organization_id = any (test_orgs) or user_id = any (test_users);
  delete from public.profiles
   where id = any (test_users) or organization_id = any (test_orgs);
  delete from public.organizations where id = any (test_orgs);
  delete from auth.users
   where id = any (test_users) and email like 'rls-%@govmind.test';
end
$purge_fx$;


do $session_tests$
declare
  test_user constant uuid := '00000000-0000-4000-8000-0000000c0001';
  org_id     bigint;
  sub_id     bigint;
  -- تجزئات ثابتة الشكل: الاختبار لا يملك رمزًا خامًا ولا يحتاجه.
  hash_ok    constant text := repeat('1', 64);
  hash_used  constant text := repeat('2', 64);
  hash_gone  constant text := repeat('3', 64);
  hash_old   constant text := repeat('4', 64);
  hash_late  constant text := repeat('5', 64);
  device_one constant text := repeat('a', 64);
  device_two constant text := repeat('b', 64);
  result     record;
  raised     boolean;
  rows_found integer;
begin
  raise notice 'GovMind: بدء اختبارات جلسات التركيب...';
  perform public.govmind_purge_session_fixtures();

  insert into public.organizations (name, slug)
  values ('جهة اختبار الجلسات', 'rls-test-org-sessions') returning id into org_id;

  insert into auth.users (id, email)
  values (test_user, 'rls-session@govmind.test');

  insert into public.profiles (id, organization_id, email, full_name, role)
  values (test_user, org_id, 'rls-session@govmind.test', 'مستخدم اختبار', 'admin');

  insert into public.organization_members (organization_id, user_id, role)
  values (org_id, test_user, 'admin');

  insert into public.subscriptions (organization_id, status, expires_at)
  values (org_id, 'active', now() + interval '365 days') returning id into sub_id;

  -- ---------------------------------------------------------------------
  -- اختبار ١: رمز صالح يفعّل الجهاز ويُحرق في العملية نفسها
  -- ---------------------------------------------------------------------
  insert into public.installation_sessions
    (user_id, organization_id, subscription_id, token_hash, expires_at)
  values (test_user, org_id, sub_id, hash_ok, now() + interval '15 minutes');

  select * into result
  from public.redeem_installation_session(hash_ok, device_one, 'حاسب الاختبار');

  if result.out_activation_id is null then
    raise exception 'خلل: لم يُنشأ تفعيل للجهاز';
  end if;

  select count(*) into rows_found from public.installation_sessions
   where token_hash = hash_ok and used_at is not null;
  if rows_found <> 1 then
    raise exception 'خلل: الرمز لم يُحرق بعد استهلاكه';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٢: إعادة إرسال الرمز نفسه تفشل (لمرة واحدة)
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    perform public.redeem_installation_session(hash_ok, device_two, 'جهاز ثانٍ');
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: أُعيد استعمال رمز تركيب محروق';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٣: الجهاز نفسه مرة أخرى — عملية مُعادة التنفيذ لا خطأ
  -- ---------------------------------------------------------------------
  insert into public.installation_sessions
    (user_id, organization_id, subscription_id, token_hash, expires_at)
  values (test_user, org_id, sub_id, hash_used, now() + interval '15 minutes');

  select * into result
  from public.redeem_installation_session(hash_used, device_one, 'حاسب الاختبار');
  if result.out_activation_id is null then
    raise exception 'خلل: إعادة تفعيل الجهاز نفسه يجب أن تنجح لا أن تفشل';
  end if;

  select count(*) into rows_found from public.device_activations
   where subscription_id = sub_id and revoked_at is null;
  if rows_found <> 1 then
    raise exception 'خلل: تكرّر تفعيل الجهاز نفسه (% صف)', rows_found;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٤: جهاز ثانٍ يفشل — **على قيد القاعدة**
  -- ---------------------------------------------------------------------
  insert into public.installation_sessions
    (user_id, organization_id, subscription_id, token_hash, expires_at)
  values (test_user, org_id, sub_id, hash_gone, now() + interval '15 minutes');

  raised := false;
  begin
    perform public.redeem_installation_session(hash_gone, device_two, 'جهاز ثانٍ');
  exception when unique_violation then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: فُعّل جهاز ثانٍ والأول ما زال فعّالًا';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٥: رمز منتهٍ يفشل
  -- ---------------------------------------------------------------------
  -- صفٌّ جديد بتاريخ إصدار في الماضي، لا تعديلٌ لـ`expires_at` إلى الخلف:
  -- الثاني يخالف `ck_installation_sessions_window` (expires_at > created_at)،
  -- والقيد سليم — الاختبار هو الذي يجب أن يبني حالة واقعية.
  insert into public.installation_sessions
    (user_id, organization_id, subscription_id, token_hash, created_at, expires_at)
  values (test_user, org_id, sub_id, hash_old,
          now() - interval '1 hour', now() - interval '45 minutes');

  raised := false;
  begin
    perform public.redeem_installation_session(hash_old, device_two, 'جهاز ثانٍ');
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قُبل رمز تركيب منتهي الصلاحية';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٦: رمز لا وجود له يفشل
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    perform public.redeem_installation_session(repeat('f', 64), device_two, 'جهاز');
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قُبل رمز تركيب لا وجود له';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٧: اشتراك منتهٍ يمنع التفعيل
  -- ---------------------------------------------------------------------
  update public.device_activations set revoked_at = now()
   where subscription_id = sub_id and revoked_at is null;
  update public.subscriptions set status = 'expired' where id = sub_id;

  -- رمز سليم تمامًا — المانع هو الاشتراك وحده، فيُقاس هو لا غيره.
  insert into public.installation_sessions
    (user_id, organization_id, subscription_id, token_hash, expires_at)
  values (test_user, org_id, sub_id, hash_late, now() + interval '15 minutes');

  raised := false;
  begin
    perform public.redeem_installation_session(hash_late, device_two, 'جهاز');
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: فُعّل جهاز على اشتراك منتهٍ';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٨: الجدول مغلق أمام العميل المسجَّل
  -- ---------------------------------------------------------------------
  set local role authenticated;
  perform set_config('request.jwt.claims',
                     json_build_object('sub', test_user, 'role', 'authenticated')::text,
                     true);
  raised := false;
  begin
    select count(*) into rows_found from public.installation_sessions;
    if rows_found <> 0 then
      raise exception 'تسريب: قرأ العميل % رمز تركيب', rows_found;
    end if;
  exception when insufficient_privilege then
    raised := true;  -- ممنوع بالصلاحيات قبل RLS — نتيجة مقبولة كذلك
  end;
  reset role;

  perform public.govmind_purge_session_fixtures();
  raise notice 'GovMind: اجتازت اختبارات جلسات التركيب الثمانية ✔';
end
$session_tests$;


-- اختبار انحدار: التنظيف لا يترك أثرًا ولا يصطدم بمفتاح أجنبي.
do $session_cleanup_check$
declare
  remaining integer;
begin
  perform public.govmind_purge_session_fixtures();

  select
    (select count(*) from public.organizations where slug = 'rls-test-org-sessions')
  + (select count(*) from auth.users where email like 'rls-session@govmind.test')
  + (select count(*) from public.installation_sessions s
      join public.profiles p on p.id = s.user_id
      where p.email like 'rls-%@govmind.test')
  into remaining;

  if remaining <> 0 then
    raise exception 'خلل: بقي % صف اختبار بعد التنظيف', remaining;
  end if;
  raise notice 'GovMind: اجتاز اختبار انحدار تنظيف الجلسات ✔';
end
$session_cleanup_check$;

drop function if exists public.govmind_purge_session_fixtures();


-- ============================================================================
-- بعد التنفيذ
-- ============================================================================
-- لا خطوة يدوية. الـBackend يصدر الرموز ويستهلكها، والعميل لا يرى الجدول.
--
-- لمتابعة الجلسات المفتوحة (بـservice_role):
--
--   select id, user_id, organization_id, expires_at, used_at
--     from public.installation_sessions
--    where used_at is null and expires_at > now();
-- ============================================================================
