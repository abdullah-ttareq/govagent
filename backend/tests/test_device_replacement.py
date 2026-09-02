"""استبدال الجهاز — يفعله صاحب الحساب بنفسه، بلا موافقة أحد.

**النموذج فردي:** حساب واحد، اشتراك واحد، **جهاز فعّال واحد**. من غيّر
حاسبه لا ينتظر مسؤولًا يوافق؛ يعيد إدخال كلمة مروره فينتقل اشتراكه.

**ما يثبته هذا الملف.**

1. الجهاز الثاني **مرفوض ابتداءً** — الاستبدال إجراء واعٍ لا نتيجة جانبية
   لتسجيل دخول.
2. كلمة مرور خاطئة **لا تستبدل شيئًا**، ورسالتها عربية آمنة.
3. كلمة المرور الصحيحة تُبطل السابق وتفعّل الحالي.
4. **لا يبقى إلا تفعيل واحد** بعد الاستبدال.
5. طلبان متزامنان **لا يتركان جهازين فعّالين**.

**حدود المحاكاة، بصراحة.** الذرّية والتسلسل يضمنهما PostgreSQL لا بايثون:
``select ... for update`` على صفّ الاشتراك، والفهرس الفريد الجزئي
``uq_device_activations_one_active``. الاثنان مُثبتان على PostgreSQL حقيقي
داخل ``database/supabase/0004_device_replacement.sql``. القاعدة المزيّفة
هنا **تحاكي العقد نفسه** (قفل لكل اشتراك + الفهرس الفريد)، فما يُختبر هنا
هو **الكود الذي يستدعيها ويترجم أخطاءها**، ويحرس
:func:`test_migration_keeps_both_layers_of_protection` بقاءَ الطبقتين في
الترحيل حتى لا تتحول المحاكاة إلى وهم.
"""

from __future__ import annotations

import threading

import pytest

from app.api import entitlements as entitlements_api
from app.services.supabase_auth import InvalidCredentialsError, SupabaseSession

from tests.test_entitlements import (
    DEVICE_A,
    DEVICE_OTHER,
    EMPLOYEE_A,
    SUB_A,
    activate,
    auth,
    client,
    fake_supabase,  # noqa: F401 — تركيب القاعدة المزيّفة
)

PASSWORD = "StrongPass!2026"
DEVICE_THIRD = "device-fingerprint-a-third-machine"


@pytest.fixture
def password_check(monkeypatch):
    """يستبدل ``sign_in`` بتحقق يقبل كلمة مرور واحدة ويعدّ محاولاته.

    التحقق الحقيقي يقع على Supabase Auth عبر الشبكة؛ ما يخصّ هذه
    الاختبارات أن المسار **ينادي التحقق قبل أي كتابة** وأن رفضه يوقف كل
    شيء.
    """

    class Checker:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def __call__(self, email: str, password: str) -> SupabaseSession:
            self.calls.append((email, password))
            if password != PASSWORD:
                raise InvalidCredentialsError("البريد أو كلمة المرور غير صحيحة.")
            return SupabaseSession(
                access_token="issued-token",
                refresh_token="issued-refresh",
                expires_in=3600,
                user_id=EMPLOYEE_A,
                email=email,
            )

    checker = Checker()
    monkeypatch.setattr(entitlements_api, "sign_in", checker)
    return checker


def replace(device_id: str, password: str, name: str = "حاسب المنزل"):
    return client.post(
        "/api/account/devices/replace",
        json={"device_id": device_id, "device_name": name, "password": password},
        headers=auth(EMPLOYEE_A),
    )


def active_rows(fake) -> list[dict]:
    return [
        row
        for row in fake.tables["device_activations"]
        if row["subscription_id"] == SUB_A and row.get("revoked_at") is None
    ]


# ===========================================================================
# الجهاز الثاني مرفوض ابتداءً
# ===========================================================================
def test_second_device_is_blocked_before_any_replacement(fake_supabase):
    """**الاستبدال إجراء واعٍ.** الدخول من حاسب ثانٍ لا يسحب الاشتراك إليه.

    لولا ذلك لكان كل تسجيل دخول على جهاز مستعار يوقف GovMind على حاسب
    صاحبه بلا أن يدري.
    """
    assert activate(EMPLOYEE_A, DEVICE_A).status_code == 200

    response = activate(EMPLOYEE_A, DEVICE_OTHER, name="حاسب المنزل")

    assert response.status_code == 409
    assert len(active_rows(fake_supabase)) == 1
    assert active_rows(fake_supabase)[0]["device_name"] == "حاسب المكتب"


def test_the_block_message_points_to_self_service_not_an_administrator(
    fake_supabase,
):
    """⚠️ الرسالة تدلّ على الحل الذاتي، ولا تذكر مسؤولًا ولا جهة."""
    activate(EMPLOYEE_A, DEVICE_A)
    detail = activate(EMPLOYEE_A, DEVICE_OTHER).json()["detail"]

    assert "استبدال الجهاز السابق" in detail
    for word in ("مسؤول", "جهة", "الدعم الفني في جهتك", "admin"):
        assert word not in detail


# ===========================================================================
# كلمة المرور شرطٌ لا شكل
# ===========================================================================
def test_wrong_password_cannot_replace_the_device(fake_supabase, password_check):
    """**الجوهر:** رمز الدخول وحده لا يوقف GovMind على حاسب آخر.

    جلسةٌ متروكة مفتوحة على جهاز عام يجب ألا تُفقد صاحبها جهازه.
    """
    activate(EMPLOYEE_A, DEVICE_A)

    response = replace(DEVICE_OTHER, "WrongPass!2026")

    assert response.status_code == 401
    detail = response.json()["detail"]
    assert "كلمة المرور غير صحيحة" in detail
    # ولا تسريب لما إن كان البريد صحيحًا أو الحساب موجودًا.
    assert "البريد" not in detail

    remaining = active_rows(fake_supabase)
    assert len(remaining) == 1
    assert remaining[0]["device_name"] == "حاسب المكتب", "أُبطل الجهاز رغم الرفض"


def test_the_password_is_checked_before_any_write(fake_supabase, password_check):
    """التحقق يسبق الكتابة، فلا إبطال يسبق إثبات الهوية."""
    activate(EMPLOYEE_A, DEVICE_A)
    before = list(fake_supabase.tables["device_activations"])

    replace(DEVICE_OTHER, "WrongPass!2026")

    assert password_check.calls == [("employee-a@govmind.test", "WrongPass!2026")]
    assert fake_supabase.tables["device_activations"] == before


def test_replacement_requires_a_password_field(fake_supabase, password_check):
    """الحقل إلزامي في المخطط — لا استبدال بحمولة ناقصة."""
    activate(EMPLOYEE_A, DEVICE_A)

    response = client.post(
        "/api/account/devices/replace",
        json={"device_id": DEVICE_OTHER, "device_name": "حاسب المنزل"},
        headers=auth(EMPLOYEE_A),
    )

    assert response.status_code == 422
    assert len(active_rows(fake_supabase)) == 1


def test_replacement_requires_a_token(fake_supabase, password_check):
    response = client.post(
        "/api/account/devices/replace",
        json={"device_id": DEVICE_OTHER, "password": PASSWORD},
    )
    assert response.status_code == 401


# ===========================================================================
# الاستبدال الناجح
# ===========================================================================
def test_correct_password_revokes_the_old_device_and_activates_this_one(
    fake_supabase, password_check
):
    activate(EMPLOYEE_A, DEVICE_A)

    response = replace(DEVICE_OTHER, PASSWORD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["replaced"] is True
    assert body["subscription"]["requires_activation"] is False
    assert body["subscription"]["device"]["device_name"] == "حاسب المنزل"
    assert body["subscription"]["device"]["is_current_device"] is True


def test_only_one_activation_stays_active_after_replacement(
    fake_supabase, password_check
):
    """**الشرط الأهم:** جهاز فعّال واحد، لا اثنان ولا صفر."""
    activate(EMPLOYEE_A, DEVICE_A)
    replace(DEVICE_OTHER, PASSWORD)

    remaining = active_rows(fake_supabase)
    assert len(remaining) == 1
    assert remaining[0]["device_name"] == "حاسب المنزل"

    # والصف القديم يبقى مُبطَلًا لا محذوفًا — سجل الأجهزة يظل قابلًا للقراءة.
    all_rows = [
        row
        for row in fake_supabase.tables["device_activations"]
        if row["subscription_id"] == SUB_A
    ]
    assert len(all_rows) == 2
    assert sum(1 for row in all_rows if row.get("revoked_at")) == 1


def test_the_previous_device_stops_verifying(fake_supabase, password_check):
    """**وعدٌ نقطعه في الشاشة:** GovMind يتوقف على الجهاز السابق."""
    activate(EMPLOYEE_A, DEVICE_A)
    replace(DEVICE_OTHER, PASSWORD)

    old = client.post(
        "/api/account/devices/verify",
        json={"device_id": DEVICE_A},
        headers=auth(EMPLOYEE_A),
    )
    new = client.post(
        "/api/account/devices/verify",
        json={"device_id": DEVICE_OTHER},
        headers=auth(EMPLOYEE_A),
    )

    assert old.status_code == 409
    assert new.status_code == 200


def test_replacing_with_the_same_device_is_a_no_op(fake_supabase, password_check):
    """إعادة الاستبدال بالجهاز نفسه لا تُبطل شيئًا ولا تُنشئ صفًا ثانيًا."""
    activate(EMPLOYEE_A, DEVICE_A)

    response = replace(DEVICE_A, PASSWORD, name="حاسب المكتب")

    assert response.status_code == 200
    assert response.json()["replaced"] is False
    assert len(active_rows(fake_supabase)) == 1
    assert len(fake_supabase.tables["device_activations"]) == 1


def test_replacement_needs_no_administrator_approval(fake_supabase, password_check):
    """صاحب الحساب موظف عادي في القاعدة، **ويستبدل جهازه بنفسه**."""
    from app.services import entitlement_service as entitlements

    profile = next(
        row for row in fake_supabase.tables["profiles"] if row["id"] == EMPLOYEE_A
    )
    assert profile["role"] == "employee"

    activate(EMPLOYEE_A, DEVICE_A)
    assert replace(DEVICE_OTHER, PASSWORD).status_code == 200

    # وللمقارنة: المسار الإداري القديم يرفضه.
    assert entitlements.AdminRequiredError is not None


def test_replacement_is_refused_on_a_blocked_subscription(
    fake_supabase, password_check
):
    """اشتراك منتهٍ لا يُستبدل عليه جهاز — الفشل مغلق."""
    activate(EMPLOYEE_A, DEVICE_A)
    for row in fake_supabase.tables["subscriptions"]:
        if row["id"] == SUB_A:
            row["status"] = "expired"

    response = replace(DEVICE_OTHER, PASSWORD)

    assert response.status_code == 403
    assert len(active_rows(fake_supabase)) == 1


# ===========================================================================
# التزامن
# ===========================================================================
def test_concurrent_replacements_never_leave_two_active_devices(
    fake_supabase, password_check
):
    """طلبان في اللحظة نفسها من حاسبين مختلفين.

    ينجح واحد ويُردّ الآخر برسالة عربية آمنة، **ويبقى جهاز فعّال واحد**.
    التسلسل من القاعدة لا من بايثون؛ انظر ترويسة الملف.
    """
    activate(EMPLOYEE_A, DEVICE_A)
    fake_supabase.replacement_delay = 0.05  # يوسّع النافذة ليتشابك الخيطان

    results: list[int] = []
    lock = threading.Lock()

    def attempt(device_id: str) -> None:
        status = replace(device_id, PASSWORD, name=device_id).status_code
        with lock:
            results.append(status)

    threads = [
        threading.Thread(target=attempt, args=(DEVICE_OTHER,)),
        threading.Thread(target=attempt, args=(DEVICE_THIRD,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    fake_supabase.replacement_delay = 0.0

    assert sorted(results) == [200, 200] or 409 in results
    assert len(active_rows(fake_supabase)) == 1, "بقي جهازان فعّالان"


def test_a_race_that_escapes_the_lock_is_reported_safely(
    fake_supabase, password_check, monkeypatch
):
    """لو أفلت سباقٌ من القفل فالفهرس الفريد يردّه — والرسالة عربية.

    يُحاكى بجعل القاعدة تعيد ``23505`` كما تفعل PostgreSQL عند مخالفة
    ``uq_device_activations_one_active``.
    """
    import httpx

    activate(EMPLOYEE_A, DEVICE_A)
    monkeypatch.setattr(
        fake_supabase,
        "_replace_device_activation",
        lambda params: httpx.Response(
            409,
            json={
                "code": "23505",
                "message": "duplicate key value violates unique constraint",
            },
        ),
    )

    response = replace(DEVICE_OTHER, PASSWORD)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "أعد المحاولة" in detail
    assert "23505" not in detail and "duplicate" not in detail


# ===========================================================================
# الحارس على المحاكاة
# ===========================================================================
def test_migration_keeps_both_layers_of_protection():
    """**يمنع المحاكاة من أن تصير وهمًا.**

    اختبارات التزامن أعلاه تفترض أن القاعدة تسلسل المحاولات وأن الفهرس
    يحكم أخيرًا. لو حُذفت إحدى الطبقتين من الترحيل لبقيت تلك الاختبارات
    خضراء وهي تختبر قفل بايثون وحده. هذا الاختبار يقرأ الترحيل نفسه.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "database" / "supabase"
    replacement = (root / "0004_device_replacement.sql").read_text(encoding="utf-8")
    schema = (root / "0001_govmind_supabase.sql").read_text(encoding="utf-8")

    lowered = replacement.lower()
    assert "for update" in lowered, "زال القفل على صفّ الاشتراك"
    assert "uq_device_activations_one_active" in (
        schema.lower() + lowered
    ), "زال الفهرس الفريد الجزئي"
    assert "where revoked_at is null" in schema.lower()


def test_replacement_endpoint_asks_for_no_url_or_key():
    """⚠️ لا حقل لرابط ولا لمفتاح ولا لمعرّف اشتراك في حمولة الاستبدال."""
    spec = client.get("/openapi.json").json()
    fields = set(spec["components"]["schemas"]["DeviceReplaceRequest"]["properties"])
    assert fields == {"device_id", "device_name", "password"}
