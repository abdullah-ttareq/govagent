"""طبقة الوصول إلى Supabase عبر PostgREST.

**لماذا PostgREST لا اتصال PostgreSQL مباشر؟** لأن الـBackend يعمل خارج شبكة
Supabase، ومنفذ القاعدة قد يكون مغلقًا على مشاريع كثيرة، بينما واجهة REST
متاحة دائمًا على HTTPS. ولأن `httpx` مثبّتة أصلًا في المشروع، فلا حزمة
جديدة ولا درايفر يُبنى على السيرفر.

**الاتصال كسول عمدًا**، كما في `database/oracle.py`: لا يُنشأ عميل HTTP ولا
تُلمس الشبكة إلا عند أول استخدام فعلي. المشروع يقلع ويعمل بالكامل بـ
`DATA_STORE=memory` وحقول Supabase فارغة.

⚠️ **هذه الوحدة تستخدم `service_role`، وهو يتجاوز RLS بالكامل.**
الـBackend يفرض العزل بنفسه: كل دالة هنا تُستدعى بمرشّح جهة أو مستخدم من
الطبقة الأعلى، وسياسات RLS في `database/supabase/0001_govmind_supabase.sql`
هي خط الدفاع الثاني للعملاء الذين يتصلون بالقاعدة مباشرة (الواجهة والإضافة
لا تفعل ذلك اليوم أصلًا).

**المفتاح لا يظهر في أي رسالة خطأ ولا سجل**: `_translate_error` تعيد نصًّا
مكتوبًا يدويًا ولا تمرّر جسم رد Supabase كما هو.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.config import settings

#: المتغيرات التي بدونها لا يمكن الاتصال، بأسمائها كما تظهر في ملف .env.
_REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("SUPABASE_URL", "supabase_url"),
    ("SUPABASE_SERVICE_ROLE_KEY", "supabase_service_role_key"),
)


class SupabaseError(Exception):
    """خطأ في التعامل مع Supabase، برسالة عربية صالحة للعرض."""


class SupabaseNotConfiguredError(SupabaseError):
    """إعدادات Supabase ناقصة — حالة متوقعة في التشغيل المحلي."""


@dataclass(frozen=True)
class SupabaseStatus:
    """نتيجة فحص الحالة. تُستخدم في /health ولا ترفع استثناءً أبدًا."""

    configured: bool
    #: not_configured | ok | error
    status: str
    detail: str | None = None


_client: httpx.Client | None = None
_client_lock = threading.Lock()


# ---------------------------------------------------------------------------
# الإعدادات
# ---------------------------------------------------------------------------
def missing_settings() -> list[str]:
    """يعيد أسماء متغيرات Supabase الناقصة كما تظهر في .env."""
    return [
        env_name
        for env_name, field in _REQUIRED_SETTINGS
        if not (getattr(settings, field, "") or "").strip()
    ]


def is_configured() -> bool:
    """هل ضُبطت كل متغيرات Supabase المطلوبة؟ لا يفتح أي اتصال."""
    return not missing_settings()


def require_configuration() -> None:
    """يرفع خطأً واضحًا إن كان الإعداد ناقصًا.

    Raises:
        SupabaseNotConfiguredError: مع أسماء المتغيرات الناقصة.
    """
    missing = missing_settings()
    if missing:
        raise SupabaseNotConfiguredError(
            "إعداد Supabase غير مكتمل. المتغيرات الناقصة: "
            f"{'، '.join(missing)}. اضبطها في ملف .env على السيرفر."
        )


def rest_base_url() -> str:
    """عنوان واجهة الجداول. بلا / في آخره."""
    return settings.supabase_url.strip().rstrip("/") + "/rest/v1"


def auth_base_url() -> str:
    """عنوان واجهة المصادقة (GoTrue). بلا / في آخره."""
    return settings.supabase_url.strip().rstrip("/") + "/auth/v1"


# ---------------------------------------------------------------------------
# العميل
# ---------------------------------------------------------------------------
def get_client() -> httpx.Client:
    """يعيد عميل HTTP مشتركًا، وينشئه عند أول استدعاء فقط.

    Raises:
        SupabaseNotConfiguredError: إذا كانت المتغيرات ناقصة.
    """
    global _client
    if _client is not None:
        return _client

    require_configuration()
    key = settings.supabase_service_role_key.strip()

    with _client_lock:
        if _client is not None:
            return _client
        _client = httpx.Client(
            base_url=rest_base_url(),
            timeout=settings.supabase_timeout_seconds,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                # يجعل PostgREST يعيد الصفوف المكتوبة بدل جسم فارغ.
                "Prefer": "return=representation",
            },
        )
    return _client


def set_client(client: httpx.Client | None) -> None:
    """يستبدل العميل — **للاختبارات وحدها**.

    تُمرَّر ``httpx.Client(transport=httpx.MockTransport(...))`` فتُختبر
    الوحدة كاملة بما فيها بناء المسارات والمرشّحات، بلا شبكة ولا مشروع
    Supabase حقيقي. ``None`` يعيد الحالة إلى ما كانت.
    """
    global _client
    with _client_lock:
        if _client is not None and client is not _client:
            try:
                _client.close()
            except Exception:  # pragma: no cover - الإغلاق لا يُفشل شيئًا
                pass
        _client = client


def close_client() -> None:
    """يغلق العميل عند إيقاف التطبيق. آمن ولو لم يُنشأ عميل أصلًا."""
    set_client(None)


# ---------------------------------------------------------------------------
# ترجمة الأخطاء
# ---------------------------------------------------------------------------
#: رموز PostgreSQL التي لها معنى في مجال العمل، لا خللًا في السيرفر.
UNIQUE_VIOLATION = "23505"
FOREIGN_KEY_VIOLATION = "23503"
CHECK_VIOLATION = "23514"


class SupabaseConstraintError(SupabaseError):
    """قيد في القاعدة رفض الكتابة. يحمل رمز PostgreSQL للتمييز."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


def _translate_status(status_code: int) -> str:
    if status_code in (401, 403):
        return (
            "رفضت Supabase صلاحية الـBackend. راجع SUPABASE_SERVICE_ROLE_KEY "
            "في ملف .env على السيرفر."
        )
    if status_code == 404:
        return (
            "المسار المطلوب غير موجود في Supabase. تأكد من تنفيذ ملف الهجرة "
            "database/supabase/0001_govmind_supabase.sql على المشروع."
        )
    if status_code >= 500:
        return "خدمة Supabase لا تستجيب حاليًا. أعد المحاولة بعد قليل."
    return "تعذّر تنفيذ العملية على Supabase. راجع سجل السيرفر للتفصيل."


def _raise_for_response(response: httpx.Response) -> None:
    """يحوّل ردًّا فاشلًا إلى استثناء برسالة عربية، بلا كشف أي مفتاح."""
    if response.is_success:
        return

    code = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            code = str(body.get("code") or "")
    except Exception:
        body = None

    if code == UNIQUE_VIOLATION:
        raise SupabaseConstraintError(
            "القيمة مستخدمة مسبقًا ولا تقبل التكرار.", UNIQUE_VIOLATION
        )
    if code == FOREIGN_KEY_VIOLATION:
        raise SupabaseConstraintError(
            "السجل المرتبط غير موجود، فلا يمكن إتمام العملية.",
            FOREIGN_KEY_VIOLATION,
        )
    if code == CHECK_VIOLATION:
        raise SupabaseConstraintError(
            "القيمة المرسلة لا تحقّق شروط القاعدة.", CHECK_VIOLATION
        )

    raise SupabaseError(_translate_status(response.status_code))


def _request(
    method: str,
    table: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    prefer: str | None = None,
) -> list[dict[str, Any]]:
    client = get_client()
    headers = {"Prefer": prefer} if prefer else None

    try:
        response = client.request(
            method, f"/{table}", params=params, json=json, headers=headers
        )
    except httpx.TimeoutException as exc:
        raise SupabaseError(
            "انتهت مهلة الاتصال بـSupabase قبل وصول الرد. راجع الشبكة."
        ) from exc
    except httpx.HTTPError as exc:
        raise SupabaseError(
            "تعذّر الوصول إلى Supabase. راجع SUPABASE_URL واتصال السيرفر "
            "بالإنترنت."
        ) from exc

    _raise_for_response(response)

    if not response.content:
        return []
    payload = response.json()
    if payload is None:
        return []
    return payload if isinstance(payload, list) else [payload]


# ---------------------------------------------------------------------------
# عمليات الجداول
# ---------------------------------------------------------------------------
def select(
    table: str,
    *,
    columns: str = "*",
    filters: dict[str, str] | None = None,
    order: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """يقرأ صفوفًا من جدول.

    ``filters`` بصيغة PostgREST: ``{"organization_id": "eq.3"}``. تُمرَّر
    كما هي إلى ``params`` فيُرمّزها ``httpx`` — لا تُدمج في نص المسار، فلا
    مجال لحقن قيمة في الاستعلام.
    """
    params: dict[str, Any] = {"select": columns}
    if filters:
        params.update(filters)
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = str(limit)
    if offset:
        params["offset"] = str(offset)
    return _request("GET", table, params=params)


def select_one(
    table: str, *, columns: str = "*", filters: dict[str, str]
) -> dict[str, Any] | None:
    """يقرأ صفًّا واحدًا أو ``None``. يقيّد الطلب بصف واحد على السيرفر."""
    rows = select(table, columns=columns, filters=filters, limit=1)
    return rows[0] if rows else None


def insert(table: str, row: dict[str, Any]) -> dict[str, Any]:
    """يدرج صفًّا ويعيده كما استقر في القاعدة.

    Raises:
        SupabaseConstraintError: عند مخالفة قيد (تكرار أو مفتاح أجنبي).
        SupabaseError: عند أي فشل آخر.
    """
    rows = _request("POST", table, json=row)
    if not rows:
        raise SupabaseError("لم تُعِد Supabase الصف بعد إدراجه.")
    return rows[0]


def update(
    table: str, values: dict[str, Any], *, filters: dict[str, str]
) -> list[dict[str, Any]]:
    """يحدّث الصفوف المطابقة ويعيدها.

    ``filters`` **إلزامي**: تحديث بلا مرشّح يطال الجدول كله، وهو خطأ لا
    يمكن التراجع عنه. الشرط هنا يجعله مستحيلًا لا مستبعَدًا.
    """
    if not filters:
        raise SupabaseError("تحديث بلا مرشّح ممنوع: كان سيطال الجدول كله.")
    return _request("PATCH", table, params=dict(filters), json=values)


def delete(table: str, *, filters: dict[str, str]) -> list[dict[str, Any]]:
    """يحذف الصفوف المطابقة. ``filters`` إلزامي للسبب نفسه في ``update``."""
    if not filters:
        raise SupabaseError("حذف بلا مرشّح ممنوع: كان سيطال الجدول كله.")
    return _request("DELETE", table, params=dict(filters))


def rpc(function_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """ينادي دالة PostgreSQL عبر ``POST /rest/v1/rpc/<name>``.

    **الطريق الوحيد إلى عملية ذرّية عبر PostgREST.** لا معاملة تمتدّ عبر
    طلبين، فما يجب أن ينجح أو يفشل معًا يُكتب دالةً في القاعدة ويُنادى من
    هنا. انظر ``redeem_installation_session``.

    رسالة الخطأ من PostgreSQL تُمرَّر في الاستثناء ليصنّفها المستدعي، ولا
    تصل المستخدم: طبقة الخدمة تترجمها إلى رسالة عربية.
    """
    client = get_client()
    try:
        response = client.post(f"/rpc/{function_name}", json=payload)
    except httpx.TimeoutException as exc:
        raise SupabaseError(
            "انتهت مهلة الاتصال بـSupabase قبل وصول الرد. راجع الشبكة."
        ) from exc
    except httpx.HTTPError as exc:
        raise SupabaseError("تعذّر الوصول إلى Supabase.") from exc

    if not response.is_success:
        # رمز PostgreSQL ورسالته يحسمان نوع الفشل لطبقة الخدمة. لا مفاتيح
        # هنا: جسم الرد من القاعدة لا من إعداد السيرفر.
        code, message = "", ""
        try:
            body = response.json()
            if isinstance(body, dict):
                code = str(body.get("code") or "")
                message = str(body.get("message") or "")
        except Exception:
            pass
        raise SupabaseError(f"{code} {message}".strip() or _translate_status(response.status_code))

    if not response.content:
        return []
    payload_out = response.json()
    if payload_out is None:
        return []
    return payload_out if isinstance(payload_out, list) else [payload_out]


def count(table: str, *, filters: dict[str, str] | None = None) -> int:
    """يعدّ الصفوف المطابقة بلا جلبها.

    يستعمل ترويسة ``Prefer: count=exact`` ويقرأ العدد من ``Content-Range``:
    جلب الصفوف كلها لعدّها يستهلك شبكة وذاكرة بلا فائدة.
    """
    client = get_client()
    params: dict[str, Any] = {"select": "id", "limit": "1"}
    if filters:
        params.update(filters)

    try:
        response = client.get(
            f"/{table}", params=params, headers={"Prefer": "count=exact"}
        )
    except httpx.HTTPError as exc:
        raise SupabaseError("تعذّر الوصول إلى Supabase أثناء العدّ.") from exc

    _raise_for_response(response)

    # الصيغة: "0-0/17" أو "*/17" أو "*/*" حين يتعذّر العدّ.
    content_range = response.headers.get("content-range", "")
    total = content_range.rsplit("/", 1)[-1] if "/" in content_range else ""
    return int(total) if total.isdigit() else 0


# ---------------------------------------------------------------------------
# فحص الحالة — لا يرفع استثناءً أبدًا
# ---------------------------------------------------------------------------
def check_status() -> SupabaseStatus:
    """يفحص Supabase لأجل /health دون أن يُفشل الفحص عند غياب الإعداد."""
    missing = missing_settings()
    if missing:
        return SupabaseStatus(
            configured=False,
            status="not_configured",
            detail=(
                "Supabase غير مضبوطة (المتغيرات الناقصة: "
                f"{'، '.join(missing)}). النظام يعمل بدونها في وضع التطوير."
            ),
        )

    try:
        select("organizations", columns="id", limit=1)
    except SupabaseError as exc:
        return SupabaseStatus(configured=True, status="error", detail=str(exc))
    except Exception:
        return SupabaseStatus(
            configured=True,
            status="error",
            detail="تعذّر الاتصال بـSupabase لسبب غير متوقع.",
        )
    return SupabaseStatus(configured=True, status="ok", detail=None)
