"""تنسيق الـRuntime: التفعيل والاستحقاق والمودل والمحرّك.

كل ما يخرج عن العملية مزيّف: Backend المستضاف، ومخزن المودل، ومحرّك
`llama-server`. ما يُختبر هنا هو **قرارات** الـRuntime لا نداءات الشبكة.
"""

from __future__ import annotations

import pytest

from govmind_runtime.control_plane import (
    ActivationRejectedError,
    Entitlement,
    ModelArtifactInfo,
    OfflineError,
    SubscriptionBlockedError,
)
from govmind_runtime.identity import DeviceIdentity
from govmind_runtime.service import RuntimeService
from govmind_runtime.state import Phase


class FakeControlPlane:
    """Backend مزيّف يسجّل ما وصله ويردّ بما يُملى عليه."""

    def __init__(self) -> None:
        self.activations: list[dict] = []
        self.activate_error: Exception | None = None
        self.entitlement_error: Exception | None = None
        self.entitlement_value = Entitlement(
            status="active",
            expires_at="2027-01-01T00:00:00+00:00",
            is_usable=True,
            blocked_reason=None,
            device_name="حاسب الاختبار",
        )
        self.artifact = ModelArtifactInfo(
            download_url="https://blob.test/m.gguf?sig=SECRET",
            file_name="govmind-model.gguf",
            sha256="a" * 64,
            size_bytes=1024,
        )

    def activate(self, *, token, device_secret, device_name):
        if self.activate_error:
            raise self.activate_error
        self.activations.append(
            {"token": token, "secret": device_secret, "name": device_name}
        )
        return {"activation_id": 1}

    def entitlement(self, device_secret):
        if self.entitlement_error:
            raise self.entitlement_error
        return self.entitlement_value

    def model_artifact(self, device_secret):
        return self.artifact


class FakeModelStore:
    def __init__(self, installed: bool = False) -> None:
        self.installed = installed
        self.downloads = 0
        self.cancelled = False
        self.error: Exception | None = None

    def is_installed(self) -> bool:
        return self.installed

    def download(self, artifact, *, on_progress=None):
        self.downloads += 1
        if self.error:
            raise self.error
        if on_progress:
            from govmind_runtime.model_store import DownloadProgress

            on_progress(DownloadProgress(received=1024, total=1024))
        self.installed = True

    def cancel(self) -> None:
        self.cancelled = True


class FakeSupervisor:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.error: Exception | None = None
        self.base_url = None

    def start(self, **kwargs):
        if self.error:
            raise self.error
        self.started += 1
        self.base_url = "http://127.0.0.1:51234/v1"
        return self.base_url

    def stop(self) -> None:
        self.stopped += 1
        self.base_url = None


@pytest.fixture
def service(config, protector):
    """خدمة بكل أطرافها مزيّفة، وهوية على قرص مؤقت."""
    return RuntimeService(
        config,
        identity=DeviceIdentity(config.data_dir, protector),
        control_plane=FakeControlPlane(),
        model_store=FakeModelStore(),
        supervisor=FakeSupervisor(),
    )


def wait_for_worker(service: RuntimeService) -> None:
    worker = service._worker
    if worker is not None:
        worker.join(timeout=10)


# ===========================================================================
# التفعيل
# ===========================================================================
def test_starts_awaiting_activation(service):
    assert service.is_activated is False
    service.prepare()
    assert service.state.phase is Phase.AWAITING_ACTIVATION


def test_activation_generates_a_local_secret_and_sends_it(service):
    """السرّ يولَّد **محليًا** ثم يُرسل — لا يأتي من الإضافة ولا من السيرفر."""
    service.activate("installation-token-value-32-chars")
    wait_for_worker(service)

    sent = service._control.activations
    assert len(sent) == 1
    assert sent[0]["token"] == "installation-token-value-32-chars"
    assert sent[0]["secret"] == service._identity.load()
    assert len(sent[0]["secret"]) >= 32


def test_device_name_carries_no_user_identity(service):
    """اسم الجهاز وصفي: لا اسم مستخدم ولا معرّف عتاد."""
    service.activate("installation-token-value-32-chars")
    wait_for_worker(service)

    import getpass

    name = service._control.activations[0]["name"]
    assert getpass.getuser().lower() not in name.lower()
    assert "حاسب" in name


def test_failed_activation_leaves_no_orphan_identity(service):
    """**لا تبقَ هوية بلا تفعيل.**

    لولا هذا لظنّ الإقلاع التالي أن الجهاز مفعَّل، ففشل كل نداء بلا سبب
    مفهوم للمستخدم.
    """
    service._control.activate_error = ActivationRejectedError("رمز غير صالح")

    with pytest.raises(ActivationRejectedError):
        service.activate("installation-token-value-32-chars")

    assert service.is_activated is False
    assert service.state.phase is Phase.AWAITING_ACTIVATION


def test_activation_is_idempotent(service):
    """إعادة الإرسال بعد انقطاع لا تفشل ولا تولّد هوية ثانية."""
    service.activate("installation-token-value-32-chars")
    wait_for_worker(service)
    secret = service._identity.load()

    service.activate("installation-token-value-32-chars")
    wait_for_worker(service)

    assert service._identity.load() == secret
    assert len(service._control.activations) == 1


def test_second_device_rejection_is_surfaced(service):
    service._control.activate_error = ActivationRejectedError(
        "هذا الاشتراك مفعّل على جهاز آخر."
    )
    with pytest.raises(ActivationRejectedError) as caught:
        service.activate("installation-token-value-32-chars")
    assert "جهاز آخر" in str(caught.value)


# ===========================================================================
# الاستحقاق
# ===========================================================================
def test_blocked_subscription_stops_the_model(service):
    service._identity.ensure()
    service._control.entitlement_value = Entitlement(
        status="expired",
        expires_at="2026-01-01T00:00:00+00:00",
        is_usable=False,
        blocked_reason="انتهى اشتراكك بتاريخ ٢٠٢٦-٠١-٠١.",
        device_name="حاسب الاختبار",
    )

    assert service.refresh_entitlement() is False
    assert service.state.phase is Phase.BLOCKED
    assert "انتهى اشتراكك" in service.state.message
    assert service._supervisor.stopped >= 1


def test_revoked_device_stops_the_model(service):
    """إبطال المسؤول للتفعيل: يتوقف المودل وتظهر رسالة تشرح."""
    service._identity.ensure()
    service._control.entitlement_error = SubscriptionBlockedError(
        "هذا الجهاز غير مفعَّل على أي اشتراك."
    )

    assert service.refresh_entitlement() is False
    assert service.state.phase is Phase.BLOCKED
    assert service._supervisor.stopped >= 1


def test_offline_does_not_stop_the_service(service):
    """**انقطاع الشبكة ليس منعًا.**

    اشتراك تحقّقنا منه قبل ساعة لا يبطل لأن الشبكة انقطعت، ومنع موظف من
    العمل بسبب شبكته عقوبة على غير ذنب.
    """
    service._identity.ensure()
    service._control.entitlement_error = OfflineError("لا اتصال")

    assert service.refresh_entitlement() is True
    assert service.state.phase is not Phase.BLOCKED
    assert service._supervisor.stopped == 0


# ===========================================================================
# المودل والمحرّك
# ===========================================================================
def test_prepare_downloads_then_starts(service):
    service._identity.ensure()
    service.prepare()

    assert service._models.downloads == 1
    assert service._supervisor.started == 1
    assert service.state.phase is Phase.READY


def test_prepare_skips_download_when_model_installed(service):
    service._identity.ensure()
    service._models.installed = True
    service.prepare()

    assert service._models.downloads == 0
    assert service._supervisor.started == 1
    assert service.state.phase is Phase.READY


def test_download_failure_surfaces_as_error_phase(service):
    from govmind_runtime.model_store import ModelVerificationError

    service._identity.ensure()
    service._models.error = ModelVerificationError("ملف المودل تالف أو غير مطابق.")
    service.prepare()

    assert service.state.phase is Phase.ERROR
    assert "تالف" in service.state.message
    assert service._supervisor.started == 0


def test_model_start_failure_surfaces_in_arabic(service):
    from govmind_runtime.llama_supervisor import SupervisorError

    service._identity.ensure()
    service._models.installed = True
    service._supervisor.error = SupervisorError(
        "توقّف محرّك المودل أثناء التحميل."
    )
    service.prepare()

    assert service.state.phase is Phase.ERROR
    assert "محرّك المودل" in service.state.message


def test_blocked_subscription_prevents_model_start(service):
    service._identity.ensure()
    service._models.installed = True
    service._control.entitlement_value = Entitlement(
        status="suspended",
        expires_at="2027-01-01T00:00:00+00:00",
        is_usable=False,
        blocked_reason="اشتراكك موقوف حاليًا.",
        device_name="حاسب",
    )
    service.prepare()

    assert service.state.phase is Phase.BLOCKED
    assert service._supervisor.started == 0


def test_shutdown_stops_the_child_process(service):
    """**لا تُترك عملية يتيمة** تحجز الذاكرة وملف المودل."""
    service._identity.ensure()
    service._models.installed = True
    service.prepare()
    service.shutdown()

    assert service._supervisor.stopped >= 1


def test_cancel_download_is_forwarded(service):
    service.cancel_download()
    assert service._models.cancelled is True


def test_state_snapshot_hides_internal_details(service):
    """⚠️ لقطة الحالة لا تحمل منفذًا ولا مسارًا ولا سرًّا."""
    service._identity.ensure()
    service._models.installed = True
    service.prepare()

    text = str(service.state.snapshot())
    assert "127.0.0.1" not in text
    assert str(service.config.data_dir) not in text
    assert service._identity.load() not in text
