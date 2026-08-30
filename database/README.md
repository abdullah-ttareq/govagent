# قاعدة بيانات GovMind — التشغيل والإعداد

هذا الملف يشرح كيف تُجهَّز قاعدة Oracle للنظام، وكيف يُشغَّل المخطط، وماذا
يفعل من لا يملك Oracle أصلًا.

| الملف | الغرض |
|---|---|
| [`schema.sql`](schema.sql) | إنشاء الجداول التسعة والفهارس. يُنفَّذ من أعلى إلى أسفل. |
| [`drop_all.sql`](drop_all.sql) | حذف كل الجداول لإعادة التشغيل. **للتطوير فقط.** |

---

## ١. هل أحتاج Oracle الآن؟

**لا.** النظام يقلع ويعمل بالكامل بدون قاعدة بيانات:

```bash
MODEL_PROVIDER=mock
ORACLE_DSN=
ORACLE_USER=
ORACLE_PASSWORD=
```

الاتصال **كسول**: لا يُفتح Pool ولا تُستورد حزمة `oracledb` إلا عند أول
استخدام فعلي للقاعدة. مع الحقول الفارغة لا يُلمس أي شيء من ذلك إطلاقًا،
و`/health` يعيد `status: "ok"` مع `oracle.status: "not_configured"`.

هذا هو الوضع المعتمد للتطوير المحلي وللعرض التجريبي.

---

## ٢. المتطلبات عند تفعيل Oracle

- **Oracle Database 23ai أو أحدث** — يلزم لعمود `VECTOR` في جدول
  `document_chunks` (البحث المتجهي في P1-04). على نسخة أقدم يفشل ذلك الجدول
  وحده بـ`ORA-00902`، والحل مشروح في التعليق فوقه داخل `schema.sql`.
- **ترميز القاعدة `AL32UTF8`** — بدونه تتلف العربية. للتحقق:
  ```sql
  SELECT value FROM nls_database_parameters WHERE parameter = 'NLS_CHARACTERSET';
  ```
- **حزمة `oracledb`** — مضمّنة في `backend/requirements.txt`. تعمل بوضع
  *thin* فلا تحتاج تثبيت Oracle Client على السيرفر.

> الأعمدة النصية معرّفة بدلالة **CHAR** لا BYTE (`VARCHAR2(200 CHAR)`)، لأن
> الحرف العربي يشغل بايتين في AL32UTF8. لولا ذلك لكان `VARCHAR2(200)` يتسع
> لمئة حرف عربي فقط.

---

## ٣. إنشاء المستخدم والقاعدة

يكفي مستخدم (Schema) واحد يملك جداول النظام. من حساب إداري:

```sql
CREATE USER govagent IDENTIFIED BY "ضع-كلمة-مرور-قوية-هنا";

GRANT CREATE SESSION       TO govagent;
GRANT CREATE TABLE         TO govagent;
GRANT CREATE SEQUENCE      TO govagent;
ALTER USER govagent QUOTA UNLIMITED ON users;
```

**لا تضع كلمة المرور في أي ملف داخل المستودع.** مكانها الوحيد هو `.env` على
السيرفر، وهو مستثنى من Git.

على **Autonomous Database** في OCI تُنشأ القاعدة من الـConsole، ويُستخدم
مستخدم `ADMIN` أو مستخدم جديد، مع Wallet أو اتصال TLS مباشر حسب الإعداد.

---

## ٤. تشغيل المخطط

من مجلد المشروع:

```bash
sqlplus govagent/كلمة-المرور@host:1521/service_name @database/schema.sql
```

أو من داخل SQL*Plus / SQLcl / SQL Developer:

```sql
@database/schema.sql
```

**الترتيب مهم** بسبب المفاتيح الأجنبية — نفّذ الملف من أعلى إلى أسفل ولا
تُشغّل أجزاءه متفرقة.

### التحقق بعد التشغيل

```sql
SELECT table_name FROM user_tables ORDER BY table_name;
```

يجب أن تظهر تسعة جداول: `AUDIT_LOGS` · `CONVERSATIONS` · `DOCUMENT_CHUNKS`
· `FILES` · `MESSAGES` · `MODEL_SETTINGS` · `ORGANIZATIONS` ·
`SUBSCRIPTIONS` · `USERS`.

### إعادة التشغيل على قاعدة غير نظيفة

`schema.sql` لا يحتوي `DROP`، فتشغيله مرتين يفشل بـ`ORA-00955`
(الاسم مستخدم مسبقًا). لإعادة البناء من الصفر:

```sql
@database/drop_all.sql
@database/schema.sql
```

⚠️ `drop_all.sql` يحذف كل البيانات نهائيًا. للتطوير فقط.

---

## ٥. ربط الـBackend

في `.env` على السيرفر:

```bash
ORACLE_DSN=host:1521/service_name
ORACLE_USER=govagent
ORACLE_PASSWORD=...
```

ثم تحقق من `/health`:

```bash
curl http://localhost:8000/health
```

| `oracle.status` | المعنى |
|---|---|
| `not_configured` | المتغيرات فارغة — النظام يعمل بدون قاعدة. |
| `ok` | الاتصال ناجح و`SELECT 1 FROM dual` يمر. |
| `error` | المتغيرات مضبوطة لكن الاتصال فشل، والسبب في `oracle.detail`. |

في الحالات الثلاث تبقى `status` الرئيسية `"ok"` — **حالة القاعدة لا تُفشل
فحص الخدمة**، لأن النظام مصمَّم للعمل بدونها.

رسائل الفشل عربية ومحددة، لا Stack Trace: كلمة مرور خاطئة، DSN غير صالح،
سيرفر غير متاح، انتهاء مهلة، حساب مقفل.

---

## ٦. ملاحظات على المخطط

- **العزل:** كل صف يخص جهة يحمل `organization_id`. كل استعلام في الـBackend
  يجب أن يُقيَّد به. هذا شرط أمني لا خيار تصميمي.
- **`updated_at`:** القيمة الافتراضية تُملأ عند الإدراج فقط. تحديثها عند كل
  تعديل مسؤولية الـBackend (`SET updated_at = SYSTIMESTAMP`). لا يوجد
  Trigger عمدًا ليبقى الملف قابلًا للتشغيل كسكربت SQL عادي.
- **الحذف المتسلسل:** حذف محادثة يحذف رسائلها، وحذف ملف يحذف مقاطعه، وحذف
  محادثة يُفرّغ `files.conversation_id` فقط. أما مفاتيح `organization_id`
  فبلا `CASCADE` عمدًا: حذف جهة بالخطأ يجب أن يفشل، لا أن يمسح بياناتها.
- **كلمات المرور:** تُخزَّن مُجزّأة (bcrypt) في `users.password_hash` فقط.
- **الأسرار:** لا يُخزَّن أي مفتاح أو بيانات اعتماد OCI في القاعدة. مكانها
  متغيرات البيئة على السيرفر.
