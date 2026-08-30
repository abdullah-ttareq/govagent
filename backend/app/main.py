"""نقطة تشغيل GovMind Backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .api.errors import register_error_handlers
from .core.config import settings
from .database import close_pool


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """دورة حياة التطبيق.

    لا يُفتح أي اتصال بقاعدة البيانات عند الإقلاع — الاتصال كسول ويُنشأ عند
    أول استخدام فعلي. المطلوب هنا هو الإغلاق النظيف فقط، وهو آمن حتى لو لم
    يُنشأ Pool إطلاقًا.
    """
    yield
    close_pool()


#: وصف كل مجموعة مسارات كما تظهر في /docs، بالترتيب نفسه.
OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "فحص حالة الخدمة والبيئة ومزود المودل وقاعدة البيانات.",
    },
    {
        "name": "auth",
        "description": (
            "تسجيل الدخول وبيانات الحساب. رمز الدخول المُعاد من "
            "`/api/auth/login` يُرسل في ترويسة `Authorization: Bearer <token>`، "
            "أو يُلصق في زر **Authorize** أعلى هذه الصفحة لتجربة المسارات "
            "المحمية. الرمز يحمل جهة الموظف ودوره، ومنه تُقرأ الجهة في كل "
            "مسار محمي — لا من جسم الطلب."
        ),
    },
    {
        "name": "organizations",
        "description": (
            "قراءة بيانات الجهة وتعديلها. **كل مسار مقيّد بجهة صاحب الرمز**، "
            "وأي معرّف لجهة أخرى يعيد 404 بلا بيانات. تجهيز جهة جديدة عملية "
            "تركيب يحرسها مفتاح `X-Provisioning-Key` لا رمز الدخول."
        ),
    },
    {
        "name": "users",
        "description": (
            "إدارة موظفي الجهة. مسؤول الجهة يدير موظفيه فقط، والموظف يرى "
            "نفسه فقط. الجهة تُقرأ من الرمز — **لا يوجد حقل "
            "`organization_id` في أي طلب**."
        ),
    },
    {
        "name": "conversations",
        "description": (
            "محادثات الموظف ورسائلها. **المحادثة خاصة بصاحبها لا بجهته**: "
            "زميل في الجهة نفسها — ولو كان مسؤولها — لا يراها. محادثة موظف "
            "آخر تعيد 404 بلا بيانات."
        ),
    },
    {
        "name": "files",
        "description": (
            "رفع الملفات وقراءة بياناتها. الصيغ المدعومة `.pdf` و `.docx` "
            "و `.txt`، والحد الأقصى من `UPLOAD_MAX_BYTES`. سجل الملف خاص "
            "بمالكه، ويُفهرس محتواه للبحث داخل الجهة."
        ),
    },
    {
        "name": "audit",
        "description": (
            "سجل تدقيق الجهة: من فعل ماذا ومتى. **لمسؤول الجهة ولجهته "
            "وحدها**، وهو سجل إضافة فقط لا يُعدَّل ولا يُحذف."
        ),
    },
    {
        "name": "chat",
        "description": (
            "إرسال الرسائل إلى الإيجنت والبحث في ملفات الجهة. **المسار محمي "
            "بالكامل**: كل طلب يتطلب رمز دخول، ويُحفظ كل تبادل في محادثته، "
            "ويأتي السياق من السيرفر لا من العميل. الطلب بلا رمز يعيد 401."
        ),
    },
]

#: وصف الواجهة كما يظهر أعلى /docs.
APP_DESCRIPTION = """مساعد ذكاء اصطناعي عام لموظفي الجهات الحكومية — نسخة MVP.

## المصادقة

سجّل الدخول عبر `POST /api/auth/login`، ثم الصق رمز الدخول في زر
**Authorize** أعلى هذه الصفحة، أو أرسله في ترويسة
`Authorization: Bearer <token>`.

الرمز يحمل معرّف الموظف وجهته ودوره. **جهة الموظف تُقرأ من الرمز دائمًا ولا
تُقبل من جسم الطلب في أي مسار** — وهو أساس عزل البيانات بين الجهات.

## شكل الأخطاء

كل الأخطاء تعيد **الغلاف نفسه** مهما كان المسار أو الحالة:

```json
{
  "detail": "المستخدم المطلوب غير موجود.",
  "status": 404,
  "code": "not_found",
  "errors": []
}
```

* `detail` — رسالة عربية صالحة للعرض على المستخدم مباشرة، **في كل الحالات**
  بما فيها أخطاء التحقق.
* `code` — معرّف نصي ثابت يُبنى عليه منطق العميل بدل مطابقة نص الرسالة.
* `errors` — تفصيل أخطاء الحقول، وهو فارغ في غير 422.

| الحالة | `code` | متى |
| ------ | ------ | --- |
| 400 | `bad_request` | جسم الطلب ليس JSON صالحًا |
| 401 | `unauthorized` | رمز الدخول مفقود أو تالف أو منتهي الصلاحية |
| 403 | `forbidden` | الدور لا يسمح، أو الحساب معطّل، أو اشتراك الجهة منتهٍ |
| 404 | `not_found` | السجل غير موجود **في نطاق صاحب الطلب** |
| 409 | `conflict` | بريد مكرر، أو تراخيص مستنفدة |
| 413 | `payload_too_large` | حجم الملف يتجاوز الحد |
| 415 | `unsupported_media_type` | صيغة ملف غير مدعومة |
| 422 | `validation_error` | حقل مرفوض — التفصيل في `errors` |
| 500 | `internal_error` | خطأ غير متوقع |
| 503 | `service_unavailable` | تعذّر الوصول إلى مزود المودل أو إعداد ناقص |

**لا يخرج في أي رد Stack Trace ولا تفاصيل داخلية ولا القيمة التي أرسلها
المستخدم.** التفصيل الكامل يُسجَّل على السيرفر وحده.

> **هذا مشروع تخرج في مرحلة MVP.** لا تُستخدم فيه بيانات حكومية حقيقية ولا
> بيانات اعتماد حقيقية."""

app = FastAPI(
    title="GovMind API",
    description=APP_DESCRIPTION,
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)

# قبل أي شيء آخر: شكل خطأ واحد لكل المسارات، ولا تسريب لتفاصيل داخلية.
register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    # إضافة المتصفح (extension/) تعمل من أصل chrome-extension://<id>، ومعرّف
    # الإضافة يتغيّر عند كل Load unpacked، لذلك يُسمح به بنمط بدل قيمة ثابتة.
    allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
