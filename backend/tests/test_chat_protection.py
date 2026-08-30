"""حماية `/api/chat` بالكامل — إنهاء الوضع الانتقالي (مهمة P4-03).

كان المسار يقبل الطلبات **بلا رمز دخول** ليبقى قابلًا للتجربة قبل أن تضيف
الواجهة والإضافة تسجيل الدخول. أُنجز ذلك في P3-01 و P4-01، فأُغلق الباب:
كل طلب يتطلب رمزًا صالحًا واشتراكًا ساريًا.

**ما يثبته هذا الملف تحديدًا:**

* الطلب بلا رمز يعيد **401** بالغلاف العربي الموحّد.
* ولا يصل المزود إطلاقًا — لا استهلاك للمودل بلا هوية ولا سجل تدقيق.
* ولا يجري أي بحث في ملفات أي جهة، ولا يعود في الرد حقل `sources`.
* الجهة تُقرأ من الرمز وحده.

بقية حالات المصادقة (الدخول الخاطئ، والرمز التالف، والمنتهي، والمسارات
المحمية الأخرى) مغطّاة في `test_auth.py`، وانتهاء الاشتراك في
`test_subscriptions.py` — ولا تُكرَّر هنا.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.services.conversation_store import MemoryConversationStore
from app.services.file_store import MemoryFileStore
from app.services.retrieval import MemoryChunkStore
from app.services.user_store import MemoryUserStore

client = TestClient(app)

EMPLOYEE = "n.alharbi@digital-services.test"


@pytest.fixture(autouse=True)
def clean_stores():
    for store in (MemoryUserStore, MemoryConversationStore, MemoryFileStore):
        store.reset()
    MemoryChunkStore.clear()
    yield
    for store in (MemoryUserStore, MemoryConversationStore, MemoryFileStore):
        store.reset()
    MemoryChunkStore.clear()


@pytest.fixture
def employee() -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": EMPLOYEE, "password": settings.dev_seed_password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _never_called(name: str):
    """بديل ينفجر إن استُدعي — يثبت أن المسار لم يصل إليه أصلًا."""

    def boom(*_args, **_kwargs):
        raise AssertionError(f"لا يجوز استدعاء {name} في طلب بلا رمز دخول")

    return boom


# ---------------------------------------------------------------------------
# ١) بلا رمز: 401 بالغلاف العربي الموحّد
# ---------------------------------------------------------------------------
def test_chat_without_a_token_returns_401():
    response = client.post("/api/chat", json={"message": "اكتب لي خطابًا رسميًا"})

    assert response.status_code == 401


def test_chat_without_a_token_uses_the_unified_arabic_envelope():
    """شكل الخطأ نفسه في كل المسارات: detail عربي و code ثابت و errors موجود."""
    response = client.post("/api/chat", json={"message": "مرحبًا"})
    body = response.json()

    assert set(body) == {"detail", "status", "code", "errors"}
    assert body["status"] == 401
    assert body["code"] == "unauthorized"
    assert body["errors"] == []
    # رسالة عربية صالحة للعرض على الموظف مباشرة، تشرح الإجراء المطلوب.
    assert "تسجيل الدخول" in body["detail"]
    assert any("؀" <= char <= "ۿ" for char in body["detail"])


def test_chat_without_a_token_advertises_the_bearer_scheme():
    """ترويسة قياسية تخبر العميل بنوع المصادقة المطلوبة."""
    response = client.post("/api/chat", json={"message": "مرحبًا"})

    assert response.headers.get("WWW-Authenticate") == "Bearer"


# ---------------------------------------------------------------------------
# ٢) بلا رمز: لا مودل ولا مصادر
# ---------------------------------------------------------------------------
def test_chat_without_a_token_never_reaches_the_model(monkeypatch):
    """استهلاك المزود بلا هوية ولا سجل تدقيق غير مقبول على سيرفر جهة."""
    monkeypatch.setattr(
        "app.api.chat.send_message", _never_called("send_message")
    )
    monkeypatch.setattr(
        "app.services.chat_service.get_model_provider",
        _never_called("get_model_provider"),
    )

    response = client.post("/api/chat", json={"message": "مرحبًا"})

    assert response.status_code == 401


def test_chat_without_a_token_never_searches_any_organization(monkeypatch):
    """بلا رمز لا جهة، وبلا جهة لا بحث — ولا حتى محاولة."""
    monkeypatch.setattr(
        "app.services.chat_service.retrieve_context",
        _never_called("retrieve_context"),
    )

    response = client.post("/api/chat", json={"message": "ما مصروفات التشغيل؟"})

    assert response.status_code == 401


def test_chat_without_a_token_returns_no_sources_and_no_reply():
    """رد الرفض لا يحمل أي أثر من رد الإيجنت ولا من ملفات أي جهة."""
    response = client.post("/api/chat", json={"message": "ما مصروفات التشغيل؟"})
    body = response.json()

    assert response.status_code == 401
    assert "sources" not in body
    assert "reply" not in body
    assert "conversation_id" not in body


def test_chat_without_a_token_saves_no_conversation():
    """لا يُنشأ سجل لأحد من طلب مرفوض."""
    client.post("/api/chat", json={"message": "مرحبًا"})

    listing = MemoryConversationStore().list_conversations(
        organization_id=1, user_id=2, limit=50, offset=0
    )
    assert listing.total == 0


def test_a_rejected_request_is_not_even_validated():
    """الرفض يسبق التحقق من الجسم: رسالة فارغة بلا رمز تعيد 401 لا 422.

    دليلٌ إضافي على أن الطلب لا يُعالَج أصلًا قبل إثبات الهوية.
    """
    response = client.post("/api/chat", json={"message": "   "})

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# ٣) الرمز غير الصالح على هذا المسار تحديدًا
# ---------------------------------------------------------------------------
def test_chat_with_an_expired_token_returns_401():
    """رمز منتهي الصلاحية لا يفتح المسار، ولو كان موقّعًا بالسر الصحيح."""
    token, _ = create_access_token(
        user_id=2, organization_id=1, role="employee", expires_minutes=-1
    )

    response = client.post(
        "/api/chat",
        json={"message": "مرحبًا"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_chat_with_an_empty_bearer_value_returns_401():
    response = client.post(
        "/api/chat",
        json={"message": "مرحبًا"},
        headers={"Authorization": "Bearer "},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# ٤) حراسة انحدار: لا رجوع إلى الوضع الانتقالي
# ---------------------------------------------------------------------------
def test_the_chat_request_schema_has_no_history_field():
    """حقل `history` حُذف: سياقٌ يرسله العميل يمكن تلفيقه.

    يفشل هذا الاختبار إن أعاده أحد إلى `ChatRequest` مستقبلًا.
    """
    schema = app.openapi()["components"]["schemas"]["ChatRequest"]

    assert "history" not in schema["properties"]
    # ولا الجهة: تُقرأ من الرمز وحده.
    assert "organization_id" not in schema["properties"]


def test_the_chat_route_requires_authentication_in_the_spec():
    """المسار معلن كمحمي في OpenAPI.

    يفشل إن عاد أحد إلى `OptionalCurrentUser`، فالمواصفة حينها تُسقط شرط
    الأمان عن المسار.
    """
    operation = app.openapi()["paths"]["/api/chat"]["post"]

    assert operation.get("security"), "‏/api/chat يجب أن يعلن شرط مصادقة"


def test_chat_with_a_token_works_and_saves_the_exchange(employee):
    """الوجه الآخر: بالرمز يعمل المسار ويحفظ التبادل بصاحبه."""
    response = client.post(
        "/api/chat", json={"message": "كم مدة الإجازة؟"}, headers=employee
    )

    assert response.status_code == 200
    body = response.json()
    conversation_id = body["conversation_id"]
    assert isinstance(conversation_id, int)

    messages = client.get(
        f"/api/conversations/{conversation_id}/messages", headers=employee
    ).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "كم مدة الإجازة؟"
