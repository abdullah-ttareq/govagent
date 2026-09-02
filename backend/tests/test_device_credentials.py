"""بيان اعتماد الجهاز: إصداره، وتخزينه، والمصادقة به.

**ما تغيّر ولماذا.** كان الـRuntime يصادق بسرّ **ولّده هو** على جهاز
العميل. ذلك يصفه معرّفَ جهاز لا بيانَ اعتماد: مصدر القيمة هو الطرف غير
الموثوق، وأي برنامج على الحاسب يستطيع توليد مثله. الآن يصدره **السيرفر**
لحظةَ يستبدل الـRuntime جلسة تركيب صالحة — وهي اللحظة الوحيدة التي يملك
فيها السيرفر إثباتًا أن صاحب الاشتراك أذن لهذا الجهاز.

**ما يثبته هذا الملف:**

* الاستبدال يصدر بيانًا **واحدًا**، ويعيده **مرة واحدة**.
* القاعدة لا تحمل إلا تجزئته — ولا سبيل إلى استرجاع الخام.
* الفحوص الثلاثة تُجرى في كل طلب: البيان، والجهاز، والاشتراك.
* لا سرّ سيرفر ولا تجزئة يخرجان في رد أو رسالة خطأ.

**ما لا يثبته:** ذرّية الإصدار وتتالي الإبطال — تلك في القاعدة نفسها،
ويثبتها قسم الاختبارات داخل `database/supabase/0005_device_credentials.sql`.
القاعدة المزيّفة هنا **تحاكي عقد الدوال**؛ مزيّفٌ ينجح دائمًا يختبر نفسه.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.device_credential import (
    DeviceCredentialError,
    generate_credential,
    hash_credential,
    is_valid_hash,
)
from app.services.device_credential_service import (
    DeviceCredentialIssueError,
    DeviceCredentialRejectedError,
)
from app.services import device_credential_service as credentials

from tests.test_installation_sessions import (  # noqa: F401 - تركيبات مشتركة
    ISSUED_CREDENTIALS,
    OTHER_SECRET,
    RUNTIME_SECRET,
    client,
    device_headers,
    fake,
    issue_token,
    runtime_activate,
)


# ===========================================================================
# التوليد والتجزئة
# ===========================================================================
def test_generated_credentials_are_unguessable():
    """بيانٌ يُخمَّن لا يحمي شيئًا. ٣٢ بايت عشوائية ⇒ ٤٣ حرفًا على الأقل."""
    values = {generate_credential() for _ in range(200)}
    assert len(values) == 200, "تكرّرت قيمة — المولّد ليس عشوائيًا"
    for value in values:
        assert len(value) >= 43


def test_hash_matches_the_column_constraint():
    digest = hash_credential(generate_credential())
    assert is_valid_hash(digest)
    assert digest == digest.lower()


def test_hash_is_sha256_of_the_trimmed_value():
    value = generate_credential()
    assert hash_credential(f"  {value}  ") == hashlib.sha256(
        value.encode()
    ).hexdigest()


@pytest.mark.parametrize("value", ["", "   ", "short", "x" * 8, "y" * 513])
def test_malformed_values_are_refused_before_any_query(value):
    """قيمة لا يمكن أن تكون صادرة عنّا تُرفض قبل أن تمسّ القاعدة."""
    with pytest.raises(DeviceCredentialError):
        hash_credential(value)


def test_the_error_message_carries_nothing_of_the_value():
    with pytest.raises(DeviceCredentialError) as caught:
        hash_credential("secret-but-too-short")
    assert "secret-but-too-short" not in str(caught.value)


# ===========================================================================
# الإصدار عند الاستبدال
# ===========================================================================
def test_redemption_issues_exactly_one_credential(fake):
    response = runtime_activate(issue_token())

    assert response.status_code == 200
    assert len(fake.tables["device_credentials"]) == 1
    assert fake.tables["device_credentials"][0]["revoked_at"] is None


def test_the_raw_credential_is_returned_once_and_stored_hashed_only(fake):
    """⚠️ **القيمة الخام لا تدخل القاعدة إطلاقًا.**"""
    raw = runtime_activate(issue_token()).json()["device_credential"]

    stored = fake.tables["device_credentials"][0]
    assert stored["credential_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in json.dumps(fake.tables, ensure_ascii=False)


def test_there_is_no_route_that_reads_a_credential_back(fake):
    """لا مسار في المنتج يعيد قيمة خامًا مخزَّنة — لا وجود لها أصلًا."""
    runtime_activate(issue_token())
    raw = ISSUED_CREDENTIALS[-1]

    for response in (
        client.get("/api/runtime/entitlement", headers=device_headers()),
        client.get("/api/account/subscription"),
    ):
        assert raw not in response.text


def test_the_credential_is_bound_to_the_activation_it_was_issued_for(fake):
    runtime_activate(issue_token())

    activation = fake.tables["device_activations"][0]
    credential = fake.tables["device_credentials"][0]
    assert credential["activation_id"] == activation["id"]


def test_re_redeeming_rotates_the_credential_and_kills_the_old_one(fake):
    """انقطاع بين النجاح ووصول الرد: يعيد الـRuntime المحاولة.

    الجهاز نفسه ⇒ التفعيل نفسه، **وبيان اعتماد جديد يُبطل السابق**. بقاء
    القديم مقبولًا يعني بيانين حيّين لجهاز واحد.
    """
    first = runtime_activate(issue_token()).json()["device_credential"]
    second = runtime_activate(issue_token(), RUNTIME_SECRET).json()[
        "device_credential"
    ]

    assert first != second
    active = [
        row for row in fake.tables["device_credentials"] if row["revoked_at"] is None
    ]
    assert len(active) == 1

    assert (
        client.get(
            "/api/runtime/entitlement", headers=device_headers(first)
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/runtime/entitlement", headers=device_headers(second)
        ).status_code
        == 200
    )


def test_a_failed_redemption_issues_nothing(fake):
    assert runtime_activate("never-issued-token-value-0001").status_code == 401
    assert fake.tables["device_credentials"] == []


def test_issuing_on_a_revoked_activation_is_refused(fake):
    runtime_activate(issue_token())
    fake.tables["device_activations"][0]["revoked_at"] = datetime.now(UTC).isoformat()

    with pytest.raises(DeviceCredentialIssueError):
        credentials.issue(fake.tables["device_activations"][0]["id"])


# ===========================================================================
# المصادقة — الفحوص الثلاثة
# ===========================================================================
def test_an_active_device_on_a_valid_subscription_succeeds(fake):
    runtime_activate(issue_token())
    response = client.get("/api/runtime/entitlement", headers=device_headers())

    assert response.status_code == 200
    assert response.json()["is_usable"] is True


def test_a_missing_credential_is_refused(fake):
    assert client.get("/api/runtime/entitlement").status_code == 401
    assert (
        client.get("/api/runtime/entitlement", headers={
            "X-GovMind-Device-Credential": "   "
        }).status_code
        == 401
    )


@pytest.mark.parametrize(
    "value",
    [
        "never-issued-credential-value-000000001",
        "x" * 64,
        RUNTIME_SECRET,
        OTHER_SECRET,
    ],
)
def test_an_invalid_credential_is_refused(fake, value):
    runtime_activate(issue_token())
    response = client.get("/api/runtime/entitlement", headers=device_headers(value))
    assert response.status_code == 401


def test_a_revoked_device_is_rejected(fake):
    runtime_activate(issue_token())
    fake.tables["device_activations"][0]["revoked_at"] = datetime.now(UTC).isoformat()

    assert (
        client.get("/api/runtime/entitlement", headers=device_headers()).status_code
        == 401
    )


def test_a_replaced_device_is_rejected(fake):
    """الجهاز الأول يفقد قبوله لحظةَ يحلّ غيرُه محلّه."""
    first = runtime_activate(issue_token()).json()["device_credential"]

    # استبدال: يُبطل الأول ثم يُفعَّل الثاني — كما تفعل دالة القاعدة.
    fake.tables["device_activations"][0]["revoked_at"] = datetime.now(UTC).isoformat()
    for row in fake.tables["device_credentials"]:
        if row["activation_id"] == fake.tables["device_activations"][0]["id"]:
            row["revoked_at"] = datetime.now(UTC).isoformat()
    second = runtime_activate(issue_token(), OTHER_SECRET).json()["device_credential"]

    assert (
        client.get(
            "/api/runtime/entitlement", headers=device_headers(first)
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/runtime/entitlement", headers=device_headers(second)
        ).status_code
        == 200
    )


@pytest.mark.parametrize("status", ["expired", "suspended", "cancelled"])
def test_a_blocked_subscription_is_rejected_on_service_routes(fake, status):
    """⚠️ **٤٠٣ لا ٤٠١**: البيان مقبول، والاشتراك هو المانع."""
    runtime_activate(issue_token())
    fake.tables["subscriptions"][0]["status"] = status

    response = client.get("/api/runtime/model", headers=device_headers())
    assert response.status_code == 403
    assert response.json()["detail"]


def test_a_subscription_past_its_date_is_rejected_even_if_active(fake):
    """الحالة والتاريخ يُفحصان معًا: لا مشغّل يحوّل `active` إلى `expired`."""
    runtime_activate(issue_token())
    fake.tables["subscriptions"][0]["expires_at"] = (
        datetime.now(UTC) - timedelta(days=1)
    ).isoformat()

    assert (
        client.get("/api/runtime/model", headers=device_headers()).status_code == 403
    )


def test_the_status_route_reports_a_blocked_subscription_instead_of_refusing(fake):
    """مسار الإخبار يقول **لماذا** توقّف، ليعرضه الـRuntime بالعربية."""
    runtime_activate(issue_token())
    fake.tables["subscriptions"][0]["status"] = "expired"

    body = client.get("/api/runtime/entitlement", headers=device_headers()).json()
    assert body["is_usable"] is False
    assert "انتهى اشتراكك" in body["blocked_reason"]


def test_the_status_route_still_refuses_a_revoked_device(fake):
    """⚠️ استثناء الاشتراك **لا يستثني الجهاز**: جهاز أُبطل لا يعرف شيئًا."""
    runtime_activate(issue_token())
    fake.tables["subscriptions"][0]["status"] = "expired"
    fake.tables["device_activations"][0]["revoked_at"] = datetime.now(UTC).isoformat()

    assert (
        client.get("/api/runtime/entitlement", headers=device_headers()).status_code
        == 401
    )


def test_failures_do_not_distinguish_their_causes(fake):
    """مجهول، ومُدوَّر، ولجهاز مبطَل: رسالة واحدة.

    التفريق يخبر من يجرّب القيم أيّها كان صحيحًا يومًا، وأيّ حساب قائم.
    """
    rotated = runtime_activate(issue_token()).json()["device_credential"]
    runtime_activate(issue_token(), RUNTIME_SECRET)
    fake.tables["device_activations"][0]["revoked_at"] = datetime.now(UTC).isoformat()

    messages = {
        client.get(
            "/api/runtime/entitlement", headers=device_headers(value)
        ).json()["detail"]
        for value in (rotated, "never-issued-credential-value-0002", ISSUED_CREDENTIALS[-1])
    }
    assert len(messages) == 1


# ===========================================================================
# التسريب
# ===========================================================================
def test_no_response_carries_a_hash_or_a_server_secret(fake, monkeypatch):
    from app.core.config import settings

    runtime_activate(issue_token())
    credential_hash = fake.tables["device_credentials"][0]["credential_hash"]
    device_hash = fake.tables["device_activations"][0]["device_id_hash"]

    responses = [
        client.get("/api/runtime/entitlement", headers=device_headers()),
        runtime_activate(issue_token(), RUNTIME_SECRET),
        client.get("/api/runtime/entitlement", headers=device_headers("bad-value-x" * 4)),
    ]
    for response in responses:
        assert credential_hash not in response.text
        assert device_hash not in response.text
        assert settings.supabase_service_role_key not in response.text
        assert settings.supabase_jwt_secret not in response.text
        assert settings.device_hash_pepper not in response.text


def test_nothing_is_logged_that_could_replay_a_credential(fake, caplog):
    """⚠️ **السجلّ ليس استثناءً.** قيمةٌ في سطر سجلّ قيمةٌ مسرّبة."""
    import logging

    caplog.set_level(logging.DEBUG)
    raw = runtime_activate(issue_token()).json()["device_credential"]
    client.get("/api/runtime/entitlement", headers=device_headers())

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert raw not in logged
    assert hash_credential(raw) not in logged


def test_the_credential_module_never_reads_a_stored_raw_value():
    """لا دالة في الوحدة تعيد قيمة خامًا من القاعدة — لا وجود لها فيها."""
    import inspect

    from app.services import device_credential_service

    source = inspect.getsource(device_credential_service)
    # الطريق الوحيد إلى قيمة خام هو توليدها الآن.
    assert source.count("generate_credential()") == 1
    assert "credential_hash" in source


def test_the_rejected_error_message_names_the_extension_not_an_administrator(fake):
    """⚠️ **لا مسؤول نظام في هذا المنتج**؛ العميل يعيد الربط بنفسه."""
    with pytest.raises(DeviceCredentialRejectedError) as caught:
        credentials.authenticate("never-issued-credential-value-00000009")

    message = str(caught.value)
    assert "GovMind" in message
    for word in ("مسؤول النظام", "مسؤول الجهة", "جهتك", "بريد العمل"):
        assert word not in message
