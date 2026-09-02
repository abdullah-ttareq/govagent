"""بيان اعتماد الجهاز — توليده وتجزئته.

**من يولّده؟ السيرفر، لا العميل.** كان الـRuntime يولّد «سرّ جهاز» بنفسه
ويرسله في كل طلب، فالسيرفر يقبل أوّل قيمة تصل ما دامت تطابق تجزئة مخزّنة.
هذا معرّف جهاز لا بيان اعتماد: من يملك الجهاز يملك توليده. الآن يولّده
السيرفر لحظةَ يستبدل الـRuntime **جلسة تركيب صالحة** — فمصدر الثقة واحد،
وهو الطرف الذي يملك الاشتراك.

**ما يخرج وما يبقى.** القيمة الخام تعود **مرة واحدة** في رد الاستبدال ولا
تُسترجع بعدها: القاعدة لا تحمل إلا SHA-256 لها. لا مسار في هذا المشروع
يعيد قراءتها، ولا سطر يسجّلها.

⚠️ **لا تصل هذه القيمة إلى JavaScript في المتصفح ولا إلى الإضافة.** الـRuntime
وحده يستقبلها ويحفظها بـDPAPI، ويلصقها بطلباته من جانب الخادم.

**لماذا SHA-256 بلا مِلح، بخلاف ``device_id.hash_device_id``؟**
المِلح يلزم حين يكون المُجزَّأ قليل العشوائية فيُبنى له جدول مسبق — بصمة
جهاز أو كلمة مرور. هذه القيمة ٢٥٦ بت من مولّد النظام العشوائي ولا تُخمَّن،
فالمِلح يضيف سرًّا يجب حفظه بلا أن يزيد أمانًا. وهو المنطق نفسه المطبَّق
على رمز جلسة التركيب في ``installation_session_service``.
"""

from __future__ import annotations

import hashlib
import re
import secrets

#: الشكل الذي يقبله عمود ``credential_hash`` في مخطط Supabase.
CREDENTIAL_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: عدد بايتات العشوائية. ٣٢ بايت = ٢٥٦ بت.
CREDENTIAL_BYTES = 32

#: أقصر قيمة مقبولة من العميل. أقصر من ذلك لا يمكن أن تكون صادرة عنّا.
MIN_RAW_CREDENTIAL_LENGTH = 32

#: أطول قيمة مقبولة — تمنع جسمًا ضخمًا في ترويسة.
MAX_RAW_CREDENTIAL_LENGTH = 512


class DeviceCredentialError(Exception):
    """بيان اعتماد بشكل غير صالح، برسالة عربية صالحة للعرض."""


def generate_credential() -> str:
    """يولّد بيان اعتماد جديدًا.

    ``secrets`` لا ``random``: الأول مولّد النظام العشوائي، والثاني يمكن
    التنبؤ بمخرجاته من عدد قليل من العيّنات.

    ⚠️ **القيمة المعادة سرّ.** لا تُسجَّل ولا تُخزَّن خامًا ولا تُعاد إلا
    مرة واحدة إلى الـRuntime الذي استبدل جلسة التركيب.
    """
    return secrets.token_urlsafe(CREDENTIAL_BYTES)


def hash_credential(raw_credential: str) -> str:
    """SHA-256 للقيمة، ست عشرية بأحرف صغيرة كما يشترط قيد العمود.

    Args:
        raw_credential: القيمة كما وصلت من الـRuntime. **لا تُسجَّل.**

    Raises:
        DeviceCredentialError: إذا كان الشكل لا يمكن أن يكون صادرًا عنّا.
    """
    value = (raw_credential or "").strip()
    if not (MIN_RAW_CREDENTIAL_LENGTH <= len(value) <= MAX_RAW_CREDENTIAL_LENGTH):
        # ⚠️ الرسالة لا تحمل شيئًا من القيمة ولا طولها.
        raise DeviceCredentialError(
            "بيان اعتماد الجهاز غير صالح. أعد ربط الجهاز من إضافة GovMind."
        )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_valid_hash(value: str) -> bool:
    """هل النص تجزئة بالشكل الذي يقبله المخطط؟ للتحقق قبل الكتابة."""
    return bool(CREDENTIAL_HASH_PATTERN.fullmatch(value or ""))
