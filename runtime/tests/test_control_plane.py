"""عميل الـControl Plane: القائمة البيضاء، وبيان الاعتماد، والتسريب.

**ما تحرسه هذه الاختبارات:**

* **لا وكيل مفتوح.** كل مسار يخرج من هذا الجهاز يجب أن يكون في
  ``ALLOWED_ROUTES`` مطابقةً حرفية — وإلا رُفض **قبل فتح أي اتصال**.
* بيان اعتماد الجهاز يُلصق في **جانب الخادم** من الـRuntime، في ترويسة
  مخصّصة لا في `Authorization`.
* لا بيان اعتماد ولا رابط موقّع يخرج في رسالة خطأ.
"""

from __future__ import annotations

import httpx
import pytest

from govmind_runtime.control_plane import (
    ALLOWED_ROUTES,
    DEVICE_HEADER,
    ActivationRejectedError,
    ControlPlaneClient,
    ControlPlaneError,
    OfflineError,
    RouteNotAllowedError,
)

CREDENTIAL = "device-credential-value-for-tests-0123456789"
SAS_URL = "https://acct.blob.core.windows.net/m.gguf?sig=SECRETSIGNATUREVALUE"


class Recorder:
    """ينقل الطلبات ويسجّلها. **لا شبكة حقيقية.**"""

    def __init__(self, response=None) -> None:
        self.requests: list[httpx.Request] = []
        self._response = response or httpx.Response(200, json={})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response


def make_client(recorder: Recorder) -> ControlPlaneClient:
    return ControlPlaneClient(
        "https://control.govmind.test",
        client=httpx.Client(transport=httpx.MockTransport(recorder)),
    )


# ===========================================================================
# القائمة البيضاء
# ===========================================================================
def test_the_allowlist_is_small_and_explicit():
    """⚠️ **إضافة مسار هنا قرار أمني.**

    كل مسار في القائمة يُنادى ببيان اعتماد جهاز عميل. الاختبار يثبّت
    القائمة كما هي، فأي إضافة تُفشله وتستدعي قراءة واعية.
    """
    assert ALLOWED_ROUTES == frozenset(
        {
            ("POST", "/api/runtime/activate"),
            ("GET", "/api/runtime/entitlement"),
            ("GET", "/api/runtime/model"),
            # ⚠️ **أُضيف بقرار**: المحادثة السحابية تمرّ بالسيرفر لأن مفتاح
            # المزوّد سرّ سيرفر لا يوضع على جهاز عميل. والجهاز يصادق ببيان
            # اعتماده هو، فيبقى الإبطال والاشتراك نافذَين على كل رسالة.
            ("POST", "/api/runtime/chat"),
        }
    )


def test_allowlist_holds_no_wildcard():
    """لا نمط ولا بادئة: نمطٌ يصير وكيلًا مفتوحًا على ما يُضاف لاحقًا."""
    for method, path in ALLOWED_ROUTES:
        assert method in {"GET", "POST"}
        assert "*" not in path
        assert path.startswith("/api/runtime/")


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/account/subscription"),
        ("POST", "/api/auth/login"),
        ("GET", "/api/runtime"),
        ("GET", "/api/runtime/entitlement/"),
        ("DELETE", "/api/runtime/entitlement"),
        ("POST", "/api/runtime/entitlement"),
        ("GET", "/api/runtime/../account/users"),
    ],
)
def test_unsupported_routes_are_refused_before_any_connection(method, path):
    """⚠️ **يُرفض قبل فتح اتصال**، فلا يخرج بايت واحد من الجهاز."""
    recorder = Recorder()
    client = make_client(recorder)

    with pytest.raises(RouteNotAllowedError):
        client._request(method, path, device_credential=CREDENTIAL)

    assert recorder.requests == []


def test_refusal_message_is_arabic_and_carries_no_credential():
    recorder = Recorder()
    client = make_client(recorder)

    with pytest.raises(RouteNotAllowedError) as caught:
        client._request("GET", "/api/account/users", device_credential=CREDENTIAL)

    assert CREDENTIAL not in str(caught.value)
    assert "GovMind" in str(caught.value)


def test_a_refused_route_is_still_a_control_plane_error():
    """المستدعي يعالج فرعًا واحدًا؛ لا يحتاج أن يعرف هذا الفرع بعينه."""
    assert issubclass(RouteNotAllowedError, ControlPlaneError)


# ===========================================================================
# بيان الاعتماد
# ===========================================================================
def test_credential_travels_in_its_own_header():
    """ليست `Authorization`: تمييزها يمنع خلطها برمز مستخدم في أي وسيط."""
    recorder = Recorder(
        httpx.Response(
            200,
            json={
                "status": "active",
                "expires_at": "2027-01-01T00:00:00+00:00",
                "is_usable": True,
                "blocked_reason": None,
                "device_name": "حاسب",
                "account_email": "owner@example.test",
            },
        )
    )
    client = make_client(recorder)

    entitlement = client.entitlement(CREDENTIAL)

    assert recorder.requests[0].headers[DEVICE_HEADER] == CREDENTIAL
    assert "authorization" not in recorder.requests[0].headers
    assert entitlement.account_email == "owner@example.test"


def test_activation_sends_no_credential_because_it_issues_one():
    """مسار الاستبدال **لا يحمل بيان اعتماد**: هو الذي يصدره."""
    recorder = Recorder(
        httpx.Response(
            200,
            json={
                "activation_id": 1,
                "status": "trial",
                "expires_at": "2027-01-01T00:00:00+00:00",
                "device_credential": CREDENTIAL,
            },
        )
    )
    client = make_client(recorder)

    result = client.activate(
        token="installation-token-0001", device_secret="secret", device_name="حاسب"
    )

    assert DEVICE_HEADER not in recorder.requests[0].headers
    assert result.credential == CREDENTIAL


def test_a_response_without_a_credential_is_a_failure():
    """ربطٌ بلا وسيلة مصادقة ليس نجاحًا ناقصًا — هو فشل."""
    recorder = Recorder(
        httpx.Response(200, json={"activation_id": 1, "status": "trial"})
    )
    client = make_client(recorder)

    with pytest.raises(ControlPlaneError):
        client.activate(
            token="installation-token-0001",
            device_secret="secret",
            device_name="حاسب",
        )


def test_rejected_activation_keeps_the_server_message():
    recorder = Recorder(
        httpx.Response(409, json={"detail": "حسابك مفعّل حاليًا على جهاز آخر."})
    )
    client = make_client(recorder)

    with pytest.raises(ActivationRejectedError) as caught:
        client.activate(
            token="installation-token-0001",
            device_secret="secret",
            device_name="حاسب",
        )
    assert "جهاز آخر" in str(caught.value)


def test_no_arabic_message_mentions_an_administrator():
    """⚠️ **لا مسؤول نظام في هذا المنتج.** الرسائل تصف ما يفعله العميل بنفسه."""
    import inspect

    from govmind_runtime import control_plane

    source = inspect.getsource(control_plane)
    for word in ("مسؤول النظام", "مسؤول الجهة", "جهتك", "بريد العمل"):
        assert word not in source


# ===========================================================================
# التسريب
# ===========================================================================
def test_offline_message_carries_no_url_or_credential():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = ControlPlaneClient(
        "https://control.govmind.test",
        client=httpx.Client(transport=httpx.MockTransport(refuse)),
    )

    with pytest.raises(OfflineError) as caught:
        client.entitlement(CREDENTIAL)

    message = str(caught.value)
    assert CREDENTIAL not in message
    assert "control.govmind.test" not in message


def test_a_server_error_message_carries_no_signed_url():
    recorder = Recorder(httpx.Response(500, json={"detail": SAS_URL}))
    client = make_client(recorder)

    with pytest.raises(ControlPlaneError) as caught:
        client.model_artifact(CREDENTIAL)

    assert "sig=" not in str(caught.value)
    assert "SECRETSIGNATUREVALUE" not in str(caught.value)


# ===========================================================================
# عميل واحد يعيش بعمر العملية — إصلاح عطل حيّ
# ===========================================================================
def test_one_client_is_created_and_reused():
    """⚠️ **إصلاح عطل حيّ، لا تحسين أداء.**

    كان كل طلب ينشئ `httpx.Client()` جديدًا، وإنشاؤه يبني سياق TLS بقراءة
    ملف شهادات `certifi`. في البناء المجمَّع يُفكّ ذلك الملف إلى مجلد
    مؤقّت، واختفاؤه من تحت عملية حيّة يجعل **كل** نداء بعده يفشل. سجلّ
    جهاز العميل أظهرها: `FileNotFoundError` من `ssl.create_default_context`
    تُسقط خيط الاستحقاق الدوري بعد ساعة من الإقلاع.
    """
    created: list[httpx.Client] = []
    real_client = httpx.Client

    class CountingClient(real_client):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    recorder = Recorder(httpx.Response(200, json={}))
    client = ControlPlaneClient("https://control.govmind.test")
    # عميل حقيقي بنقل مزيّف: ما يُقاس هو **عدد مرات الإنشاء**.
    client._owned = CountingClient(transport=httpx.MockTransport(recorder))
    created.clear()

    for _ in range(5):
        client._request("GET", "/api/runtime/entitlement", device_credential=CREDENTIAL)

    assert len(recorder.requests) == 5, "لم تُنفَّذ الطلبات الخمسة"
    assert created == [], "أُنشئ عميل جديد بعد الأول"
    client.close()


def test_the_client_is_created_once_under_concurrency():
    """خيط الاستحقاق وخيط التجهيز قد يبلغان أول نداء معًا."""
    import threading

    client = ControlPlaneClient("https://control.govmind.test")
    seen: list[httpx.Client] = []
    barrier = threading.Barrier(8)

    def grab() -> None:
        barrier.wait()
        seen.append(client._session())

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(item) for item in seen}) == 1, "أُنشئ أكثر من عميل"
    client.close()


def test_an_os_error_becomes_an_arabic_offline_message():
    """⚠️ `FileNotFoundError` ليست `httpx.HTTPError`.

    كانت تمرّ بلا التقاط فتُسقط الخيط بأثر بايثون خام في السجلّ. الصحيح
    أن تصير «تعذّر الاتصال»: هي بالضبط ما يستطيع العميل فعله حيالها.
    """

    def explode(request: httpx.Request) -> httpx.Response:
        raise FileNotFoundError(2, "No such file or directory")

    client = ControlPlaneClient(
        "https://control.govmind.test",
        client=httpx.Client(transport=httpx.MockTransport(explode)),
    )

    with pytest.raises(OfflineError) as caught:
        client.entitlement(CREDENTIAL)

    message = str(caught.value)
    assert "تعذّر الاتصال" in message
    assert "FileNotFoundError" not in message
    assert CREDENTIAL not in message


def test_close_does_not_close_an_injected_client():
    """العميل المُمرَّر يملكه من مرّره؛ إغلاقه هنا يكسر مستدعيًا يظنّه حيًّا."""
    injected = httpx.Client(transport=httpx.MockTransport(Recorder()))
    client = ControlPlaneClient("https://control.govmind.test", client=injected)

    client.close()
    assert injected.is_closed is False
    injected.close()


def test_shutdown_closes_the_owned_client(tmp_path):
    """`RuntimeService.shutdown` لا يترك اتصالًا مفتوحًا."""
    from govmind_runtime.config import RuntimeConfig
    from govmind_runtime.service import RuntimeService

    config = RuntimeConfig(
        control_plane_url="https://control.govmind.test",
        data_dir=tmp_path / "data",
        install_root=tmp_path / "install",
        port=8765,
    )
    service = RuntimeService(config)
    owned = service._control._session()

    service.shutdown()
    assert owned.is_closed is True
