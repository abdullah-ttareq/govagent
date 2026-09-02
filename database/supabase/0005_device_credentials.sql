-- ============================================================================
-- GovMind — مخطط Supabase — الهجرة رقم ٥: بيانات اعتماد الجهاز
--
-- **نفّذ 0001 ثم 0002 ثم 0003 ثم 0004 أولًا.** تحديثي (idempotent)، وينتهي
-- باختبارات تُفشل الهجرة إن اختلّ شرط أمني.
--
-- ⚠️ **لا يُعدَّل أي ملف هجرة سابق.** ما قبل هذا الملف بقي كما نُفّذ على
-- القاعدة الحيّة؛ التغيير كله هنا.
--
-- ----------------------------------------------------------------------------
-- ما تحلّه
-- ----------------------------------------------------------------------------
-- كان الـRuntime **يولّد سرّه بنفسه** ويرسله في كل طلب. أي برنامج على جهاز
-- العميل يستطيع توليد سرّ، والسيرفر يقبل أوّل من يصل بشرط أن يطابق تجزئة
-- مخزّنة — فالسرّ كان معرّف جهاز لا بيان اعتماد صادر عن جهة تملك إصداره.
--
-- الآن: **السيرفر هو من يصدر بيان الاعتماد**، عشوائيًّا وغير قابل للتخمين،
-- لحظةَ يستبدل الـRuntime جلسة تركيب صالحة بنجاح. ويعود **مرة واحدة** في
-- رد الاستبدال ولا يُسترجع بعدها أبدًا: القاعدة لا تحمل إلا تجزئته.
--
-- ----------------------------------------------------------------------------
-- ما يبقى وما يتغيّر
-- ----------------------------------------------------------------------------
-- * `device_activations.device_id_hash` **يبقى كما هو**: هو *هويّة* الجهاز
--   التي يقوم عليها قيد «جهاز فعّال واحد» واستبدال الجهاز. لا يُلمس.
-- * `device_credentials` جديد: بيان *الاعتماد* الذي يصادِق به الـRuntime.
--   الفصل مقصود — الهوية تدوم، وبيان الاعتماد يُدوَّر ويُبطَل بلا أن يفقد
--   العميل جهازه المسجَّل ولا تاريخه.
--
-- ----------------------------------------------------------------------------
-- لماذا SHA-256 بلا مِلح هنا، بخلاف `device_id_hash`؟
-- ----------------------------------------------------------------------------
-- المِلح يلزم حين يكون المُجزَّأ قليل العشوائية فيُبنى له جدول مسبق (بصمة
-- جهاز، كلمة مرور). بيان الاعتماد هنا **٢٥٦ بت من `secrets.token_urlsafe`**
-- ولا يُخمَّن، فالمِلح يضيف سرًّا يجب حفظه بلا أن يزيد أمانًا — وهو المنطق
-- نفسه المطبَّق على `installation_sessions.token_hash` في الهجرة ٢.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- ١) فحص أوّلي — لا يغيّر شيئًا
-- ----------------------------------------------------------------------------
do $preflight$
begin
  if to_regclass('public.device_activations') is null then
    raise exception
      'GovMind: نفّذ 0001_govmind_supabase.sql أولًا — جدول device_activations غير موجود.';
  end if;
  if to_regclass('public.installation_sessions') is null then
    raise exception
      'GovMind: نفّذ 0002_installation_sessions.sql أولًا.';
  end if;

  if to_regclass('public.device_credentials') is null then
    raise notice 'GovMind: تنفيذ أول للهجرة ٥.';
  else
    raise notice 'GovMind: جدول device_credentials موجود — هذا التنفيذ تحديثي.';
  end if;
end
$preflight$;


-- ----------------------------------------------------------------------------
-- ٢) الجدول
-- ----------------------------------------------------------------------------
-- **لا شيء زائد عن الحاجة.** لا عنوان IP ولا وكيل مستخدم ولا اسم جهاز
-- (الاسم على التفعيل نفسه): هذا صفّ مصادقة، وكل عمود فيه عن عميل يجب أن
-- يبرّر وجوده.
create table if not exists public.device_credentials (
  id              bigint generated always as identity primary key,

  activation_id   bigint      not null
                  references public.device_activations (id) on delete cascade,

  -- ⚠️ **تجزئة لا بيان اعتماد.** القيمة الخام لا تدخل القاعدة إطلاقًا:
  -- يجزّئها الـBackend بـSHA-256 ويخزّن الناتج وحده. القيد يرفض أي قيمة
  -- ليست ٦٤ خانة ست عشرية، فلا يمكن تمرير قيمة خام سهوًا.
  credential_hash text        not null unique
                  check (credential_hash ~ '^[0-9a-f]{64}$'),

  issued_at       timestamptz not null default now(),
  --: يُحدَّث عند كل مصادقة ناجحة — للتشخيص ولقياس الهجر.
  last_used_at    timestamptz not null default now(),
  --: وجوده يعني أن البيان أُبطل. الصف **يبقى** ولا يُحذف فورًا.
  revoked_at      timestamptz
);

comment on table public.device_credentials is
  'بيانات اعتماد يصدرها السيرفر للـRuntime عند استبدال جلسة تركيب. تُخزَّن مجزّأة.';

-- **بيان اعتماد فعّال واحد لكل تفعيل.** التدوير يبطل السابق ثم يصدر
-- الجديد، والفهرس الجزئي هو الحكم الأخير لو أفلت طلبان متزامنان.
create unique index if not exists uq_device_credentials_one_active
  on public.device_credentials (activation_id)
  where revoked_at is null;

-- البحث يتم بالتجزئة دائمًا؛ القيد الفريد يوفّر فهرسه. وهذا يخدم التنظيف.
create index if not exists ix_device_credentials_revoked
  on public.device_credentials (revoked_at)
  where revoked_at is not null;


-- ----------------------------------------------------------------------------
-- ٣) RLS — الجدول مغلق تمامًا أمام العملاء
-- ----------------------------------------------------------------------------
-- **لا سياسة واحدة، ولا `grant` لأي دور عميل.** تفعيل RLS بلا سياسة = منع
-- الجميع، وهذا مقصود: العميل لا يقرأ تجزئة بيان اعتماده ولا يكتبها. من
-- يقرأ التجزئة يستطيع مطابقتها بقيمة خام يملكها، فلا تخرج إلى أحد.
alter table public.device_credentials enable row level security;
alter table public.device_credentials force  row level security;

revoke all on public.device_credentials from anon, authenticated;
grant all on public.device_credentials to service_role;


-- ----------------------------------------------------------------------------
-- ٤) الإبطال يتتالى من التفعيل إلى بيان اعتماده
-- ----------------------------------------------------------------------------
-- **هذا ما يجعل «استبدال الجهاز يبطل بيان اعتماده» حقيقةً في القاعدة لا
-- ترتيبَ نداءات في بايثون.** `replace_device_activation` (الهجرة ٤) يضبط
-- `revoked_at` على الصف السابق، و`revoke_device` كذلك — والاثنان لا يعرفان
-- شيئًا عن هذا الجدول ولا يجب أن يعرفا.
--
-- المشغّل يسدّ ذلك: أي مسار يبطل تفعيلًا — قائمًا الآن أو يُكتب لاحقًا —
-- يبطل بيان اعتماده في المعاملة نفسها.
create or replace function public.revoke_credentials_of_activation()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $revoke_creds$
begin
  update public.device_credentials
     set revoked_at = new.revoked_at
   where activation_id = new.id
     and revoked_at is null;
  return new;
end
$revoke_creds$;

comment on function public.revoke_credentials_of_activation() is
  'مشغّل: إبطال التفعيل يبطل بيانات اعتماده في المعاملة نفسها.';

drop trigger if exists trg_revoke_credentials_of_activation
  on public.device_activations;

create trigger trg_revoke_credentials_of_activation
  after update of revoked_at on public.device_activations
  for each row
  when (new.revoked_at is not null and old.revoked_at is null)
  execute function public.revoke_credentials_of_activation();


-- ----------------------------------------------------------------------------
-- ٥) الإصدار — ذرّي، ومع تدوير
-- ----------------------------------------------------------------------------
-- **لماذا دالة لا إدراج من بايثون؟** الإصدار عمليتان: إبطال البيان السابق
-- وإدراج الجديد. عبر PostgREST لا معاملة تمتدّ عبر طلبين، فطلبان متتاليان
-- يتركان نافذة إمّا تبطل بيانًا صالحًا بلا بديل، أو تترك بيانين فعّالين.
--
-- **ولماذا تفحص الاشتراك؟** بيان اعتماد يُصدَر على اشتراك لا يسمح بالخدمة
-- بيانٌ يُقبل غدًا بلا أن يمرّ بأي فحص إصدار. الفحص هنا وفي كل مصادقة.
create or replace function public.issue_device_credential(
  p_activation_id   bigint,
  p_credential_hash text
)
returns table (
  out_credential_id bigint,
  out_revoked_id    bigint
)
language plpgsql
security definer
set search_path = public, pg_temp
as $issue_cred$
declare
  act_row  public.device_activations%rowtype;
  sub_row  public.subscriptions%rowtype;
  old_id   bigint := null;
  new_id   bigint;
begin
  -- ① قفل التفعيل: يسلسل الإصدارات المتزامنة على الجهاز الواحد.
  select * into act_row
  from public.device_activations
  where id = p_activation_id
  for update;

  if not found then
    raise exception 'activation_not_found'
      using errcode = '22023', hint = 'لا يوجد تفعيل بهذا المعرّف.';
  end if;

  -- ② تفعيل مبطَل لا يُصدَر له بيان اعتماد جديد.
  if act_row.revoked_at is not null then
    raise exception 'activation_revoked'
      using errcode = '22023', hint = 'هذا الجهاز لم يعد مفعَّلًا.';
  end if;

  -- ③ الاشتراك يجب أن يسمح بالخدمة **الآن**.
  select * into sub_row
  from public.subscriptions
  where id = act_row.subscription_id;

  if not found
     or sub_row.status not in ('trial', 'active')
     or sub_row.expires_at <= now() then
    raise exception 'subscription_not_serviceable'
      using errcode = '22023', hint = 'الاشتراك لا يسمح بالخدمة حاليًا.';
  end if;

  -- ④ تدوير: أي بيان فعّال سابق يُبطل قبل إدراج الجديد.
  update public.device_credentials
     set revoked_at = now()
   where activation_id = p_activation_id
     and revoked_at is null
  returning id into old_id;

  -- ⑤ الإدراج. لو أفلت طلبٌ متزامن من القفل لفشل هنا على الفهرس الجزئي.
  insert into public.device_credentials (activation_id, credential_hash)
  values (p_activation_id, p_credential_hash)
  returning id into new_id;

  return query select new_id, old_id;
end
$issue_cred$;

comment on function public.issue_device_credential(bigint, text) is
  'يصدر بيان اعتماد لجهاز مفعَّل ويبطل سابقه في معاملة واحدة. للـBackend وحده.';

revoke all on function public.issue_device_credential(bigint, text)
  from public, anon, authenticated;
grant execute on function public.issue_device_credential(bigint, text)
  to service_role;


-- ----------------------------------------------------------------------------
-- ٦) المصادقة — الفحوص الثلاثة في جملة واحدة
-- ----------------------------------------------------------------------------
-- **كل طلب يمرّ من هنا**، ولا يعود بشيء ما لم تتحقق الثلاثة معًا:
--
--   ١) بيان الاعتماد غير مبطَل.
--   ٢) تفعيل الجهاز غير مبطَل (فالمستبدَل والمُبطَل مرفوضان).
--   ٣) الاشتراك `trial` أو `active` **ولم ينتهِ تاريخه**.
--
-- الحالة والتاريخ يُفحصان معًا: لا مشغّل في القاعدة يحوّل `active` إلى
-- `expired` عند مرور التاريخ، فحالةٌ سارية بتاريخ ماضٍ اشتراكٌ منتهٍ فعلًا.
--
-- ⚠️ **لا يُفرَّق في الرد بين «غير موجود» و«مبطَل» و«جهاز مستبدَل»**: صفر
-- صف في الحالات كلها. التفريق يخبر من يجرّب البيانات أيّها كان صحيحًا يومًا.
--
-- ----------------------------------------------------------------------------
-- `p_require_serviceable`: استثناء واحد، ومحصور
-- ----------------------------------------------------------------------------
-- **الافتراضي `true`** — وهو ما تستعمله كل مسارات الخدمة: اشتراك لا يسمح
-- ⇒ صفر صف ⇒ رفض.
--
-- و`false` لمسار **واحد** هو `/api/runtime/entitlement`، وهو مسار *إخبار*
-- لا مسار خدمة: الـRuntime يسأله «هل أستطيع العمل؟ وإن لا، فلماذا؟» ليعرض
-- السبب بالعربية على شاشة العميل. رفضُه بـ403 يترك العميل أمام «ممنوع»
-- بلا سبب ولا إجراء — وهو ما نصلحه في هذا التغيير كله.
--
-- ⚠️ **الفحصان الآخران لا يُستثنيان أبدًا**: البيان يجب أن يكون فعّالًا،
-- والجهاز يجب أن يكون مفعَّلًا، مهما كانت قيمة هذه الراية. فجهاز أُبطل أو
-- استُبدل لا يعرف حتى **حالة** اشتراك لم يعد يخصّه.
create or replace function public.authenticate_device_credential(
  p_credential_hash     text,
  p_require_serviceable boolean default true
)
returns table (
  out_activation_id    bigint,
  out_subscription_id  bigint,
  out_organization_id  bigint,
  out_device_name      text,
  out_activated_at     timestamptz,
  out_last_seen_at     timestamptz,
  out_status           text,
  out_starts_at        timestamptz,
  out_expires_at       timestamptz,
  out_seats            integer
)
language plpgsql
security definer
set search_path = public, pg_temp
as $auth_cred$
declare
  cred_row public.device_credentials%rowtype;
  act_row  public.device_activations%rowtype;
  sub_row  public.subscriptions%rowtype;
begin
  select * into cred_row
  from public.device_credentials
  where credential_hash = p_credential_hash
    and revoked_at is null;

  if not found then
    return;
  end if;

  select * into act_row
  from public.device_activations
  where id = cred_row.activation_id
    and revoked_at is null;

  if not found then
    return;
  end if;

  select * into sub_row
  from public.subscriptions
  where id = act_row.subscription_id;

  -- اشتراك محذوف: لا شيء يُعاد بأي حال — لا حالة تُخبَر عنها أصلًا.
  if not found then
    return;
  end if;

  if p_require_serviceable
     and (sub_row.status not in ('trial', 'active')
          or sub_row.expires_at <= now()) then
    return;
  end if;

  -- المصادقة نجحت: يُحدَّث أثر الاستعمال على البيان وعلى الجهاز معًا.
  update public.device_credentials
     set last_used_at = now() where id = cred_row.id;
  update public.device_activations
     set last_seen_at = now() where id = act_row.id
  returning * into act_row;

  -- ⚠️ `sub_row.status::text` لا `sub_row.status`.
  --
  -- العمود من النوع المعدود `subscription_status`، والمخرج معلَن `text`.
  -- PostgreSQL لا يحوّل بينهما ضمنيًا في `returns table`، بل يرفض التنفيذ
  -- بـ«structure of query does not match function result type» — **عند
  -- أول نداء لا عند الإنشاء**، فلا يظهر الخلل إلا على قاعدة حقيقية.
  --
  -- والمعلَن `text` عمدًا: توقيع الدالة لا يجب أن يتقيّد بنوع معدود، وإضافة
  -- حالة اشتراك جديدة يومًا يجب ألّا تستلزم تغيير توقيع دالة مصادقة.
  return query
    select act_row.id, act_row.subscription_id, sub_row.organization_id,
           act_row.device_name, act_row.activated_at, act_row.last_seen_at,
           sub_row.status::text, sub_row.starts_at, sub_row.expires_at,
           sub_row.seats;
end
$auth_cred$;

comment on function public.authenticate_device_credential(text, boolean) is
  'يصادق بيان اعتماد جهاز: البيان فعّال، والجهاز مفعّل، والاشتراك سارٍ (إلا لمسار الإخبار). للـBackend وحده.';

revoke all on function public.authenticate_device_credential(text, boolean)
  from public, anon, authenticated;
grant execute on function public.authenticate_device_credential(text, boolean)
  to service_role;

-- ⚠️ **لا تبقَ نسخة بتوقيع قديم.** تنفيذٌ سابق لهذه الهجرة كان قد أنشأ
-- `(text)` بلا الراية؛ تركها يبقي بابًا يصادق بلا فحص اشتراك.
drop function if exists public.authenticate_device_credential(text);


-- ----------------------------------------------------------------------------
-- ٧) التنظيف
-- ----------------------------------------------------------------------------
-- صفّ مبطَل منذ شهر لا فائدة منه: التفعيل نفسه يحفظ التاريخ، وهذا الصف
-- يحمل تجزئةً لا تُطابق شيئًا. تُستدعى من الـBackend عند كل إصدار.
create or replace function public.purge_revoked_device_credentials()
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $purge_creds$
declare
  removed integer;
begin
  delete from public.device_credentials
   where revoked_at is not null
     and revoked_at < now() - interval '30 days';
  get diagnostics removed = row_count;
  return removed;
end
$purge_creds$;

revoke all on function public.purge_revoked_device_credentials()
  from public, anon, authenticated;
grant execute on function public.purge_revoked_device_credentials()
  to service_role;


-- ============================================================================
-- ٨) اختبارات — تفشل الهجرة كلها إن اختلّ شرط
-- ============================================================================
create or replace function public.govmind_purge_credential_fixtures()
returns void
language plpgsql
as $purge_fx$
declare
  test_user constant uuid := '00000000-0000-4000-8000-0000000f0001';
  test_slug constant text := 'rls-test-credentials';
  test_orgs bigint[];
begin
  select coalesce(array_agg(id), '{}'::bigint[]) into test_orgs
  from public.organizations where slug = test_slug;

  delete from public.device_credentials
   where activation_id in (
     select id from public.device_activations
      where subscription_id in (
        select id from public.subscriptions where organization_id = any (test_orgs)
      )
   );
  delete from public.installation_sessions where organization_id = any (test_orgs);
  delete from public.audit_logs where organization_id = any (test_orgs);
  delete from public.device_activations
   where subscription_id in (
     select id from public.subscriptions where organization_id = any (test_orgs)
   );
  delete from public.subscriptions where organization_id = any (test_orgs);
  delete from public.organization_members where organization_id = any (test_orgs);
  delete from public.profiles
   where id = test_user or organization_id = any (test_orgs);
  delete from public.organizations where id = any (test_orgs);
  delete from auth.users where id = test_user;
end
$purge_fx$;


do $credential_tests$
declare
  test_user constant uuid := '00000000-0000-4000-8000-0000000f0001';
  device_a  constant text := repeat('1', 64);
  device_b  constant text := repeat('2', 64);
  cred_one  constant text := repeat('a', 64);
  cred_two  constant text := repeat('b', 64);
  cred_gone constant text := repeat('f', 64);
  org_id    bigint;
  sub_id    bigint;
  act_a     bigint;
  act_b     bigint;
  result    record;
  found_row record;
  rows_back integer;
  active    integer;
  raised    boolean;
begin
  raise notice 'GovMind: بدء اختبارات بيان اعتماد الجهاز…';
  perform public.govmind_purge_credential_fixtures();

  insert into public.organizations (name, slug)
  values ('مساحة اختبار بيان الاعتماد', 'rls-test-credentials') returning id into org_id;
  insert into auth.users (id, email) values (test_user, 'rls-credentials@govmind.test');
  insert into public.profiles (id, organization_id, email, full_name, role)
  values (test_user, org_id, 'rls-credentials@govmind.test', 'عميل اختبار', 'admin');
  insert into public.organization_members (organization_id, user_id, role)
  values (org_id, test_user, 'admin');
  insert into public.subscriptions (organization_id, status, seats, expires_at)
  values (org_id, 'trial', 1, now() + interval '30 days') returning id into sub_id;
  insert into public.device_activations (subscription_id, device_id_hash, device_name)
  values (sub_id, device_a, 'حاسب الاختبار') returning id into act_a;

  -- ---------------------------------------------------------------------
  -- اختبار ١: الإصدار ينشئ بيانًا فعّالًا واحدًا بلا إبطال شيء
  -- ---------------------------------------------------------------------
  select * into result from public.issue_device_credential(act_a, cred_one);
  if result.out_credential_id is null then
    raise exception 'خلل: لم يُصدَر بيان اعتماد';
  end if;
  if result.out_revoked_id is not null then
    raise exception 'خلل: أُبطل بيان ولا بيان سابق';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٢: **لا قيمة خام في القاعدة** — العمود يقبل التجزئة وحدها
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    insert into public.device_credentials (activation_id, credential_hash)
    values (act_a, 'raw-secret-value-not-a-hash');
  exception when check_violation then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قُبلت قيمة ليست تجزئة في credential_hash';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٣: المصادقة تنجح لبيان فعّال على اشتراك سارٍ
  -- ---------------------------------------------------------------------
  select * into found_row
  from public.authenticate_device_credential(cred_one);
  if found_row.out_activation_id is distinct from act_a then
    raise exception 'خلل: المصادقة لم تُرجع التفعيل الصحيح';
  end if;
  if found_row.out_organization_id is distinct from org_id then
    raise exception 'خلل: المصادقة أعادت جهة أخرى';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٤: بيان مجهول يُرفض بصفر صف — لا خطأ يفرّق الحالات
  -- ---------------------------------------------------------------------
  select count(*) into rows_back
  from public.authenticate_device_credential(cred_gone);
  if rows_back <> 0 then
    raise exception 'ثغرة: قُبل بيان اعتماد مجهول';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٥: التدوير يبطل السابق ويبقي بيانًا فعّالًا واحدًا
  -- ---------------------------------------------------------------------
  select * into result from public.issue_device_credential(act_a, cred_two);
  if result.out_revoked_id is null then
    raise exception 'خلل: التدوير لم يبطل البيان السابق';
  end if;

  select count(*) into active from public.device_credentials
   where activation_id = act_a and revoked_at is null;
  if active <> 1 then
    raise exception 'ثغرة: % بيان اعتماد فعّال بعد التدوير', active;
  end if;

  select count(*) into rows_back
  from public.authenticate_device_credential(cred_one);
  if rows_back <> 0 then
    raise exception 'ثغرة: بيان مُدوَّر ما زال يُقبل';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٦: **الفهرس الجزئي هو الحكم الأخير** على «بيان فعّال واحد»
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    insert into public.device_credentials (activation_id, credential_hash)
    values (act_a, repeat('c', 64));
  exception when unique_violation then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قُبل بيان اعتماد فعّال ثانٍ على التفعيل نفسه';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٧: **استبدال الجهاز يبطل بيان اعتماد الجهاز السابق**
  -- ---------------------------------------------------------------------
  select * into result
  from public.replace_device_activation(sub_id, device_b, 'حاسب بديل');
  act_b := result.out_activation_id;

  select count(*) into rows_back
  from public.authenticate_device_credential(cred_two);
  if rows_back <> 0 then
    raise exception 'ثغرة: بيان اعتماد جهاز مستبدَل ما زال يُقبل';
  end if;

  select count(*) into active from public.device_credentials
   where activation_id = act_a and revoked_at is null;
  if active <> 0 then
    raise exception 'ثغرة: بقي % بيان فعّال على جهاز أُبطل', active;
  end if;

  -- ⚠️ **ولا حتى مسار الإخبار**: جهاز أُبطل لا يعرف حالة اشتراك لم يعد
  -- يخصّه. الراية تستثني فحص الاشتراك وحده، لا فحص الجهاز ولا البيان.
  select count(*) into rows_back
  from public.authenticate_device_credential(cred_two, false);
  if rows_back <> 0 then
    raise exception 'ثغرة: مسار الإخبار قَبِل بيان جهاز مستبدَل';
  end if;

  -- وتاريخ الأجهزة **يبقى**: الإبطال لا يمحو صفًّا.
  select count(*) into rows_back from public.device_activations
   where subscription_id = sub_id;
  if rows_back <> 2 then
    raise exception 'خلل: سجل الأجهزة يجب أن يحفظ المبطل والفعّال (% صف)', rows_back;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٨: لا يُصدَر بيان اعتماد لتفعيل مبطَل
  -- ---------------------------------------------------------------------
  raised := false;
  begin
    perform public.issue_device_credential(act_a, repeat('d', 64));
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: صدر بيان اعتماد لجهاز مبطَل';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٩: اشتراك منتهٍ أو موقوف أو ملغى يُبطل المصادقة **فورًا**
  -- ---------------------------------------------------------------------
  perform public.issue_device_credential(act_b, repeat('e', 64));

  select count(*) into rows_back
  from public.authenticate_device_credential(repeat('e', 64));
  if rows_back <> 1 then
    raise exception 'خلل: لم تنجح المصادقة على الجهاز البديل';
  end if;

  update public.subscriptions set status = 'expired' where id = sub_id;
  select count(*) into rows_back
  from public.authenticate_device_credential(repeat('e', 64));
  if rows_back <> 0 then
    raise exception 'ثغرة: قُبل بيان اعتماد على اشتراك منتهٍ';
  end if;

  update public.subscriptions set status = 'suspended' where id = sub_id;
  select count(*) into rows_back
  from public.authenticate_device_credential(repeat('e', 64));
  if rows_back <> 0 then
    raise exception 'ثغرة: قُبل بيان اعتماد على اشتراك موقوف';
  end if;

  update public.subscriptions set status = 'cancelled' where id = sub_id;
  select count(*) into rows_back
  from public.authenticate_device_credential(repeat('e', 64));
  if rows_back <> 0 then
    raise exception 'ثغرة: قُبل بيان اعتماد على اشتراك ملغى';
  end if;

  -- **حالة سارية بتاريخ ماضٍ اشتراكٌ منتهٍ**: الحالة والتاريخ معًا.
  --
  -- ⚠️ `starts_at` يُرجَع معه: قيد `ck_subscriptions_window` يشترط
  -- `expires_at > starts_at`، فتأخيرُ الانتهاء وحده يخالف القيد ويفشل
  -- التحديث قبل أن يُختبر شيء.
  update public.subscriptions
     set status     = 'active',
         starts_at  = now() - interval '30 days',
         expires_at = now() - interval '1 day'
   where id = sub_id;
  select count(*) into rows_back
  from public.authenticate_device_credential(repeat('e', 64));
  if rows_back <> 0 then
    raise exception 'ثغرة: قُبل بيان اعتماد على اشتراك تجاوز تاريخه';
  end if;

  -- ...ومع ذلك، **مسار الإخبار وحده** يعيد الحالة ليعرضها العميل، بشرط
  -- أن يكون البيان والجهاز فعّالين.
  select count(*) into rows_back
  from public.authenticate_device_credential(repeat('e', 64), false);
  if rows_back <> 1 then
    raise exception 'خلل: مسار الإخبار لم يُرجع حالة اشتراك منتهٍ';
  end if;

  update public.subscriptions
     set status     = 'trial',
         starts_at  = now() - interval '1 day',
         expires_at = now() + interval '30 days'
   where id = sub_id;

  -- ---------------------------------------------------------------------
  -- اختبار ١٠: **عزل** — بيان اعتماد لا يصل جهة أخرى
  -- ---------------------------------------------------------------------
  -- الدالة تشتقّ الجهة والاشتراك من التفعيل نفسه، ولا تقبل معرّفًا من
  -- المستدعي. فما يعود لا يمكن أن يخصّ غير صاحب البيان.
  select * into found_row
  from public.authenticate_device_credential(repeat('e', 64));
  if found_row.out_organization_id is distinct from org_id
     or found_row.out_subscription_id is distinct from sub_id then
    raise exception 'ثغرة: المصادقة أعادت اشتراك جهة أخرى';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ١١: **العميل المسجَّل لا يقرأ الجدول ولا ينفّذ الدوال**
  -- ---------------------------------------------------------------------
  set local role authenticated;
  raised := false;
  begin
    perform * from public.device_credentials;
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قرأ عميل مسجَّل جدول بيانات الاعتماد';
  end if;

  raised := false;
  begin
    perform public.authenticate_device_credential(repeat('e', 64));
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: نفّذ عميل مسجَّل دالة المصادقة';
  end if;

  raised := false;
  begin
    perform public.issue_device_credential(act_b, repeat('9', 64));
  exception when others then
    raised := true;
  end;
  reset role;
  if not raised then
    raise exception 'ثغرة: نفّذ عميل مسجَّل دالة الإصدار';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ١٢: التنظيف يحذف المبطَل القديم وحده
  -- ---------------------------------------------------------------------
  update public.device_credentials
     set revoked_at = now() - interval '60 days'
   where activation_id = act_a;

  perform public.purge_revoked_device_credentials();

  select count(*) into rows_back from public.device_credentials
   where activation_id = act_a;
  if rows_back <> 0 then
    raise exception 'خلل: لم يُنظَّف بيان اعتماد مبطَل منذ شهرين';
  end if;

  select count(*) into rows_back from public.device_credentials
   where activation_id = act_b and revoked_at is null;
  if rows_back <> 1 then
    raise exception 'ثغرة: حذف التنظيف بيانًا فعّالًا';
  end if;

  perform public.govmind_purge_credential_fixtures();
  raise notice 'GovMind: اجتازت اختبارات بيان اعتماد الجهاز الاثنا عشر ✔';
end
$credential_tests$;


-- ----------------------------------------------------------------------------
-- ٩) انحدار التنظيف — لا يبقى صفّ اختبار واحد
-- ----------------------------------------------------------------------------
do $credential_cleanup_check$
declare
  remaining integer;
begin
  perform public.govmind_purge_credential_fixtures();
  select
    (select count(*) from public.organizations where slug = 'rls-test-credentials')
  + (select count(*) from auth.users where email = 'rls-credentials@govmind.test')
  + (select count(*) from public.device_credentials
       where credential_hash in (repeat('a', 64), repeat('b', 64), repeat('e', 64)))
  into remaining;

  if remaining <> 0 then
    raise exception 'خلل: بقي % صف اختبار بعد التنظيف', remaining;
  end if;
  raise notice 'GovMind: اجتاز اختبار انحدار تنظيف بيانات الاعتماد ✔';
end
$credential_cleanup_check$;

drop function if exists public.govmind_purge_credential_fixtures();


do $done$
begin
  raise notice 'GovMind: اكتملت الهجرة ٥ — بيانات اعتماد الجهاز جاهزة.';
end
$done$;
