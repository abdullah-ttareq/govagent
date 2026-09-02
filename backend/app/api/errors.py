"""معالجة الأخطاء الموحّدة لكل مسارات الـAPI.

ثلاثة معالجات تغطي كل ما قد يخرج من التطبيق:

* :func:`http_exception_handler` — كل ``HTTPException`` التي ترفعها المسارات،
  وكذلك ما ترفعه Starlette نفسها (404 لمسار غير موجود، 405 لطريقة غير
  مسموحة). رسائل Starlette الافتراضية **إنجليزية**، فتُستبدل بالعربية هنا.
* :func:`validation_exception_handler` — أخطاء التحقق من الطلب.
* :func:`unhandled_exception_handler` — أي استثناء لم يُتوقَّع: يُسجَّل كاملًا
  على السيرفر، ويصل المستخدم رسالة عربية عامة **بلا أي تفصيل داخلي**.

**قاعدة عدم التسريب:** لا يخرج من هنا Stack Trace ولا اسم ملف ولا نص استثناء
ولا قيمة أرسلها المستخدم. رد التحقق في FastAPI كان يعيد ``input`` — أي الحقل
كما وصل — فكلمة مرور قصيرة تعود نصًّا صريحًا؛ ويعيد ``ctx`` وفيه رسائل المحلّل
الداخلية. الحقلان محذوفان هنا.
"""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

#: رسالة عربية افتراضية لكل حالة. تُستخدم حين لا يوفّر المسار رسالته الخاصة،
#: أو حين تكون الرسالة من Starlette نفسها (وهي إنجليزية دائمًا).
ARABIC_MESSAGES: dict[int, str] = {
    400: "الطلب غير صالح. راجع صيغة البيانات المُرسَلة.",
    401: (
        "هذا المسار يتطلب تسجيل الدخول. أرسل رمز الدخول في ترويسة "
        "Authorization بالشكل: Bearer <token>."
    ),
    403: "لا تملك صلاحية تنفيذ هذا الإجراء.",
    404: "المسار أو السجل المطلوب غير موجود.",
    405: "طريقة الطلب غير مسموحة على هذا المسار.",
    409: "تعارض مع بيانات موجودة في النظام.",
    413: "حجم الطلب يتجاوز الحد المسموح.",
    415: "صيغة المحتوى غير مدعومة.",
    422: "تعذّر قبول البيانات المُرسَلة.",
    429: "عدد الطلبات تجاوز الحد المسموح. حاول بعد قليل.",
    500: (
        "حدث خطأ غير متوقع في الخدمة. حاول مرة أخرى، وإن تكرر فتواصل مع "
        "الدعم."
    ),
    503: "الخدمة غير متاحة حاليًا. حاول بعد قليل.",
}

#: معرّف نصي ثابت لكل حالة، يُبنى عليه منطق العميل بدل مطابقة نص الرسالة.
ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}

#: ترجمة أنواع أخطاء pydantic الشائعة. مُحقِّقاتنا تكتب رسائلها بالعربية
#: أصلًا، وهذه للأنواع المدمجة التي رسائلها إنجليزية.
_PYDANTIC_MESSAGES: dict[str, str] = {
    "missing": "هذا الحقل مطلوب.",
    "string_too_short": "القيمة أقصر من الحد المسموح.",
    "string_too_long": "القيمة أطول من الحد المسموح.",
    "string_type": "القيمة يجب أن تكون نصًّا.",
    "int_type": "القيمة يجب أن تكون رقمًا صحيحًا.",
    "int_parsing": "القيمة يجب أن تكون رقمًا صحيحًا.",
    "float_parsing": "القيمة يجب أن تكون رقمًا.",
    "bool_parsing": "القيمة يجب أن تكون true أو false.",
    "datetime_parsing": "صيغة التاريخ غير صحيحة.",
    "greater_than": "القيمة أصغر من الحد المسموح.",
    "greater_than_equal": "القيمة أصغر من الحد المسموح.",
    "less_than": "القيمة أكبر من الحد المسموح.",
    "less_than_equal": "القيمة أكبر من الحد المسموح.",
    "too_short": "عدد العناصر أقل من الحد المسموح.",
    "too_long": "عدد العناصر أكثر من الحد المسموح.",
    "literal_error": "القيمة غير مقبولة ضمن القيم المتاحة.",
    "enum": "القيمة غير مقبولة ضمن القيم المتاحة.",
    "value_error": "القيمة غير مقبولة.",
}

#: pydantic يسبق رسائل المُحقِّقات المخصصة بهذه البادئة الإنجليزية.
_VALUE_ERROR_PREFIX = "Value error, "

#: أقصى عدد أخطاء حقول تُذكر في نص ``detail``. الباقي في ``errors``.
_MAX_SUMMARISED_FIELDS = 3


def default_message(status_code: int) -> str:
    """الرسالة العربية الافتراضية للحالة، أو رسالة 500 إن كانت غير معروفة."""
    return ARABIC_MESSAGES.get(status_code, ARABIC_MESSAGES[500])


def error_code(status_code: int) -> str:
    """المعرّف النصي للحالة."""
    return ERROR_CODES.get(status_code, "error")


def build_payload(
    *,
    status_code: int,
    detail: str,
    errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """يبني غلاف الخطأ الموحّد.

    ``errors`` موجود دائمًا ولو فارغًا، فيبقى شكل الرد واحدًا في كل الحالات.
    """
    return {
        "detail": detail,
        "status": status_code,
        "code": error_code(status_code),
        "errors": errors or [],
    }


def _is_starlette_default(status_code: int, detail: Any) -> bool:
    """هل الرسالة هي عبارة HTTP الإنجليزية التي تضعها Starlette تلقائيًا؟

    ``Not Found`` و ``Method Not Allowed`` وأمثالهما تصل من Starlette لا من
    مسارات المشروع، فتُستبدل بالعربية. الرسائل التي نكتبها نحن تمر كما هي.
    """
    if not isinstance(detail, str):
        return True
    try:
        return detail == HTTPStatus(status_code).phrase
    except ValueError:
        return False


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """يوحّد كل ``HTTPException`` في الغلاف الواحد.

    ``exc.headers`` تُمرَّر كما هي: ترويسة ``WWW-Authenticate`` جزء من عقد
    401 القياسي، وإسقاطها هنا يكسر العملاء الذين يعتمدون عليها.
    """
    detail = (
        default_message(exc.status_code)
        if _is_starlette_default(exc.status_code, exc.detail)
        else str(exc.detail)
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=build_payload(status_code=exc.status_code, detail=detail),
        headers=getattr(exc, "headers", None),
    )


def _field_path(location: tuple[Any, ...]) -> str:
    """يحوّل موضع الخطأ إلى مسار مقروء مثل ``body.email``.

    الجزء الأول (body / query / path) يبقى عمدًا: الحقل ``limit`` قد يكون في
    الاستعلام وفي الجسم، فحذفه يجعل الرسالة ملتبسة.
    """
    return ".".join(str(part) for part in location) or "body"


def _field_message(error: dict[str, Any]) -> str:
    """يستخرج رسالة عربية للحقل، بلا قيمة المستخدم وبلا تفاصيل المحلّل."""
    raw = str(error.get("msg", "")).strip()
    if raw.startswith(_VALUE_ERROR_PREFIX):
        # مُحقِّقاتنا تكتب رسالتها بالعربية، وpydantic يسبقها ببادئة إنجليزية.
        return raw[len(_VALUE_ERROR_PREFIX) :]
    translated = _PYDANTIC_MESSAGES.get(str(error.get("type", "")))
    return translated or raw or "القيمة غير مقبولة."


def _summarise(errors: list[dict[str, str]]) -> str:
    """يبني نص ``detail`` من أخطاء الحقول، ليكفي العميل الذي يعرضه وحده."""
    if not errors:
        return ARABIC_MESSAGES[422]
    shown = errors[:_MAX_SUMMARISED_FIELDS]
    parts = "؛ ".join(f"«{item['field']}»: {item['message']}" for item in shown)
    remaining = len(errors) - len(shown)
    suffix = f" (و{remaining} حقلًا آخر)" if remaining > 0 else ""
    return f"{ARABIC_MESSAGES[422]} {parts}{suffix}"


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """يحوّل أخطاء التحقق إلى الغلاف الموحّد، بلا تسريب المُدخَلات.

    جسم الطلب الذي ليس JSON صالحًا يعود **400** لا 422: العيب في صيغة الطلب
    نفسه لا في معاني حقوله، ولا حقول تُذكر أصلًا.
    """
    raw_errors = exc.errors()

    if any(item.get("type") == "json_invalid" for item in raw_errors):
        return JSONResponse(
            status_code=400,
            content=build_payload(
                status_code=400,
                detail=(
                    "تعذّرت قراءة جسم الطلب: المحتوى ليس JSON صالحًا. تأكد من "
                    "صيغة البيانات ومن ترويسة Content-Type."
                ),
            ),
        )

    # يُبنى كل عنصر من الموضع والرسالة فقط: input و ctx لا يخرجان إطلاقًا.
    errors = [
        {
            "field": _field_path(item.get("loc", ())),
            "message": _field_message(item),
        }
        for item in raw_errors
    ]
    return JSONResponse(
        status_code=422,
        content=build_payload(
            status_code=422, detail=_summarise(errors), errors=errors
        ),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """آخر خط دفاع: يمنع تسرّب أي خطأ غير متوقع إلى المستخدم.

    التفصيل الكامل يُسجَّل على السيرفر مع الـTraceback، ويصل المستخدم رسالة
    عربية عامة. لا نوع الاستثناء ولا نصه ولا مسار الملف يخرج في الرد: كلها
    تصف بنية النظام الداخلية لمن لا يملك حق معرفتها.
    """
    logger.exception(
        "خطأ غير متوقع أثناء معالجة الطلب: %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content=build_payload(status_code=500, detail=default_message(500)),
    )


def register_error_handlers(app: FastAPI) -> None:
    """يربط المعالجات الثلاثة بالتطبيق.

    ``StarletteHTTPException`` لا ``fastapi.HTTPException``: الأولى هي الأعمّ،
    وهي ما ترفعه Starlette للمسار غير الموجود وللطريقة غير المسموحة، والثانية
    ترث منها فتدخل في المعالج نفسه.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
