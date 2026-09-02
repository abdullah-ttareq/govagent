"""اختبارات مزود OCI Generative AI.

لا يوجد في هذه الاختبارات أي اتصال حقيقي بـOracle Cloud ولا أي بيانات اعتماد:
كل ما يُختبر هنا هو التحقق من الإعدادات، والاستيراد الكسول لحزمة oci، وتحويل
كل فشل إلى ModelProviderError برسالة عربية. الاختبار الفعلي مقابل خدمة حقيقية
مؤجَّل — انظر test_oracle_live_call_pending_oracle_setup في آخر الملف.
"""

import importlib.util
from types import SimpleNamespace

import pytest

from app.ai import ChatMessage, ModelProviderError
from app.ai.oracle_provider import OracleModelProvider
from app.core.config import settings

OCI_INSTALLED = importlib.util.find_spec("oci") is not None

CONVERSATION = [ChatMessage(role="user", content="اكتب لي خطابًا رسميًا")]


@pytest.fixture
def oci_settings(monkeypatch):
    """يضبط إعدادات OCI لكل اختبار ويعيدها إلى ما كانت عليه بعده."""

    def apply(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setattr(settings, key, value)

    return apply


class _FakeServiceError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class _FakeTimeoutError(Exception):
    """اسم الصنف يحتوي timeout عمدًا — هكذا يصنّفها المزود."""


def _fake_sdk() -> SimpleNamespace:
    """بديل مبسّط لحزمة oci يكفي لاختبار تصنيف الأخطاء وقراءة الرد."""
    return SimpleNamespace(
        root=SimpleNamespace(exceptions=SimpleNamespace(ServiceError=_FakeServiceError)),
        client_class=None,
        models=None,
    )


def _client_raising(error: Exception) -> SimpleNamespace:
    def chat(_details):
        raise error

    return SimpleNamespace(chat=chat)


# ---------------------------------------------------------------------------
# 1) إعداد ناقص
# ---------------------------------------------------------------------------
def test_oracle_with_no_configuration_names_every_missing_variable(oci_settings):
    oci_settings(oci_region="", oci_compartment_id="", oci_model_id="")

    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider().generate(messages=CONVERSATION, system_prompt="تعليمات")

    message = str(exc.value)
    assert "OCI_REGION" in message
    assert "OCI_COMPARTMENT_ID" in message
    assert "OCI_MODEL_ID" in message
    assert "mock" in message


def test_oracle_with_partial_configuration_names_only_the_missing_one(oci_settings):
    oci_settings(
        oci_region="me-jeddah-1",
        oci_compartment_id="ocid1.compartment.oc1..example",
        oci_model_id="",
    )

    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider().generate(messages=CONVERSATION, system_prompt="تعليمات")

    message = str(exc.value)
    assert "OCI_MODEL_ID" in message
    assert "OCI_REGION" not in message.split("المتغيرات الناقصة:")[1]


def test_oracle_checks_configuration_before_touching_the_network(oci_settings):
    """الإعداد الناقص يُكتشف قبل أي محاولة استيراد أو اتصال."""
    oci_settings(oci_region="", oci_compartment_id="", oci_model_id="")

    def fail(*_args, **_kwargs):
        raise AssertionError("لا يجوز استيراد حزمة oci قبل التحقق من الإعدادات")

    # يُلتقط الواصف (staticmethod) نفسه من __dict__ لا الدالة المجرّدة، حتى
    # تعود الفئة إلى حالتها الأصلية ولا تتأثر بقية الاختبارات.
    original = OracleModelProvider.__dict__["_import_sdk"]
    OracleModelProvider._import_sdk = staticmethod(fail)
    try:
        with pytest.raises(ModelProviderError):
            OracleModelProvider().generate(
                messages=CONVERSATION, system_prompt="تعليمات"
            )
    finally:
        OracleModelProvider._import_sdk = original


# ---------------------------------------------------------------------------
# 2) الاستيراد الكسول لحزمة oci
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    OCI_INSTALLED, reason="حزمة oci مثبّتة هنا، فلا يمكن اختبار حالة غيابها"
)
def test_oracle_reports_missing_oci_package_clearly(oci_settings):
    """بإعداد كامل وحزمة غير مثبّتة، الرسالة تشرح الحل ولا تنهار."""
    oci_settings(
        oci_region="me-jeddah-1",
        oci_compartment_id="ocid1.compartment.oc1..example",
        oci_model_id="ocid1.generativeaimodel.oc1..example",
    )

    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider().generate(messages=CONVERSATION, system_prompt="تعليمات")

    message = str(exc.value)
    assert "oci" in message
    assert "mock" in message


def test_importing_the_project_does_not_require_oci():
    """استيراد ملف المزود نفسه يجب ألا يستورد حزمة oci."""
    import sys

    assert OCI_INSTALLED or "oci" not in sys.modules


# ---------------------------------------------------------------------------
# 3) نوع الهوية
# ---------------------------------------------------------------------------
def test_unsupported_auth_type_lists_accepted_values(oci_settings):
    oci_settings(oci_auth_type="kerberos")

    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider._build_signer_or_config(_fake_sdk())

    message = str(exc.value)
    assert "kerberos" in message
    assert "config" in message
    assert "instance_principal" in message


# ---------------------------------------------------------------------------
# 4) تحويل أخطاء الاستدعاء إلى رسائل عربية
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "صلاحية"),
        (403, "صلاحية"),
        (404, "OCI_MODEL_ID"),
        (429, "الحد المسموح"),
        (500, "رمز 500"),
    ],
)
def test_service_errors_become_arabic_messages(status, expected):
    error = _FakeServiceError(status, "internal failure")

    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider._call_model(
            _fake_sdk(), _client_raising(error), details=None
        )

    assert expected in str(exc.value)


def test_timeout_becomes_a_clear_timeout_message():
    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider._call_model(
            _fake_sdk(), _client_raising(_FakeTimeoutError()), details=None
        )
    assert "مهلة" in str(exc.value)


def test_connection_failure_becomes_a_clear_message():
    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider._call_model(
            _fake_sdk(), _client_raising(ConnectionError("no route")), details=None
        )
    assert "تعذّر الاتصال" in str(exc.value)


# ---------------------------------------------------------------------------
# 5) قراءة الرد
# ---------------------------------------------------------------------------
def _response(*texts: str) -> SimpleNamespace:
    parts = [SimpleNamespace(text=text) for text in texts]
    return SimpleNamespace(
        data=SimpleNamespace(
            chat_response=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=parts))]
            )
        )
    )


def test_reply_is_extracted_from_a_valid_response():
    assert OracleModelProvider._extract_reply(_response(" مرحبًا ")) == "مرحبًا"


def test_reply_joins_multiple_content_parts():
    assert OracleModelProvider._extract_reply(_response("سطر", "آخر")) == "سطر\nآخر"


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(data=None),
        SimpleNamespace(data=SimpleNamespace(chat_response=None)),
        SimpleNamespace(
            data=SimpleNamespace(chat_response=SimpleNamespace(choices=[]))
        ),
        _response("   "),
    ],
)
def test_invalid_response_shape_raises_a_clear_error(response):
    with pytest.raises(ModelProviderError) as exc:
        OracleModelProvider._extract_reply(response)
    assert "غير صالح" in str(exc.value)


# ---------------------------------------------------------------------------
# 6) الاختبار الحي — مؤجَّل
# ---------------------------------------------------------------------------
@pytest.mark.skip(
    reason=(
        "Pending Oracle Setup — لا توجد حتى الآن موارد ولا بيانات دخول في "
        "Oracle Cloud (Compartment / Model / هوية OCI)، فلا يمكن تنفيذ "
        "استدعاء حقيقي. يُفعَّل هذا الاختبار بعد تجهيز الحساب."
    )
)
def test_oracle_live_call_pending_oracle_setup():
    """استدعاء حقيقي لـOCI Generative AI والتحقق من وصول رد نصي."""
    result = OracleModelProvider().generate(
        messages=CONVERSATION, system_prompt="تعليمات"
    )
    assert result.provider == "oracle"
    assert result.reply.strip()
