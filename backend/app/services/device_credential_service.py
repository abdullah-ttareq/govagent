"""إصدار بيانات اعتماد الأجهزة والمصادقة بها.

**ما تغيّر ولماذا.** كان الـRuntime يصادق بسرّ **ولّده هو** على الجهاز.
ذلك يصفه معرّفَ جهاز لا بيانَ اعتماد: مصدر القيمة هو الطرف غير الموثوق.
الآن يصدره السيرفر لحظةَ يستبدل الـRuntime جلسة تركيب صالحة — وهي اللحظة
الوحيدة التي يملك فيها السيرفر إثباتًا أن صاحب الاشتراك أذن لهذا الجهاز.

**دورة الحياة:**

1. الإضافة تُصدر جلسة تركيب (رمز لمرة واحدة) وتسلّمها للـRuntime محليًا.
2. الـRuntime يستبدلها ⇒ ينشأ تفعيل الجهاز **ويصدر بيان اعتماد**.
3. القيمة الخام تعود **مرة واحدة** ⇒ يحفظها الـRuntime بـDPAPI.
4. كل طلب بعدها يحمل التجزئة المطابقة، وتُفحص ثلاثتها معًا في القاعدة:
   البيان فعّال، والجهاز مفعّل، والاشتراك ``trial``/``active`` ولم ينتهِ.
5. استبدال الجهاز أو إبطاله ⇒ **مشغّل في القاعدة** يبطل بيان اعتماده في
   المعاملة نفسها (الهجرة ٥).

⚠️ **لا شيء هنا يعيد قيمة خامًا مخزَّنة**: لا وجود لها. و``issue`` وحدها
تُنتج قيمة، وتعيدها لمستدعٍ واحد لا يسجّلها.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..core.device_credential import (
    DeviceCredentialError,
    generate_credential,
    hash_credential,
)
from ..database import supabase
from ..database.supabase import SupabaseError
from .entitlement_service import (
    DeviceActivation,
    EntitlementError,
    Subscription,
    _parse_timestamp,
)

logger = logging.getLogger(__name__)


class DeviceCredentialRejectedError(EntitlementError):
    """بيان اعتماد غير مقبول — **لا يُفرَّق بين الأسباب**.

    مجهول، أو مُدوَّر، أو لجهاز أُبطل أو استُبدل، أو لاشتراك لم يعد يسمح:
    كلها ترجع بالرسالة نفسها. التفريق يخبر من يجرّب القيم أيّها كان
    صحيحًا يومًا، وأيّ حساب ما زال قائمًا.
    """


class DeviceCredentialIssueError(EntitlementError):
    """تعذّر إصدار بيان اعتماد، برسالة عربية صالحة للعرض."""


@dataclass(frozen=True)
class IssuedCredential:
    """بيان اعتماد صادر. ``credential`` يخرج مرة واحدة ولا يُخزَّن."""

    credential: str
    activation_id: int


def issue(activation_id: int) -> IssuedCredential:
    """يصدر بيان اعتماد لجهاز مفعَّل، مُبطلًا أي بيان سابق له.

    **التدوير مقصود:** الـRuntime قد يعيد الاستبدال بعد انقطاع بين النجاح
    ووصول الرد، أو بعد أن يفقد ملفه المحمي (إعادة تثبيت ويندوز). في كلتا
    الحالتين يحتاج بيانًا جديدًا، والقديم يجب ألا يبقى مقبولًا.

    ⚠️ **القيمة المعادة سرّ يخرج مرة واحدة.** لا تُسجَّل، ولا تُعاد إلى
    الإضافة ولا إلى أي JavaScript في متصفح.

    Raises:
        DeviceCredentialIssueError: تفعيل مبطَل أو اشتراك لا يسمح.
        SupabaseError: تعذّر الوصول إلى القاعدة.
    """
    credential = generate_credential()

    try:
        rows = supabase.rpc(
            "issue_device_credential",
            {
                "p_activation_id": int(activation_id),
                "p_credential_hash": hash_credential(credential),
            },
        )
    except SupabaseError as exc:
        raise _translate_issue(exc) from exc

    if not rows:
        raise DeviceCredentialIssueError(
            "تعذّر ربط هذا الجهاز بحسابك. أعد المحاولة من إضافة GovMind."
        )

    # التنظيف عند كل إصدار — لا مهمة مجدولة ولا صفّ مبطَل يعيش سنة.
    # فشله لا يعني شيئًا لصاحب الطلب، فلا يُسقط العملية.
    try:
        supabase.rpc("purge_revoked_device_credentials", {})
    except SupabaseError:
        logger.warning("تعذّر تنظيف بيانات الاعتماد المبطَلة", exc_info=True)

    logger.info("صدر بيان اعتماد لجهاز مفعَّل (تفعيل رقم %s).", activation_id)
    return IssuedCredential(credential=credential, activation_id=int(activation_id))


def authenticate(
    raw_credential: str, *, require_serviceable: bool = True
) -> tuple[DeviceActivation, Subscription]:
    """يصادق بيان اعتماد ويعيد الجهاز واشتراكه.

    **الفحوص الثلاثة في القاعدة لا هنا** (``authenticate_device_credential``
    في الهجرة ٥): البيان فعّال، والجهاز مفعّل، والاشتراك ``trial`` أو
    ``active`` ولم ينتهِ تاريخه. جمعها في جملة SQL واحدة يمنع نافذةً بين
    قراءتين، ويمنع أن ينسى مسارٌ جديد أحدها.

    ``require_serviceable=False`` **لمسار الإخبار وحده** —
    ``/api/runtime/entitlement``. ذلك المسار يسأل «هل أستطيع العمل؟ وإن لا،
    فلماذا؟» ليعرض الـRuntime السبب بالعربية؛ ورفضُه بـ403 يترك العميل أمام
    «ممنوع» بلا سبب ولا إجراء. **الفحصان الآخران لا يُستثنيان**: بيان مبطَل
    أو جهاز مستبدَل يُرفض في الحالتين.

    ⚠️ ``raw_credential`` سرّ. **يُجزَّأ فور وصوله ولا يُسجَّل ولا يُعاد.**

    Raises:
        DeviceCredentialRejectedError: بشكل غير صالح أو لا يطابق شيئًا.
        SupabaseError: تعذّر الوصول إلى القاعدة.
    """
    try:
        credential_hash = hash_credential(raw_credential)
    except DeviceCredentialError as exc:
        raise DeviceCredentialRejectedError(str(exc)) from exc

    rows = supabase.rpc(
        "authenticate_device_credential",
        {
            "p_credential_hash": credential_hash,
            "p_require_serviceable": require_serviceable,
        },
    )
    if not rows:
        raise DeviceCredentialRejectedError(
            "هذا الجهاز غير مرتبط بأي اشتراك فعّال. أعد ربطه من إضافة "
            "GovMind في المتصفح."
        )

    row = rows[0]
    device = DeviceActivation(
        id=int(row["out_activation_id"]),
        subscription_id=int(row["out_subscription_id"]),
        # ⚠️ **لا تخرج تجزئة هوية الجهاز من الدالة**، فلا قيمة لها هنا:
        # من يعرفها يستطيع انتحال الجهاز أمام أي فحص يقارنها.
        device_id_hash="",
        device_name=str(row.get("out_device_name") or ""),
        activated_at=_parse_timestamp(row["out_activated_at"]),
        last_seen_at=_parse_timestamp(row["out_last_seen_at"]),
        revoked_at=None,
    )
    subscription = Subscription(
        id=int(row["out_subscription_id"]),
        organization_id=int(row["out_organization_id"]),
        status=str(row["out_status"]),
        seats=int(row.get("out_seats") or 0),
        starts_at=_parse_timestamp(row["out_starts_at"]),
        expires_at=_parse_timestamp(row["out_expires_at"]),
    )
    return device, subscription


def _translate_issue(exc: SupabaseError) -> EntitlementError:
    """يحوّل خطأ القاعدة إلى خطأ مجال برسالة عربية.

    الرموز من ``raise ... using errcode`` داخل دوال الهجرة ٥. **النص
    الإنجليزي الخام لا يصل المستخدم أبدًا.**
    """
    detail = str(exc)

    if "activation_revoked" in detail or "activation_not_found" in detail:
        return DeviceCredentialIssueError(
            "هذا الجهاز لم يعد مرتبطًا بحسابك. أعد ربطه من إضافة GovMind."
        )
    if "subscription_not_serviceable" in detail:
        return DeviceCredentialIssueError(
            "اشتراكك لا يسمح بربط جهاز حاليًا."
        )
    if "23505" in detail:
        return DeviceCredentialIssueError(
            "جرت محاولة ربط متزامنة لهذا الجهاز. أعد المحاولة."
        )
    return DeviceCredentialIssueError(
        "تعذّر ربط هذا الجهاز بحسابك. أعد المحاولة، وإن تكرر فتواصل مع الدعم."
    )
