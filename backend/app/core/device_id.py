"""تجزئة بصمة الجهاز.

**البصمة الخام لا تُخزَّن أبدًا ولا تُسجَّل ولا تخرج في أي رد.** يُخزَّن
HMAC-SHA256 لها بمِلح سرّي على السيرفر، ولا شيء غيره.

**لماذا HMAC بمِلح لا SHA-256 مجرّدة؟** بصمة الجهاز قليلة العشوائية بطبيعتها
— اسم جهاز ورقم لوحة ومعرّف نظام — ومجالها قابل للحصر. تجزئة بلا سرّ تعني
أن من يقرأ القاعدة يبني جدولًا مسبقًا ويستعيد هوية كل جهاز فيها. المِلح
يجعل ذلك مستحيلًا بلا سرقة متغيرات البيئة أيضًا.

**المِلح إلزامي ولا قيمة افتراضية له:** مِلح مكتوب في الكود لا يختلف عن لا
مِلح، لأنه في كل نسخة من المستودع. غيابه يوقف تفعيل الأجهزة برسالة إعداد
واضحة بدل أن يخزّن تجزئة ضعيفة بصمت.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from .config import settings

#: الشكل الذي يقبله عمود ``device_id_hash`` في مخطط Supabase.
DEVICE_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: أقصر بصمة مقبولة. بصمة من حرفين لا تميّز جهازًا عن آخر.
MIN_RAW_DEVICE_ID_LENGTH = 8


class DeviceIdError(Exception):
    """خطأ في بصمة الجهاز أو في إعداد تجزئتها، برسالة عربية للعرض."""


def hash_device_id(raw_device_id: str) -> str:
    """يحوّل بصمة الجهاز إلى تجزئة ست عشرية بطول ٦٤ خانة.

    Args:
        raw_device_id: البصمة كما ولّدها العميل. **لا تُخزَّن ولا تُسجَّل.**

    Raises:
        DeviceIdError: إذا كانت البصمة قصيرة جدًا أو المِلح غير مضبوط.
    """
    value = (raw_device_id or "").strip()
    if len(value) < MIN_RAW_DEVICE_ID_LENGTH:
        raise DeviceIdError(
            "معرّف الجهاز المرسل غير صالح. أعد فتح النافذة وحاول مرة أخرى."
        )

    pepper = (settings.device_hash_pepper or "").strip()
    if not pepper:
        raise DeviceIdError(
            "تفعيل الأجهزة غير مهيّأ على هذا السيرفر. المتغير الناقص: "
            "DEVICE_HASH_PEPPER."
        )

    return hmac.new(
        pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def is_valid_hash(value: str) -> bool:
    """هل النص تجزئة بالشكل الذي يقبله المخطط؟ للتحقق قبل الكتابة."""
    return bool(DEVICE_HASH_PATTERN.fullmatch(value or ""))
