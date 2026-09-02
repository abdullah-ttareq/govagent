-- ============================================================================
-- GovMind — مخطط Supabase — الهجرة رقم ٣: التسجيل الذاتي
--
-- **نفّذ 0001 ثم 0002 أولًا.** يُنفَّذ كما هو من Supabase SQL Editor، وهو
-- **تحديثي (idempotent)** وينتهي باختبارات تُفشل الهجرة إن اختلّ شرط.
--
-- ----------------------------------------------------------------------------
-- ما تحلّه
-- ----------------------------------------------------------------------------
-- كان تجهيز أي حساب عملية يدوية في لوحة Supabase. هذه الهجرة تجعلها عملية
-- واحدة يستدعيها الـBackend عند تسجيل عميل جديد من الإضافة.
--
-- **أربع كتابات يجب أن تنجح معًا أو تفشل معًا:**
--
--   ١) الجهة            organizations
--   ٢) الملف الشخصي      profiles          (دور admin)
--   ٣) العضوية          organization_members (دور admin)
--   ٤) اشتراك تجريبي     subscriptions     (مقعد واحد، ٣٠ يومًا)
--
-- نجاح بعضها دون بعض يترك حسابًا لا يستطيع صاحبه استعماله ولا حذفه:
-- جهة بلا اشتراك (ممنوعة من الخدمة بفشل مغلق)، أو ملف بلا عضوية (لا يراه
-- أي استعلام صلاحيات). لذلك هي دالة واحدة — وجسم الدالة معاملة ضمنية.
--
-- ----------------------------------------------------------------------------
-- ⚠️ «الجهة» بنيةٌ داخلية، لا مفهومٌ يراه العميل
-- ----------------------------------------------------------------------------
-- المنتج النهائي **اشتراك فردي**: حساب واحد، اشتراك واحد، جهاز فعّال واحد.
-- **لا مسؤول جهة ولا مسؤول نظام** يراجعه العميل، ولا يُطلب منه اسم جهة.
--
-- ومع ذلك يبقى الجدول `organizations` كما هو، لأن **كل سياسات RLS تقيس
-- عليه**: عزل المحادثات والملفات والمقاطع والسجلّات كلها مبنية على
-- `organization_id`. إزالته تعني إعادة كتابة العزل كله لمكسب تسمية.
--
-- فلكل حساب **مساحة شخصية مخفية**: جهة يولّد الـBackend اسمها ومعرّفها
-- النصي من معرّف المستخدم، فلا تتصادم ولا يراها العميل ولا يُسأل عنها.
--
-- والدور `admin` في `profiles` و`organization_members` **صلاحية قاعدة
-- بيانات لا لقب**: صاحب المساحة يملكها كاملة. لا تُعرض هذه الكلمة في أي
-- شاشة.
--
-- ⚠️ **حساب `auth.users` لا يُنشأ هنا.** إنشاؤه يمرّ بـGoTrue لا بـSQL،
-- فلا يمكن ضمّه إلى المعاملة نفسها. الـBackend ينشئه أولًا، فإن فشلت هذه
-- الدالة **حذفه تعويضًا** — انظر `services/registration_service.py`.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- ١) فحص أوّلي — لا يغيّر شيئًا
-- ----------------------------------------------------------------------------
do $preflight$
begin
  if to_regclass('public.subscriptions') is null
     or to_regclass('public.organization_members') is null then
    raise exception
      'GovMind: نفّذ 0001_govmind_supabase.sql أولًا.';
  end if;
  raise notice 'GovMind: تهيئة دالة التسجيل الذاتي…';
end
$preflight$;


-- ----------------------------------------------------------------------------
-- ٢) الدالة الذرّية
-- ----------------------------------------------------------------------------
-- **`security definer` مقصود ومحصور:** تكتب في أربعة جداول عليها RLS يمنع
-- العملاء. لا تُمنح لأي دور عميل — `service_role` وحده ينفّذها.
-- `search_path` مثبّت لأن دالة definer بمسار متغيّر ثغرة معروفة.
--
-- **الأسماء المُخرَجة مسبوقة بـ`out_`:** أعمدة `returns table` متغيّرات
-- داخل الجسم، واسمٌ منها يطابق عمودًا يجعل كل إشارة إليه ملتبسة.

create or replace function public.register_organization(
  p_user_id     uuid,
  p_email       text,
  p_full_name   text,
  -- ⚠️ **مولَّدان في الـBackend من معرّف المستخدم، لا مُدخَلان من العميل.**
  -- شاشة التسجيل لا تسأل عن جهة أصلًا — انظر تعليق «المساحة الشخصية» أعلاه.
  p_org_name    text,
  p_org_slug    text,
  p_trial_days  integer default 30,
  p_seats       integer default 1
)
returns table (
  out_organization_id bigint,
  out_subscription_id bigint
)
language plpgsql
security definer
set search_path = public, pg_temp
as $register$
declare
  new_org bigint;
  new_sub bigint;
begin
  -- ① المساحة الشخصية. المعرّف النصي مشتقّ من `auth.users.id` فلا يتصادم
  --    عمليًا؛ ويبقى فحص التفرّد لأن قيدًا في القاعدة أوثق من افتراض.
  begin
    insert into public.organizations (name, slug)
    values (btrim(p_org_name), lower(btrim(p_org_slug)))
    returning id into new_org;
  exception when unique_violation then
    raise exception 'organization_slug_taken'
      using errcode = '23505',
            hint = 'اسم الجهة مستخدم في النظام.';
  end;

  -- ② الملف الشخصي. `id` هو معرّف `auth.users` نفسه.
  --    الدور `admin` **صلاحية قاعدة لا لقب يُعرض**: صاحب المساحة يملكها.
  begin
    insert into public.profiles (id, organization_id, email, full_name, role)
    values (p_user_id, new_org, lower(btrim(p_email)), btrim(p_full_name), 'admin');
  exception when unique_violation then
    -- فهرس `uq_profiles_email_lower` أو مفتاح `id` — كلاهما «مسجَّل سلفًا».
    raise exception 'email_already_registered'
      using errcode = '23505',
            hint = 'البريد الإلكتروني مسجَّل مسبقًا.';
  end;

  -- ③ العضوية. بدونها لا يراه أي استعلام صلاحيات ولو كان ملفه admin.
  --    وهي عضوية العميل في مساحته هو — لا انضمام إلى جهة فيها آخرون.
  insert into public.organization_members (organization_id, user_id, role)
  values (new_org, p_user_id, 'admin');

  -- ④ الاشتراك التجريبي: **مقعد واحد** و**٣٠ يومًا**.
  -- المقعد الواحد هو النموذج كله لا قيمةً افتراضية: عميل واحد على جهاز
  -- فعّال واحد. تغيير الجهاز يفعله العميل بنفسه — انظر الهجرة ٤.
  insert into public.subscriptions
    (organization_id, status, seats, starts_at, expires_at)
  values
    (new_org, 'trial', greatest(1, p_seats),
     now(), now() + make_interval(days => greatest(1, p_trial_days)))
  returning id into new_sub;

  insert into public.audit_logs (organization_id, user_id, action, entity_type, entity_id)
  values (new_org, p_user_id, 'organization.registered', 'organization', new_org::text);

  return query select new_org, new_sub;
end
$register$;

comment on function public.register_organization(uuid, text, text, text, text, integer, integer) is
  'ينشئ الجهة وملف المسؤول وعضويته واشتراكًا تجريبيًا في معاملة واحدة. للـBackend وحده.';

revoke all on function public.register_organization(uuid, text, text, text, text, integer, integer)
  from public, anon, authenticated;
grant execute on function public.register_organization(uuid, text, text, text, text, integer, integer)
  to service_role;


-- ============================================================================
-- ٣) اختبارات — الذرّية والتفرّد وشروط الاشتراك التجريبي
-- ============================================================================
create or replace function public.govmind_purge_registration_fixtures()
returns void
language plpgsql
as $purge_fx$
declare
  test_users constant uuid[] := array[
    '00000000-0000-4000-8000-0000000d0001',
    '00000000-0000-4000-8000-0000000d0002'
  ]::uuid[];
  test_slugs constant text[] := array['rls-test-reg-a', 'rls-test-reg-b'];
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


do $registration_tests$
declare
  user_a constant uuid := '00000000-0000-4000-8000-0000000d0001';
  user_b constant uuid := '00000000-0000-4000-8000-0000000d0002';
  result record;
  sub    public.subscriptions%rowtype;
  seen   integer;
  raised boolean;
begin
  raise notice 'GovMind: بدء اختبارات التسجيل…';
  perform public.govmind_purge_registration_fixtures();

  insert into auth.users (id, email) values
    (user_a, 'rls-reg-a@govmind.test'),
    (user_b, 'rls-reg-b@govmind.test');

  -- ---------------------------------------------------------------------
  -- اختبار ١: التسجيل ينشئ الأربعة كلها
  -- ---------------------------------------------------------------------
  select * into result from public.register_organization(
    user_a, 'rls-reg-a@govmind.test', 'عميل أ', 'مساحة عميل أ', 'rls-test-reg-a'
  );

  if result.out_organization_id is null or result.out_subscription_id is null then
    raise exception 'خلل: التسجيل لم يُعِد معرّفات';
  end if;

  select count(*) into seen from public.profiles
   where id = user_a and role = 'admin';
  if seen <> 1 then raise exception 'خلل: لم يُنشأ الملف الشخصي'; end if;

  select count(*) into seen from public.organization_members
   where user_id = user_a and role = 'admin';
  if seen <> 1 then raise exception 'خلل: لم تُنشأ العضوية'; end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٢: الاشتراك تجريبي، بمقعد واحد، و٣٠ يومًا
  -- ---------------------------------------------------------------------
  select * into sub from public.subscriptions where id = result.out_subscription_id;

  if sub.status <> 'trial' then
    raise exception 'خلل: حالة الاشتراك % لا trial', sub.status;
  end if;
  if sub.seats <> 1 then
    raise exception 'خلل: عدد المقاعد % لا واحد', sub.seats;
  end if;
  if sub.expires_at::date <> (now() + interval '30 days')::date then
    raise exception 'خلل: مدة التجربة ليست ٣٠ يومًا (تنتهي %)', sub.expires_at;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٣: معرّف نصي مكرر يُرفض (لا يقع عمليًا، والقيد يحرسه)
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    perform public.register_organization(
      user_b, 'rls-reg-b@govmind.test', 'عميل ب', 'مساحة عميل ب', 'rls-test-reg-a'
    );
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قُبل معرّف جهة مكرر';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٤: **لا بقايا بعد الفشل** — الذرّية
  -- ---------------------------------------------------------------------
  -- الجهة الثانية أُدرجت في ① قبل أن يفشل ②؛ لولا ذرّية الدالة لبقيت.
  select count(*) into seen from public.organizations where slug = 'rls-test-reg-b';
  if seen <> 0 then
    raise exception 'خلل: بقيت جهة بعد فشل التسجيل (% صف)', seen;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٥: بريد مكرر يُرفض ولا يترك جهة
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    perform public.register_organization(
      user_b, 'rls-reg-a@govmind.test', 'عميل ب', 'مساحة عميل ب', 'rls-test-reg-b'
    );
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قُبل بريد مسجَّل مسبقًا';
  end if;

  select count(*) into seen from public.organizations where slug = 'rls-test-reg-b';
  if seen <> 0 then
    raise exception 'خلل: بقيت جهة بعد فشل التسجيل ببريد مكرر (% صف)', seen;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٦: العميل المسجَّل لا ينفّذ الدالة
  -- ---------------------------------------------------------------------
  set local role authenticated;
  raised := false;
  begin
    perform public.register_organization(
      user_b, 'x@govmind.test', 'س', 'مساحة', 'rls-test-reg-b'
    );
  exception when insufficient_privilege then
    raised := true;
  when others then
    raised := true;
  end;
  reset role;
  if not raised then
    raise exception 'ثغرة: نفّذ عميل مسجَّل دالة التسجيل';
  end if;

  perform public.govmind_purge_registration_fixtures();
  raise notice 'GovMind: اجتازت اختبارات التسجيل الستة ✔';
end
$registration_tests$;


do $registration_cleanup_check$
declare
  remaining integer;
begin
  perform public.govmind_purge_registration_fixtures();
  select
    (select count(*) from public.organizations where slug like 'rls-test-reg-%')
  + (select count(*) from auth.users where email like 'rls-reg-%@govmind.test')
  into remaining;

  if remaining <> 0 then
    raise exception 'خلل: بقي % صف اختبار بعد التنظيف', remaining;
  end if;
  raise notice 'GovMind: اجتاز اختبار انحدار تنظيف التسجيل ✔';
end
$registration_cleanup_check$;

drop function if exists public.govmind_purge_registration_fixtures();


-- ============================================================================
-- بعد التنفيذ
-- ============================================================================
-- لا خطوة يدوية. الـBackend يستدعي `register_organization` بعد أن ينشئ
-- حساب `auth.users`، ويحذف الحساب تعويضًا إن فشلت الدالة.
--
-- ⚠️ **لا يُعرض للعميل شيء من مفردات «الجهة» ولا لقب «مسؤول».** الجدول
-- والدور بنيةُ تفويضٍ داخلية فحسب.
-- ============================================================================
