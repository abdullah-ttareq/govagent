"""فتح الواجهة وحارس النسخة الواحدة — انحدار على عطل ظهر في تثبيت فعلي.

**ما حدث.** بعد أول تثبيت ناجح لم يُفتح GovMind ولم تظهر أي رسالة خطأ.
السبب: الاختصار وخانة ما بعد التثبيت يشيران إلى `govmind-runtime.exe` وهو
خادم بلا نافذة (`console=False`)، فيبدأ ويحجز منفذًا ويجلس صامتًا. **لم
يكن في الشيفرة كلها استدعاء واحد يفتح متصفحًا.**

وتبعه عطل ثانٍ: كل ضغطة على الاختصار كانت تبدأ خادمًا جديدًا على المنفذ
التالي، فتراكمت خمس نسخ تستمع على 8765–8769.

هذه الاختبارات تحرس الحلّين معًا.
"""

from __future__ import annotations

import httpx
import pytest

from govmind_runtime import opener
from govmind_runtime.opener import (
    CANDIDATE_PORTS,
    find_running_port,
    open_ui,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def fake_get(live: dict[int, dict]):
    """`httpx.get` مزيّف: يردّ فقط على المنافذ المذكورة في `live`."""

    def _get(url: str, timeout: float = 0) -> FakeResponse:
        port = int(url.split(":")[2].split("/")[0])
        if port not in live:
            raise httpx.ConnectError("refused")
        return FakeResponse(200, live[port])

    return _get


GOVMIND = {"service": "govmind-runtime", "phase": "ready"}
SOMETHING_ELSE = {"service": "some-other-app"}


# ===========================================================================
# اكتشاف الخدمة العاملة
# ===========================================================================
def test_finds_a_running_runtime(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get({8765: GOVMIND}))
    assert find_running_port() == 8765


def test_finds_a_runtime_on_a_fallback_port(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get({8768: GOVMIND}))
    assert find_running_port() == 8768


def test_returns_none_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get({}))
    assert find_running_port() is None


def test_ignores_a_foreign_service_on_our_port(monkeypatch):
    """منفذ يشغله برنامج آخر يردّ ٢٠٠ ليس GovMind.

    بلا فحص التوقيع يفتح البرنامج متصفحًا على واجهة ليست له.
    """
    monkeypatch.setattr(httpx, "get", fake_get({8765: SOMETHING_ELSE}))
    assert find_running_port() is None


def test_probes_the_same_ports_the_extension_probes():
    """القائمة مشتركة مع `extension/config.js` — اختلافها يفقدهما بعضًا."""
    assert CANDIDATE_PORTS == (8765, 8766, 8767, 8768, 8769)


# ===========================================================================
# وضع الفتح
# ===========================================================================
def test_open_ui_opens_the_browser_on_a_running_service(monkeypatch):
    """**جوهر الإصلاح**: يوجد خادم ⇒ يُفتح المتصفح، ولا يُشغَّل خادم ثانٍ."""
    monkeypatch.setattr(httpx, "get", fake_get({8765: GOVMIND}))
    opened: list[int] = []
    started: list[int] = []
    monkeypatch.setattr(opener, "open_browser", lambda port: opened.append(port))
    monkeypatch.setattr(opener, "start_service", lambda: started.append(1))

    assert open_ui() == 0
    assert opened == [8765]
    assert started == [], "لا يجوز تشغيل خادم ثانٍ وواحد يعمل"


def test_open_ui_starts_the_service_when_none_is_running(monkeypatch):
    state: dict[int, dict] = {}
    monkeypatch.setattr(httpx, "get", fake_get(state))

    def start() -> None:
        state[8765] = GOVMIND  # الخدمة صارت جاهزة

    opened: list[int] = []
    monkeypatch.setattr(opener, "start_service", start)
    monkeypatch.setattr(opener, "open_browser", lambda port: opened.append(port))

    assert open_ui() == 0
    assert opened == [8765]


def test_open_ui_reports_failure_visibly(monkeypatch):
    """**الفشل الصامت هو العطل الأصلي.** لا يجوز أن ينتهي بلا رسالة."""
    monkeypatch.setattr(httpx, "get", fake_get({}))
    monkeypatch.setattr(opener, "start_service", lambda: None)
    monkeypatch.setattr(opener, "wait_for_service", lambda timeout=0: None)

    messages: list[str] = []
    monkeypatch.setattr(opener, "_report_failure", lambda text: messages.append(text))
    monkeypatch.setattr(
        opener, "open_browser", lambda port: pytest.fail("لا يُفتح متصفح بلا خدمة")
    )

    assert open_ui() == 1
    assert len(messages) == 1
    assert "تعذّر تشغيل GovMind" in messages[0]
    assert "runtime.log" in messages[0]


def test_browser_url_is_loopback_only(monkeypatch):
    urls: list[str] = []
    monkeypatch.setattr(opener.os, "startfile", lambda url: urls.append(url), raising=False)
    monkeypatch.setattr(opener.sys, "platform", "win32")

    opener.open_browser(8765)
    assert urls == ["http://127.0.0.1:8765/"]


# ===========================================================================
# توزيع الأوضاع
# ===========================================================================
def test_open_flag_routes_to_the_opener(monkeypatch):
    from govmind_runtime import main as main_module

    calls: list[str] = []
    monkeypatch.setattr(main_module, "open_ui", lambda: calls.append("open") or 0)
    monkeypatch.setattr(main_module, "configure_logging", lambda config: None)
    monkeypatch.setattr(
        main_module, "run_service", lambda: pytest.fail("لا خدمة في وضع الفتح")
    )

    assert main_module.main(["--open"]) == 0
    assert calls == ["open"]


def test_no_arguments_routes_to_the_service(monkeypatch):
    from govmind_runtime import main as main_module

    calls: list[str] = []
    monkeypatch.setattr(main_module, "run_service", lambda: calls.append("serve") or 0)
    monkeypatch.setattr(
        main_module, "open_ui", lambda: pytest.fail("لا فتح بلا وسائط")
    )

    assert main_module.main([]) == 0
    assert calls == ["serve"]


# ===========================================================================
# حارس النسخة الواحدة
# ===========================================================================
def test_second_service_exits_instead_of_taking_another_port(monkeypatch):
    """**العطل الثاني**: خمس نسخ تستمع معًا لأن كل ضغطة بدأت واحدة."""
    from govmind_runtime import main as main_module

    class HeldGuard:
        already_running = True

        def release(self) -> None:
            pass

    monkeypatch.setattr(main_module, "configure_logging", lambda config: None)
    monkeypatch.setattr(main_module, "SingleInstance", lambda: HeldGuard())
    monkeypatch.setattr(main_module, "find_running_port", lambda: 8765)
    monkeypatch.setattr(
        main_module, "_serve", lambda config: pytest.fail("بدأت نسخة ثانية")
    )

    assert main_module.run_service() == 0


def test_first_service_starts_normally(monkeypatch):
    from govmind_runtime import main as main_module

    class FreeGuard:
        already_running = False

        def __init__(self) -> None:
            self.released = False

        def release(self) -> None:
            self.released = True

    guard = FreeGuard()
    served: list[str] = []
    monkeypatch.setattr(main_module, "configure_logging", lambda config: None)
    monkeypatch.setattr(main_module, "SingleInstance", lambda: guard)
    monkeypatch.setattr(main_module, "_serve", lambda config: served.append("x") or 0)

    assert main_module.run_service() == 0
    assert served == ["x"]
    assert guard.released, "الحارس يجب أن يُحرَّر عند الخروج"


def test_single_instance_guard_is_acquired_on_windows():
    """الحارس حقيقي على ويندوز: نسخة ثانية ترى أن الاسم محجوز."""
    import sys

    from govmind_runtime.single_instance import SingleInstance

    first = SingleInstance("Local\\GovMind.Test.Guard")
    try:
        assert first.already_running is False
        second = SingleInstance("Local\\GovMind.Test.Guard")
        try:
            if sys.platform == "win32":
                assert second.already_running is True
            else:
                # لا حارس خارج ويندوز — الـRuntime منتج ويندوز.
                assert second.already_running is False
        finally:
            second.release()
    finally:
        first.release()
