-- ============================================================================
-- GovMind — مخطط Supabase — الهجرة رقم ٤: استبدال الجهاز ذاتيًا
--
-- **نفّذ 0001 ثم 0002 ثم 0003 أولًا.** تحديثي (idempotent)، وينتهي
-- باختبارات تُفشل الهجرة إن اختلّ شرط.
--
-- ----------------------------------------------------------------------------
-- ما تحلّه
-- ----------------------------------------------------------------------------
-- في النموذج النهائي **لا يوجد مسؤول جهة ولا مسؤول نظام** يراجعه العميل:
-- كل عميل يملك حسابًا واحدًا واشتراكًا واحدًا وجهازًا فعّالًا واحدًا. فمن
-- غيّر حاسبه كان يقف أمام رسالة «راجع مسؤول النظام» ولا مسؤولَ ليراجعه.
--
-- هذه الدالة تعطيه الطريق بنفسه: **يُبطل جهازه السابق ويفعّل الحالي**،
-- بعد أن يثبت ملكيته للحساب بكلمة مروره (يتحقق منها الـBackend قبل
-- النداء — انظر `services/entitlement_service.replace_device`).
--
-- ----------------------------------------------------------------------------
-- لماذا دالة واحدة لا خطوتان
-- ----------------------------------------------------------------------------
-- «أبطل القديم» ثم «فعّل الجديد» عبر طلبين يتركان نافذتين:
--
--   * نجح الإبطال وفشل التفعيل ⇒ العميل بلا جهاز فعّال، وفقد ما كان يعمل.
--   * طلبان متزامنان ⇒ كلاهما يقرأ «يوجد جهاز واحد» فيبطلانه ويفعّلان
--     جهازين. الفهرس الفريد الجزئي يمنع الثاني، لكن الأول يكون قد أبطل
--     جهازًا لا داعي لإبطاله.
--
-- الحلّ هنا طبقتان:
--
--   ١) **قفل صف الاشتراك** (`for update`) يسلسل الاستبدالات على الاشتراك
--      الواحد، فلا يقرأ طلبان الحالة نفسها معًا.
--   ٢) **الفهرس الفريد الجزئي** `uq_device_activations_one_active` يبقى
--      الحكم الأخير: لو نفد القفل بأي حيلة، تفشل الكتابة الثانية بـ23505.
-- ============================================================================


do $preflight$
begin
  if to_regclass('public.device_activations') is null then
    raise exception 'GovMind: نفّذ 0001_govmind_supabase.sql أولًا.';
  end if;
  raise notice 'GovMind: تهيئة استبدال الجهاز…';
end
$preflight$;


-- ----------------------------------------------------------------------------
-- الدالة الذرّية
-- ----------------------------------------------------------------------------
-- ⚠️ **لا تتحقق من كلمة المرور.** التحقق عبر Supabase Auth في الـBackend
-- قبل النداء؛ القاعدة لا ترى كلمة مرور ولا تخزّنها.
--
-- ⚠️ **لا تتلقّى بصمة جهاز خامة.** تصلها التجزئة وحدها.

create or replace function public.replace_device_activation(
  p_subscription_id bigint,
  p_device_hash     text,
  p_device_name     text default 'جهاز غير مسمّى'
)
returns table (
  out_activation_id bigint,
  out_revoked_id    bigint,
  out_replaced      boolean
)
language plpgsql
security definer
set search_path = public, pg_temp
as $replace$
declare
  existing public.device_activations%rowtype;
  sub_row  public.subscriptions%rowtype;
  new_id   bigint;
  old_id   bigint := null;
begin
  -- ① قفل الاشتراك: يسلسل الاستبدالات المتزامنة على هذا الاشتراك وحده.
  select * into sub_row
  from public.subscriptions
  where id = p_subscription_id
  for update;

  if not found then
    raise exception 'subscription_not_found'
      using errcode = '22023', hint = 'لا يوجد اشتراك بهذا المعرّف.';
  end if;

  -- ② الاشتراك يجب أن يسمح بالخدمة **الآن**.
  if sub_row.status not in ('trial', 'active') or sub_row.expires_at <= now() then
    raise exception 'subscription_not_serviceable'
      using errcode = '22023', hint = 'الاشتراك لا يسمح بتفعيل جهاز حاليًا.';
  end if;

  -- ③ الجهاز الفعّال الحالي — يُقرأ **بعد** القفل لا قبله.
  select * into existing
  from public.device_activations
  where subscription_id = p_subscription_id
    and revoked_at is null;

  -- ④ الجهاز نفسه: لا شيء يُستبدل. عملية مُعادة التنفيذ لا خطأ — العميل
  --    قد يضغط الزرّ مرتين، أو تُعاد المحاولة بعد انقطاع شبكة.
  if found and existing.device_id_hash = p_device_hash then
    update public.device_activations
       set last_seen_at = now()
     where id = existing.id;
    return query select existing.id, null::bigint, false;
    return;
  end if;

  -- ⑤ إبطال السابق. الصف **يبقى** في السجل: تاريخ الأجهزة جزء من
  --    الاشتراك، والإبطال يخرجه من الفهرس الجزئي فيُفرغ المكان.
  if found then
    update public.device_activations
       set revoked_at = now()
     where id = existing.id;
    old_id := existing.id;
  end if;

  -- ⑥ تفعيل الحالي. لو أفلت طلبٌ متزامن من القفل لفشل هنا بـ23505.
  insert into public.device_activations
    (subscription_id, device_id_hash, device_name)
  values
    (p_subscription_id, p_device_hash,
     coalesce(nullif(btrim(p_device_name), ''), 'جهاز غير مسمّى'))
  returning id into new_id;

  insert into public.audit_logs (organization_id, action, entity_type, entity_id)
  values (sub_row.organization_id,
          case when old_id is null then 'device.activated' else 'device.replaced' end,
          'device_activation', new_id::text);

  return query select new_id, old_id, (old_id is not null);
end
$replace$;

comment on function public.replace_device_activation(bigint, text, text) is
  'يبطل الجهاز الفعّال ويفعّل غيره في معاملة واحدة. للـBackend وحده بعد التحقق من كلمة المرور.';

revoke all on function public.replace_device_activation(bigint, text, text)
  from public, anon, authenticated;
grant execute on function public.replace_device_activation(bigint, text, text)
  to service_role;


-- ============================================================================
-- اختبارات
-- ============================================================================
create or replace function public.govmind_purge_replacement_fixtures()
returns void
language plpgsql
as $purge_fx$
declare
  test_user constant uuid := '00000000-0000-4000-8000-0000000e0001';
  test_slug constant text := 'rls-test-replace';
  test_orgs bigint[];
begin
  select coalesce(array_agg(id), '{}'::bigint[]) into test_orgs
  from public.organizations where slug = test_slug;

  delete from public.installation_sessions where organization_id = any (test_orgs);
  delete from public.audit_logs where organization_id = any (test_orgs);
  delete from public.device_activations
   where subscription_id in (
     select id from public.subscriptions where organization_id = any (test_orgs)
   );
  delete from public.subscriptions where organization_id = any (test_orgs);
  delete from public.organization_members where organization_id = any (test_orgs);
  delete from public.profiles where organization_id = any (test_orgs);
  delete from public.organizations where id = any (test_orgs);
  delete from auth.users where id = test_user;
end
$purge_fx$;


do $replacement_tests$
declare
  test_user constant uuid := '00000000-0000-4000-8000-0000000e0001';
  device_a  constant text := repeat('a', 64);
  device_b  constant text := repeat('b', 64);
  device_c  constant text := repeat('c', 64);
  org_id    bigint;
  sub_id    bigint;
  result    record;
  active    integer;
  total     integer;
  raised    boolean;
begin
  raise notice 'GovMind: بدء اختبارات استبدال الجهاز…';
  perform public.govmind_purge_replacement_fixtures();

  insert into public.organizations (name, slug)
  values ('مساحة اختبار الاستبدال', 'rls-test-replace') returning id into org_id;
  insert into auth.users (id, email) values (test_user, 'rls-replace@govmind.test');
  insert into public.profiles (id, organization_id, email, full_name, role)
  values (test_user, org_id, 'rls-replace@govmind.test', 'عميل اختبار', 'admin');
  insert into public.organization_members (organization_id, user_id, role)
  values (org_id, test_user, 'admin');
  insert into public.subscriptions (organization_id, status, seats, expires_at)
  values (org_id, 'trial', 1, now() + interval '30 days') returning id into sub_id;

  -- ---------------------------------------------------------------------
  -- اختبار ١: أول جهاز يُفعَّل بلا إبطال شيء
  -- ---------------------------------------------------------------------
  select * into result
  from public.replace_device_activation(sub_id, device_a, 'حاسب أول');

  if result.out_replaced then
    raise exception 'خلل: أول تفعيل عُدَّ استبدالًا';
  end if;
  if result.out_revoked_id is not null then
    raise exception 'خلل: أُبطل جهاز ولا جهاز سابق';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٢: الاستبدال يبطل السابق ويفعّل الجديد
  -- ---------------------------------------------------------------------
  select * into result
  from public.replace_device_activation(sub_id, device_b, 'حاسب ثانٍ');

  if not result.out_replaced then
    raise exception 'خلل: لم يُسجَّل الاستبدال';
  end if;
  if result.out_revoked_id is null then
    raise exception 'خلل: لم يُبطل الجهاز السابق';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٣: **جهاز فعّال واحد لا غير**
  -- ---------------------------------------------------------------------
  select count(*) into active from public.device_activations
   where subscription_id = sub_id and revoked_at is null;
  if active <> 1 then
    raise exception 'ثغرة: % جهاز فعّال بعد الاستبدال', active;
  end if;

  -- والسجل يحتفظ بالمبطل: تاريخ الأجهزة لا يُمحى.
  select count(*) into total from public.device_activations
   where subscription_id = sub_id;
  if total <> 2 then
    raise exception 'خلل: سجل الأجهزة يجب أن يحفظ المبطل والفعّال (% صف)', total;
  end if;

  -- الجهاز الفعّال هو الجديد لا القديم.
  select count(*) into active from public.device_activations
   where subscription_id = sub_id and revoked_at is null
     and device_id_hash = device_b;
  if active <> 1 then
    raise exception 'خلل: الجهاز الفعّال ليس الجهاز الجديد';
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٤: تكرار الاستبدال بالجهاز نفسه لا يبطل شيئًا
  -- ---------------------------------------------------------------------
  select * into result
  from public.replace_device_activation(sub_id, device_b, 'حاسب ثانٍ');

  if result.out_replaced then
    raise exception 'خلل: عُدَّ الجهاز نفسه استبدالًا';
  end if;

  select count(*) into total from public.device_activations
   where subscription_id = sub_id;
  if total <> 2 then
    raise exception 'خلل: أُنشئ صف زائد لتكرار الجهاز نفسه (% صف)', total;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٥: **الفهرس الفريد هو الحكم الأخير**
  -- ---------------------------------------------------------------------
  -- إدراج مباشر لجهاز فعّال ثانٍ يجب أن يفشل مهما كان مصدره.
  raised := false;
  begin
    insert into public.device_activations (subscription_id, device_id_hash, device_name)
    values (sub_id, device_c, 'جهاز ثالث متزامن');
  exception when unique_violation then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: قُبل جهاز فعّال ثانٍ على الاشتراك';
  end if;

  select count(*) into active from public.device_activations
   where subscription_id = sub_id and revoked_at is null;
  if active <> 1 then
    raise exception 'ثغرة: % جهاز فعّال بعد محاولة الإدراج المتزامن', active;
  end if;

  -- ---------------------------------------------------------------------
  -- اختبار ٦: اشتراك منتهٍ يمنع الاستبدال
  -- ---------------------------------------------------------------------
  update public.subscriptions set status = 'expired' where id = sub_id;
  raised := false;
  begin
    perform public.replace_device_activation(sub_id, device_c, 'جهاز');
  exception when others then
    raised := true;
  end;
  if not raised then
    raise exception 'ثغرة: استُبدل جهاز على اشتراك منتهٍ';
  end if;
  update public.subscriptions set status = 'trial' where id = sub_id;

  -- ---------------------------------------------------------------------
  -- اختبار ٧: العميل المسجَّل لا ينفّذ الدالة
  -- ---------------------------------------------------------------------
  set local role authenticated;
  raised := false;
  begin
    perform public.replace_device_activation(sub_id, device_c, 'جهاز');
  exception when others then
    raised := true;
  end;
  reset role;
  if not raised then
    raise exception 'ثغرة: نفّذ عميل مسجَّل دالة الاستبدال';
  end if;

  perform public.govmind_purge_replacement_fixtures();
  raise notice 'GovMind: اجتازت اختبارات استبدال الجهاز السبعة ✔';
end
$replacement_tests$;


do $replacement_cleanup_check$
declare
  remaining integer;
begin
  perform public.govmind_purge_replacement_fixtures();
  select
    (select count(*) from public.organizations where slug = 'rls-test-replace')
  + (select count(*) from auth.users where email = 'rls-replace@govmind.test')
  into remaining;

  if remaining <> 0 then
    raise exception 'خلل: بقي % صف اختبار بعد التنظيف', remaining;
  end if;
  raise notice 'GovMind: اجتاز اختبار انحدار تنظيف الاستبدال ✔';
end
$replacement_cleanup_check$;

drop function if exists public.govmind_purge_replacement_fixtures();
