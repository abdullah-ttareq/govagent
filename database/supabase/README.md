# Supabase — تشغيل المخطط

| الملف | الغرض |
|---|---|
| [`0001_govmind_supabase.sql`](0001_govmind_supabase.sql) | الجداول العشرة، وسياسات RLS، واختبارات العزل. **ملف واحد يُنفَّذ كما هو.** |

> Oracle ومخزن الذاكرة **باقيان كما هما**. Supabase مزوّد بيانات ثالث
> يُختار بـ`DATA_STORE=supabase`، ولا يستبدل شيئًا.

---

## ١. التشغيل

1. افتح مشروعك في Supabase ← **SQL Editor** ← **New query**.
2. الصق محتوى `0001_govmind_supabase.sql` كاملًا.
3. اضغط **Run**.

الملف ينتهي بكتلة اختبارات تزرع جهتين وثلاثة مستخدمين، وتنتحل هوية كلٍّ
منهم عبر `set local role authenticated`، وتتحقق من ثمانية شروط عزل، ثم
تحذف كل ما زرعته. **فشل أي تأكيد يرفع استثناءً فتتراجع الهجرة كلها** — لا
يمكن أن يبقى في مشروعك مخطط ثبت تسريبه.

عند النجاح ترى في السجل:

```
NOTICE:  GovMind: بدء اختبارات العزل...
NOTICE:  GovMind: اجتازت اختبارات العزل الثمانية جميعها ✔
```

الملف قابل لإعادة التنفيذ: كل `create` بـ`if not exists`، وكل سياسة تُحذف
قبل إنشائها.

---

## ٢. تجهيز أول جهة وأول مسؤول

**لا يُنشأ شيء من هذا تلقائيًا**، وجهة بلا صف اشتراك ممنوعة من الخدمة
عمدًا (فشل مغلق).

```sql
-- ١) الجهة
insert into public.organizations (name, slug)
values ('اسم الجهة', 'org-slug')
returning id;

-- ٢) الحساب: من Dashboard ← Authentication ← Add user، ثم انسخ الـuuid.

-- ٣) الملف والعضوية والاشتراك
insert into public.profiles (id, organization_id, email, full_name, role)
values ('<uuid>', <org_id>, 'admin@org.gov.sa', 'اسم المسؤول', 'admin');

insert into public.organization_members (organization_id, user_id, role)
values (<org_id>, '<uuid>', 'admin');

insert into public.subscriptions (organization_id, status, seats, expires_at)
values (<org_id>, 'trial', 10, now() + interval '30 days');
```

---

## ٣. إدارة الأجهزة

كل اشتراك يعمل على **جهاز واحد**، يفرضه فهرس فريد جزئي لا فحصٌ في الكود.

```sql
-- أجهزة اشتراك جهة
select d.id, d.device_name, d.activated_at, d.last_seen_at, d.revoked_at
from public.device_activations d
join public.subscriptions s on s.id = d.subscription_id
where s.organization_id = <org_id>
order by d.activated_at desc;

-- إبطال تفعيل ليتمكّن العميل من تفعيل جهاز بديل
update public.device_activations set revoked_at = now() where id = <id>;
```

الصف **لا يُحذف**: تاريخ الأجهزة جزء من سجل الاشتراك، وملء `revoked_at`
يخرجه من الفهرس الجزئي فيصير المكان شاغرًا.

المسؤول يستطيع فعل الأمرين من الـAPI كذلك:
`GET /api/account/devices` و `POST /api/account/devices/{id}/revoke`.

---

## ٤. المفاتيح

| المفتاح | أين يوضع | لماذا |
|---|---|---|
| `anon` | الـBackend فقط (`SUPABASE_ANON_KEY`) | تسجيل الدخول. ليس سرًّا بطبيعته. |
| `service_role` | **الـBackend وحده** (`SUPABASE_SERVICE_ROLE_KEY`) | يتجاوز RLS بالكامل. |
| `JWT Secret` | الـBackend (`SUPABASE_JWT_SECRET`) | التحقق من رموز المستخدمين محليًا. |

> ⚠️ **`service_role` لا يوضع في الواجهة ولا في إضافة المتصفح إطلاقًا.**
> هو يتجاوز كل سياسات هذا الملف، فوجوده في العميل يُلغي العزل كله.
> الإضافة لا تعرف عنوان Supabase أصلًا: كل طلباتها تمرّ بالـBackend.
