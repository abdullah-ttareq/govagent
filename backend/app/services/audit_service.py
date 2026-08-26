"""تسجيل الأحداث المهمة وقراءتها.

**التسجيل لا يُفشل العملية أبدًا.** `record` تبتلع أي خطأ وتعيد ``None``:
تعذُّر كتابة سطر في السجل يجب ألا يمنع موظفًا من تسجيل الدخول ولا من رفع ملف.

لكن الفشل **لا يمر صامتًا**: يُكتب تحذير في سجل التطبيق يذكر نوع الحدث
والجهة ونوع الخطأ، فيظهر في سجلات السيرفر ويمكن تتبّعه. سجل تدقيق يفقد
أحداثًا بلا أثر أسوأ من غيابه، لأنه يُعطي ثقة لا يستحقها.

**التحذير بلا بيانات حساسة:** لا يحمل ``details`` (وفيه بريد الموظف واسم
الملف)، ولا نص الاستثناء (وقد يحمل بيانات اتصال القاعدة). نوع الخطأ وحده
يكفي لتشخيص العطل.

**القراءة لمسؤول الجهة وحده، ولجهته وحدها.** السجل يكشف من فعل ماذا ومتى،
فهو أحسّ من قائمة الموظفين.
"""

from __future__ import annotations

import logging

from .audit_store import AuditEvent, get_audit_store
from .conversation_store import Page, resolve_page
from .user_store import User


logger = logging.getLogger(__name__)


class AuditError(Exception):
    """خطأ في قراءة سجل التدقيق، برسالة عربية صالحة للعرض."""


class AuditPermissionError(AuditError):
    """صاحب الطلب ليس مسؤول جهته."""


def record(
    *,
    organization_id: int,
    action: str,
    user_id: int | None = None,
    details: str | None = None,
) -> AuditEvent | None:
    """يسجّل حدثًا. يعيد ``None`` إن تعذّر التسجيل، ولا يرفع استثناءً.

    Args:
        organization_id: جهة الحدث — إلزامية، فلا حدث بلا جهة.
        user_id: صاحب الحدث، أو None لحدث سبق وجود مستخدم (تجهيز جهة).
        details: وصف قصير للعرض في لوحة المسؤول.
    """
    try:
        return get_audit_store().append(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            details=details,
        )
    except Exception as exc:  # noqa: BLE001 — السجل لا يُسقط العملية التي يصفها
        # بلا details وبلا نص الاستثناء: الأول يحمل بريدًا واسم ملف،
        # والثاني قد يحمل بيانات اتصال القاعدة. النوع وحده يكفي للتشخيص.
        logger.warning(
            "تعذّر حفظ حدث في سجل التدقيق: action=%s organization_id=%s "
            "error=%s. العملية الأصلية لم تتأثر.",
            action,
            organization_id,
            type(exc).__name__,
        )
        return None


def record_for(
    actor: User, *, action: str, details: str | None = None
) -> AuditEvent | None:
    """اختصار: يسجّل حدثًا بجهة صاحب الطلب ومعرّفه معًا."""
    return record(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action,
        details=details,
    )


def list_events(
    *,
    actor: User,
    action: str | None = None,
    user_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """يعيد أحداث جهة صاحب الطلب من الأحدث. لمسؤول الجهة فقط.

    Args:
        action: تصفية على نوع الحدث، أو None للكل.
        user_id: تصفية على موظف بعينه **داخل الجهة**، أو None للكل.

    Raises:
        AuditPermissionError: إذا لم يكن صاحب الطلب مسؤولًا.
    """
    if actor.role != "admin":
        raise AuditPermissionError(
            "سجل التدقيق متاح لمسؤول الجهة فقط. راجع مسؤول النظام في جهتك."
        )

    resolved_limit, resolved_offset = resolve_page(limit, offset)
    return get_audit_store().list_events(
        organization_id=actor.organization_id,
        action=action,
        user_id=user_id,
        limit=resolved_limit,
        offset=resolved_offset,
    )
