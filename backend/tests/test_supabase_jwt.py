"""التحقق من رموز Supabase: ES256 وRS256 عبر JWKS، وHS256 القديمة.

**ما كسر الإنتاج.** مشروع Supabase جديد يوقّع رموز مستخدميه بمفتاح **غير
متماثل** (ES256) وينشر نظيره العام على
``/auth/v1/.well-known/jwks.json``. المتحقّق كان يمرّر
``algorithms=["HS256"]`` وحدها، فكان PyJWT يرفع ``InvalidAlgorithmError``
على **كل** رمز مستخدم — فينجح التسجيل والدخول (وهما لا يحتاجان تحققًا
محليًا) ثم تُردّ كل نداءات ``Bearer`` بـ٤٠١.

**ما يثبته هذا الملف.** أن المسارين يعملان، وأن التحقق يشمل التوقيع
والانتهاء والمُصدِر والجمهور والهوية، وأن **خلط الخوارزميات مرفوض**، وأن
`kid` مجهولًا يُحدِّث المخزون **مرة واحدة** لا مرة لكل طلب، وأن عطل JWKS
يعود ٥٠٣ لا ٤٠١ — لأن ٤٠١ كانت ستُخرج كل المستخدمين من حساباتهم بسبب
انقطاع عابر.

⚠️ **لا مفاتيح حقيقية هنا.** كل مفتاح في هذا الملف يُولَّد في الذاكرة عند
تشغيل الاختبار، ولا يُقرأ أي سرّ من الإعداد ولا من الشبكة.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core.config import settings
from app.services import supabase_auth, supabase_jwks
from app.services.supabase_auth import (
    InvalidSupabaseTokenError,
    SupabaseAuthNotConfiguredError,
    verify_access_token,
)

PROJECT_URL = "https://project.supabase.co"
ISSUER = f"{PROJECT_URL}/auth/v1"
USER_ID = "11111111-1111-4111-8111-111111111111"
LEGACY_SECRET = "legacy-hs256-secret-at-least-32-bytes"

EC_KID = "ec-key-2026"
RSA_KID = "rsa-key-2026"
ROTATED_KID = "ec-key-rotated"


# ===========================================================================
# مفاتيح مولّدة في الذاكرة
# ===========================================================================
def _ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(private_key, kid: str, alg: str | None) -> dict[str, Any]:
    """يحوّل المفتاح الخاص إلى JWK **عامّ** كما تنشره Supabase."""
    jwk = json.loads(jwt.algorithms.get_default_algorithms()[alg or "ES256"].to_jwk(
        private_key.public_key()
    ))
    jwk["kid"] = kid
    jwk["use"] = "sig"
    if alg:
        jwk["alg"] = alg
    else:
        jwk.pop("alg", None)
    return jwk


class Project:
    """مشروع Supabase مزيّف: مفاتيحه، وJWKS المنشورة، وعدّاد جلبها."""

    def __init__(self) -> None:
        self.ec_key = _ec_key()
        self.rsa_key = _rsa_key()
        self.rotated_key = _ec_key()
        self.published: list[dict[str, Any]] = [
            public_jwk(self.ec_key, EC_KID, "ES256"),
            public_jwk(self.rsa_key, RSA_KID, "RS256"),
        ]
        self.fetches = 0
        self.status = 200

    def handler(self, url: str, **kwargs: Any) -> httpx.Response:
        assert url.endswith("/auth/v1/.well-known/jwks.json"), url
        self.fetches += 1
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        return httpx.Response(200, json={"keys": self.published})

    def rotate(self) -> None:
        """يستبدل المفاتيح المنشورة بمفتاح جديد — كما يفعل تدوير حقيقي."""
        self.published = [public_jwk(self.rotated_key, ROTATED_KID, "ES256")]


@pytest.fixture
def project(monkeypatch):
    """مشروع مزيّف مركّب، ومخزون JWKS مفرَّغ قبل الاختبار وبعده."""
    monkeypatch.setattr(settings, "supabase_url", PROJECT_URL)
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key-for-tests")
    monkeypatch.setattr(settings, "supabase_jwt_secret", LEGACY_SECRET)
    monkeypatch.setattr(settings, "supabase_timeout_seconds", 5.0)

    fake = Project()
    monkeypatch.setattr(supabase_jwks.httpx, "get", fake.handler)
    supabase_jwks.reset_cache()
    yield fake
    supabase_jwks.reset_cache()


# ===========================================================================
# صناعة الرموز
# ===========================================================================
def claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    body = {
        "sub": USER_ID,
        "email": "adbo@example.test",
        "aud": "authenticated",
        "role": "authenticated",
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    body.update(overrides)
    return body


def sign(key, algorithm: str, kid: str | None = None, **overrides: Any) -> str:
    headers = {"kid": kid} if kid else {}
    return jwt.encode(claims(**overrides), key, algorithm=algorithm, headers=headers)


# ===========================================================================
# ١) المسار غير المتماثل — جوهر الإصلاح
# ===========================================================================
def test_es256_token_is_accepted(project):
    """**الحالة التي كانت تفشل حيًّا.**"""
    identity = verify_access_token(sign(project.ec_key, "ES256", EC_KID))

    assert identity.user_id == USER_ID
    assert identity.email == "adbo@example.test"
    assert project.fetches == 1


def test_rs256_token_is_accepted(project):
    """Supabase تتيح RS256 كذلك، فلا يُقصر الدعم على ES256."""
    identity = verify_access_token(sign(project.rsa_key, "RS256", RSA_KID))
    assert identity.user_id == USER_ID


def test_asymmetric_verification_needs_no_legacy_secret(project, monkeypatch):
    """⚠️ **شرط صريح: لا يُطلب من العميل ضبط `SUPABASE_JWT_SECRET`.**

    مشروع حديث لا يعرض سرًّا متماثلًا أصلًا. لو بقي مطلوبًا لكان الإصلاح
    يفرض على العميل تغيير إعداد التوقيع — وهو ما مُنع صراحةً.
    """
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")

    identity = verify_access_token(sign(project.ec_key, "ES256", EC_KID))
    assert identity.user_id == USER_ID


def test_jwks_is_fetched_once_and_cached(project):
    """نداء شبكي لكل طلب محمي كان سيضيف تأخيرًا ويربط الخدمة بتوفّر JWKS."""
    for _ in range(5):
        verify_access_token(sign(project.ec_key, "ES256", EC_KID))

    assert project.fetches == 1
    assert supabase_jwks.cached_kids() == sorted([EC_KID, RSA_KID])


def test_token_without_kid_is_rejected(project):
    """كل مفاتيح Supabase تحمل `kid`؛ غيابه يعني رمزًا من غيرها."""
    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token(sign(project.ec_key, "ES256"))


# ===========================================================================
# ٢) المسار المتماثل — لا ينكسر ما كان يعمل
# ===========================================================================
def test_legacy_hs256_token_is_still_accepted(project):
    """مشروع قديم لم ينتقل بعد يجب أن يبقى عاملًا."""
    identity = verify_access_token(jwt.encode(claims(), LEGACY_SECRET, algorithm="HS256"))

    assert identity.user_id == USER_ID
    assert project.fetches == 0, "مسار HS256 لا يلمس JWKS إطلاقًا"


def test_hs256_without_secret_reports_configuration_not_bad_token(
    project, monkeypatch
):
    """سرّ ناقص خللُ تركيب: ٥٠٣ لا ٤٠١، فلا يُلام المستخدم على إعداد."""
    monkeypatch.setattr(settings, "supabase_jwt_secret", "")

    with pytest.raises(SupabaseAuthNotConfiguredError):
        verify_access_token(jwt.encode(claims(), LEGACY_SECRET, algorithm="HS256"))


# ===========================================================================
# ٣) `kid` مجهول — تحديث واحد لا فيضان
# ===========================================================================
def test_unknown_kid_triggers_exactly_one_refresh(project):
    """تدوير المفاتيح يجب أن يُلتقط بلا إعادة تشغيل السيرفر."""
    verify_access_token(sign(project.ec_key, "ES256", EC_KID))
    assert project.fetches == 1

    project.rotate()  # المشروع بدّل مفاتيحه
    identity = verify_access_token(sign(project.rotated_key, "ES256", ROTATED_KID))

    assert identity.user_id == USER_ID
    assert project.fetches == 2, "تحديث واحد لا أكثر"


def test_unknown_kid_after_refresh_is_rejected(project):
    """مفتاح لا وجود له أصلًا: تحديث واحد ثم رفض، لا محاولات متكررة."""
    stranger = _ec_key()

    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token(sign(stranger, "ES256", "kid-that-never-existed"))

    assert project.fetches == 2, "جلب أوّلي + تحديث قسري واحد"


def test_repeated_unknown_kids_do_not_flood_supabase(project):
    """⚠️ **حماية من إغراق نُطلقه نحن.**

    مهاجم يرسل `kid` عشوائيًا في كل طلب كان سيجرّ السيرفر إلى نداء صعودي
    لكل طلب. المهلة تمنع ذلك، والرمز يُرفض في الحالتين.
    """
    stranger = _ec_key()

    for index in range(10):
        with pytest.raises(InvalidSupabaseTokenError):
            verify_access_token(sign(stranger, "ES256", f"random-kid-{index}"))

    assert project.fetches == 2, "لم تُحترم مهلة التحديث القسري"


# ===========================================================================
# ٤) التوقيع والمدة والمُصدِر والجمهور
# ===========================================================================
def test_invalid_signature_is_rejected(project):
    """مفتاح آخر بنفس `kid`: التوقيع لا يطابق المفتاح العام المنشور."""
    impostor = _ec_key()

    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token(sign(impostor, "ES256", EC_KID))


def test_expired_token_says_the_session_ended(project):
    past = int((datetime.now(UTC) - timedelta(hours=2)).timestamp())

    with pytest.raises(InvalidSupabaseTokenError) as caught:
        verify_access_token(
            sign(project.ec_key, "ES256", EC_KID, exp=past, iat=past - 3600)
        )

    assert "انتهت صلاحية جلستك" in str(caught.value)


def test_token_from_another_project_is_rejected(project):
    """توقيع صحيح لا يكفي: **المُصدِر يجب أن يكون هذا المشروع.**"""
    with pytest.raises(InvalidSupabaseTokenError) as caught:
        verify_access_token(
            sign(
                project.ec_key,
                "ES256",
                EC_KID,
                iss="https://another-project.supabase.co/auth/v1",
            )
        )

    assert "جهة أخرى" in str(caught.value)


def test_token_without_issuer_is_rejected(project):
    body = claims()
    del body["iss"]
    token = jwt.encode(body, project.ec_key, algorithm="ES256", headers={"kid": EC_KID})

    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token(token)


def test_service_token_audience_is_rejected(project):
    """رمز خدمة جمهوره ليس `authenticated` لا يمرّ في مسار مستخدم."""
    with pytest.raises(InvalidSupabaseTokenError) as caught:
        verify_access_token(sign(project.ec_key, "ES256", EC_KID, aud="service_role"))

    assert "ليس رمز مستخدم" in str(caught.value)


def test_token_without_subject_is_rejected(project):
    body = claims()
    del body["sub"]
    token = jwt.encode(body, project.ec_key, algorithm="ES256", headers={"kid": EC_KID})

    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token(token)


def test_missing_token_is_rejected(project):
    for empty in ("", "   ", None):
        with pytest.raises(InvalidSupabaseTokenError):
            verify_access_token(empty)  # type: ignore[arg-type]


def test_malformed_token_is_rejected(project):
    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token("not.a.jwt")


# ===========================================================================
# ٥) خلط الخوارزميات — الهجوم الكلاسيكي على هذا الترقيع بالذات
# ===========================================================================
def test_algorithm_confusion_with_the_public_key_as_hmac_secret(project):
    """**الهجوم:** يوقّع المهاجم بـHS256 مستعملًا المفتاح **العام** سرًّا.

    من يقبل الخوارزمية من الترويسة ويجلب «المفتاح» بـ`kid` يقع فيه: المفتاح
    العام منشور للجميع. هنا لا يقع: مسار JWKS لا يقبل HS256 أصلًا، ورمز
    HS256 يُفحص بسرّ المشروع وحده.
    """
    import base64
    import hmac
    import hashlib

    from cryptography.hazmat.primitives import serialization

    public_pem = project.ec_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # **يُصاغ الرمز يدويًا عمدًا.** `jwt.encode` يرفض مفتاحًا غير متماثل
    # سرًّا لـHMAC، وهي حماية في طرف **الإصدار**. المهاجم لا يستعمل مكتبتنا،
    # فالمطلوب إثبات أن طرف **التحقق** يردّه.
    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": EC_KID}).encode())
    body = b64(json.dumps(claims()).encode())
    signing_input = header + b"." + body
    signature = b64(hmac.new(public_pem, signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + signature).decode("ascii")

    # الترويسة فعلًا HS256 وتحمل `kid` مفتاح المشروع — أي الفخّ كاملًا.
    assert jwt.get_unverified_header(forged) == {
        "alg": "HS256",
        "typ": "JWT",
        "kid": EC_KID,
    }

    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token(forged)


def test_unsigned_token_is_rejected(project):
    """`alg: none` — أوضح صور التزوير."""
    unsigned = jwt.encode(claims(), key="", algorithm="none")

    with pytest.raises(InvalidSupabaseTokenError) as caught:
        verify_access_token(unsigned)

    assert "غير مدعومة" in str(caught.value)


def test_algorithm_outside_the_allowlist_is_rejected(project):
    """ES384 توقيع سليم، لكنها **خارج قائمة السماح** فتُرفض.

    القائمة صريحة عمدًا: كل خوارزمية إضافية سطحُ هجوم بلا مقابل.
    """
    key = ec.generate_private_key(ec.SECP384R1())
    token = jwt.encode(
        claims(), key, algorithm="ES384", headers={"kid": EC_KID}
    )

    with pytest.raises(InvalidSupabaseTokenError) as caught:
        verify_access_token(token)

    assert "غير مدعومة" in str(caught.value)


def test_jwk_without_alg_must_match_the_key_type(project):
    """JWK بلا `alg`: تُقبل خوارزمية الترويسة **إن وافقت نوع المفتاح**.

    فمفتاح EC لا يوقّع RS256، ولو ادّعت الترويسة ذلك.
    """
    project.published = [public_jwk(project.ec_key, EC_KID, None)]
    supabase_jwks.reset_cache()

    # ES256 على مفتاح EC: مقبول.
    assert verify_access_token(sign(project.ec_key, "ES256", EC_KID)).user_id == USER_ID

    # RS256 على مفتاح EC: مرفوض قبل أي محاولة تحقق.
    forged = jwt.encode(
        claims(), project.rsa_key, algorithm="RS256", headers={"kid": EC_KID}
    )
    with pytest.raises(InvalidSupabaseTokenError):
        verify_access_token(forged)


# ===========================================================================
# ٦) عطل JWKS ليس جلسة ساقطة
# ===========================================================================
def test_jwks_outage_is_a_service_error_not_a_dead_session(project):
    """⚠️ **الفرق يقرّر مصير كل المستخدمين.**

    لو رُدّت ٤٠١ عند تعذّر جلب المفاتيح لخرج كل من يستعمل النظام من حسابه
    بسبب انقطاع عابر عند Supabase. ٥٠٣ تقول «أعد المحاولة» وتُبقي الجلسة.
    """
    project.status = 500

    with pytest.raises(SupabaseAuthNotConfiguredError):
        verify_access_token(sign(project.ec_key, "ES256", EC_KID))


def test_network_failure_while_fetching_jwks_is_also_a_service_error(
    project, monkeypatch
):
    def refuse(url: str, **kwargs: Any):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(supabase_jwks.httpx, "get", refuse)
    supabase_jwks.reset_cache()

    with pytest.raises(SupabaseAuthNotConfiguredError):
        verify_access_token(sign(project.ec_key, "ES256", EC_KID))


def test_asymmetric_path_without_project_url_reports_configuration(
    project, monkeypatch
):
    monkeypatch.setattr(settings, "supabase_url", "")
    supabase_jwks.reset_cache()

    with pytest.raises(SupabaseAuthNotConfiguredError):
        verify_access_token(sign(project.ec_key, "ES256", EC_KID))


def test_malformed_jwks_entries_do_not_break_the_good_ones(project):
    """مفتاح شاذّ واحد لا يجوز أن يعطّل التحقق كله."""
    project.published = [
        {"kty": "EC", "kid": "broken"},          # ناقص
        {"not": "a key"},                        # لا `kid`
        public_jwk(project.ec_key, EC_KID, "ES256"),
    ]

    assert verify_access_token(sign(project.ec_key, "ES256", EC_KID)).user_id == USER_ID


# ===========================================================================
# ٧) لا تسريب في السجلات ولا في الرسائل
# ===========================================================================
def test_no_token_or_secret_appears_in_logs_or_errors(project, caplog, monkeypatch):
    """⚠️ **شرط قاطع:** لا رمز ولا سرّ ولا مادة مفاتيح في أي سجل أو رسالة."""
    monkeypatch.setattr(settings, "supabase_jwt_secret", LEGACY_SECRET)
    caplog.set_level(logging.DEBUG)

    valid = sign(project.ec_key, "ES256", EC_KID)
    verify_access_token(valid)

    forged = sign(_ec_key(), "ES256", EC_KID)
    unsigned = jwt.encode(claims(), key="", algorithm="none")
    legacy = jwt.encode(claims(), LEGACY_SECRET, algorithm="HS256")
    verify_access_token(legacy)

    messages: list[str] = []
    for token in (forged, unsigned, "not.a.jwt"):
        try:
            verify_access_token(token)
        except supabase_auth.SupabaseAuthError as exc:
            messages.append(str(exc))

    logged = caplog.text
    haystack = logged + " ".join(messages)

    for secret in (valid, forged, unsigned, legacy, LEGACY_SECRET):
        assert secret not in haystack, "تسرّب رمز أو سرّ"
        # ولا حتى جزء التوقيع وحده. (`alg: none` توقيعه فارغ، فيُتخطّى.)
        signature = secret.rsplit(".", 1)[-1]
        if signature:
            assert signature not in haystack

    # ولا مادة المفاتيح العامة (المُعامِلات) في السجل.
    for jwk in project.published:
        for field in ("x", "y", "n", "d"):
            value = jwk.get(field)
            if value:
                assert value not in haystack


def test_error_messages_never_name_internal_details(project):
    with pytest.raises(InvalidSupabaseTokenError) as caught:
        verify_access_token(sign(_ec_key(), "ES256", EC_KID))

    detail = str(caught.value)
    for word in ("JWKS", "kid", "signature", "PyJWT", "Traceback", "ES256"):
        assert word not in detail


# ===========================================================================
# ٨) المسار الحيّ كاملًا: جلسة بعد التسجيل ⇒ تفعيل أول جهاز
# ===========================================================================
# هذا ما فشل عند العميل حرفيًا:
#   POST /api/account/register        201
#   POST /api/account/login           200
#   GET  /api/account/subscription    401  ← هنا كان ينكسر
#   POST /api/account/devices/activate 401
# الاختبار يعيد التسلسل نفسه برمز ES256 حقيقي عبر المسارات الحقيقية.
from tests.test_entitlements import (  # noqa: E402
    DEVICE_A,
    EMPLOYEE_A,
    client,
    fake_supabase,  # noqa: F401 — تركيب قاعدة PostgREST المزيّفة
)


def es256_auth(project: Project, user_id: str = EMPLOYEE_A) -> dict[str, str]:
    """ترويسة Authorization برمز ES256 كالذي تصدره Supabase الحديثة."""
    token = sign(
        project.ec_key,
        "ES256",
        EC_KID,
        sub=user_id,
        email=f"{user_id[:8]}@govmind.test",
    )
    return {"Authorization": f"Bearer {token}"}


def test_es256_session_reaches_subscription_and_first_activation(
    project, fake_supabase
):
    """**اختبار الانحدار للعطل الحيّ.**"""
    headers = es256_auth(project)

    status_response = client.get("/api/account/subscription", headers=headers)
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["requires_activation"] is True

    activate = client.post(
        "/api/account/devices/activate",
        json={"device_id": DEVICE_A, "device_name": "حاسب المكتب"},
        headers=headers,
    )
    assert activate.status_code == 200, activate.text
    assert activate.json()["device"]["is_current_device"] is True

    active = [
        row
        for row in fake_supabase.tables["device_activations"]
        if row.get("revoked_at") is None
    ]
    assert len(active) == 1


def test_es256_session_reads_the_account_profile(project, fake_supabase):
    response = client.get("/api/account/me", headers=es256_auth(project))

    assert response.status_code == 200
    assert response.json()["email"] == "employee-a@govmind.test"


def test_a_jwks_outage_returns_503_not_401_on_a_protected_route(
    project, fake_supabase
):
    """⚠️ الفرق الذي يمنع تسجيل خروج جماعي عند عطل عابر."""
    headers = es256_auth(project)
    project.status = 500
    supabase_jwks.reset_cache()

    response = client.get("/api/account/subscription", headers=headers)

    assert response.status_code == 503
    assert "أعد المحاولة" in response.json()["detail"]


def test_forged_token_is_still_401_on_a_protected_route(project, fake_supabase):
    forged = sign(_ec_key(), "ES256", EC_KID, sub=EMPLOYEE_A)

    response = client.get(
        "/api/account/subscription",
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert response.status_code == 401
