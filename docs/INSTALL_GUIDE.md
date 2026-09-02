# دليل التشغيل من الصفر — GovMind

يشرح هذا الدليل تشغيل النظام على جهاز جديد **من نسخة المستودع إلى محادثة
تعمل**. مكتوب لمن لم يفتح المشروع من قبل.

> **الوجهة:** بيئة تطوير أو عرض. النشر على سيرفر جهة حقيقية له متطلبات
> إضافية مذكورة في [قبل النشر على سيرفر جهة](#قبل-النشر-على-سيرفر-جهة).

---

## ١. المتطلبات

| الأداة | الإصدار | للتحقق |
| ------ | ------- | ------ |
| Python | 3.11 فأحدث | `python --version` |
| Node.js | 20 فأحدث | `node --version` |
| Git | أي حديث | `git --version` |
| Chrome أو Edge | حديث | لتجربة الإضافة |

**لا تحتاج Oracle، ولا حساب OCI، ولا أي مفتاح.** النظام يعمل بالكامل بمخزن
داخل الذاكرة وبمزود مودل تجريبي.

## ٢. نسخ المستودع

```bash
git clone <رابط المستودع> govagent-repo
cd govagent-repo
```

## ٣. ملف البيئة

```bash
cp .env.example .env
```

القيم الافتراضية كافية. الحقول المهمة:

| المتغيّر | الافتراضي | معناه |
| -------- | --------- | ----- |
| `MODEL_PROVIDER` | `mock` | مزود تجريبي بلا مودل حقيقي |
| `DATA_STORE` | `memory` | مخزن في الذاكرة، **يفرغ عند إعادة التشغيل** |
| `DEV_SEED_PASSWORD` | `GovAgent@2026` | كلمة مرور الحسابات التجريبية |
| `JWT_SECRET` | فارغ | يُولَّد عشوائيًا محليًا؛ **إلزامي خارج التطوير** |
| `PROVISIONING_KEY` | فارغ | مفتاح تجهيز الجهات؛ فارغًا يعطّل المسار بـ503 |
| `FRONTEND_URL` | `http://localhost:3000` | يُسمح به في CORS |

## ٤. تشغيل الـBackend

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

(على لينكس أو ماك استبدل `.venv/Scripts/` بـ`.venv/bin/` في كل الأوامر.)

ثم:

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

**تحقّق قبل المتابعة:**

* <http://localhost:8000/health> يعيد `"status": "ok"`
* <http://localhost:8000/docs> يفتح توثيق Swagger بالعربية

> حقل `oracle` في `/health` يظهر `not_configured` — **هذا صحيح ومتوقّع**،
> ولا يعني عطلًا. النظام يعمل بدونها.

## ٥. تشغيل الـFrontend

في طرفية ثانية، والـBackend يعمل:

```bash
cd frontend
npm install
npm run dev
```

الواجهة على <http://localhost:3000>.

سجّل الدخول بأي حساب من [الحسابات التجريبية](#٧-الحسابات-التجريبية).

## ٦. تحميل الإضافة

1. افتح `chrome://extensions` (أو `edge://extensions`).
2. فعّل **Developer mode**.
3. **Load unpacked** ← اختر مجلد `extension` (المجلد نفسه، لا `manifest.json`).
4. ثبّت الأيقونة من قائمة الإضافات واضغط عليها.
5. سجّل الدخول بالحساب نفسه.

التفاصيل في [`extension/README.md`](../extension/README.md).

## ٧. الحسابات التجريبية

كلمة المرور للجميع هي قيمة `DEV_SEED_PASSWORD` — افتراضها `GovAgent@2026`.

| البريد | الدور | الجهة | الاشتراك |
| ------ | ----- | ----- | -------- |
| `admin@digital-services.test` | مسؤول | هيئة الخدمات الرقمية | فعّال |
| `n.alharbi@digital-services.test` | موظف | هيئة الخدمات الرقمية | فعّال |
| `admin@urban-planning.test` | مسؤول | مركز التخطيط العمراني | فعّال |
| `l.aldosari@urban-planning.test` | موظف | مركز التخطيط العمراني | فعّال |
| `r.alanzi@national-archive.test` | موظف | هيئة الأرشيف الوطني | **منتهٍ** |

الجهتان الأوليان تُثبتان عزل البيانات، والثالثة تُختبر بها رسالة انتهاء
الاشتراك. القائمة كاملة في
[`mock-data/README.md`](../mock-data/README.md).

## ٨. التحقق من التركيب

```bash
# اختبارات الـBackend
cd backend && .venv/Scripts/python -m pytest

# بناء الواجهة وفحصها
cd ../frontend && npm run build && npx eslint .

# مجموعة Postman كاملة (من جذر المستودع)
npx newman run docs/postman/GovAgent.postman_collection.json \
  -e docs/postman/GovAgent.postman_environment.json \
  --env-var "dev_password=GovAgent@2026"
```

ثم امشِ على [قائمة الفحص اليدوي](MANUAL_TEST_CHECKLIST.md).

---

## أخطاء شائعة عند التركيب

| ما تراه | السبب والحل |
| ------- | ----------- |
| `ModuleNotFoundError: No module named 'bcrypt'` | لم تُثبَّت المتطلبات. أعد `pip install -r requirements.txt` داخل الـvenv. |
| الواجهة تعرض «تعذّر الاتصال بسيرفر جهتك» | الـBackend غير مشغّل، أو رابطه خطأ في صفحة الإعدادات. |
| «انتهى اشتراك جهتك…» | دخلت بحساب الجهة الثالثة عمدًا. استخدم جهة فعّالة. |
| مسار التجهيز يعيد **503** | `PROVISIONING_KEY` فارغ. هذا **مقصود**: المفتاح الفارغ يعطّل المسار ولا يفتحه. |
| الإضافة لا ترسل شيئًا | إذن النطاق غير ممنوح. اضغط «امنح الإذن» في رسالة الخطأ. |
| المحادثات اختفت بعد إعادة تشغيل السيرفر | `DATA_STORE=memory` غير دائم. متوقّع في التطوير. |

## قبل النشر على سيرفر جهة

النظام **بحالته هذه للتطوير والعرض**. قبل أي استخدام حقيقي يلزم:

1. **`JWT_SECRET`** قيمة ثابتة قوية — بدونه تسقط الجلسات عند كل إعادة تشغيل،
   ويُرفض التشغيل خارج `APP_ENV=development` أصلًا.
2. **`PROVISIONING_KEY`** قيمة قوية، وإلا بقي مسار تجهيز الجهات معطّلًا.
3. **`DATA_STORE=oracle`** وتشغيل [`database/schema.sql`](../database/schema.sql):
   مخزن الذاكرة يفقد كل شيء عند إعادة التشغيل، **ومنه سجل التدقيق** — وسجل
   تدقيق يفقد أحداثه لا يصلح دليلًا.
4. **`MODEL_PROVIDER`** إلى مزود حقيقي — المزود التجريبي لا يجيب فعليًا.
5. **HTTPS** أمام الخدمة، و`FRONTEND_URL` على النطاق الحقيقي.
6. مراجعة `.env` والتأكد أنه **ليس** في المستودع.

> **لم يُجرَّب أيٌّ من هذه الست في هذا المشروع.** كل ما وُثّق هنا نُفِّذ على
> `mock` و `memory` محليًا.
