"""الاشتراكات وإعدادات المودل في جدولي subscriptions و model_settings.

**قاعدة العزل:** كل عبارة مقيّدة بـ``organization_id``، وهو مفتاح فريد في
الجدولين (``uq_subscriptions_org`` و ``uq_model_settings_org``) فلا يوجد أكثر
من صف لجهة.

``updated_at`` مسؤولية الـBackend لا Trigger — انظر تعليق المخطط.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .oracle import get_connection

if TYPE_CHECKING:  # يُستورد للتلميح النوعي فقط.
    from ..services.organization_settings_store import ModelSettings, Subscription

_FETCH_SUBSCRIPTION = """
    SELECT s.organization_id, s.status, s.seats, s.starts_at, s.expires_at
      FROM subscriptions s
     WHERE s.organization_id = :organization_id
"""

# MERGE بدل INSERT/UPDATE منفصلين: صف واحد لكل جهة (uq_subscriptions_org)،
# وعبارتان متتاليتان تتركان نافذة يفشل فيها الإدراج على قيد التفرّد.
_MERGE_SUBSCRIPTION = """
    MERGE INTO subscriptions s
    USING (SELECT :organization_id AS organization_id FROM dual) src
       ON (s.organization_id = src.organization_id)
     WHEN MATCHED THEN
          UPDATE SET s.status = :status,
                     s.seats = :seats,
                     s.starts_at = :starts_at,
                     s.expires_at = :expires_at,
                     s.updated_at = SYSTIMESTAMP
     WHEN NOT MATCHED THEN
          INSERT (organization_id, status, seats, starts_at, expires_at)
          VALUES (:organization_id, :status, :seats, :starts_at, :expires_at)
"""

_FETCH_MODEL_SETTINGS = """
    SELECT m.organization_id, m.provider, m.updated_at
      FROM model_settings m
     WHERE m.organization_id = :organization_id
"""

_MERGE_MODEL_SETTINGS = """
    MERGE INTO model_settings m
    USING (SELECT :organization_id AS organization_id FROM dual) src
       ON (m.organization_id = src.organization_id)
     WHEN MATCHED THEN
          UPDATE SET m.provider = :provider,
                     m.updated_at = SYSTIMESTAMP
     WHEN NOT MATCHED THEN
          INSERT (organization_id, provider)
          VALUES (:organization_id, :provider)
"""


def fetch_subscription(organization_id: int) -> Subscription | None:
    """يقرأ اشتراك الجهة، أو None إن لم يوجد صف لها."""
    from ..services.organization_settings_store import Subscription

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_SUBSCRIPTION, {"organization_id": organization_id}
            )
            row = cursor.fetchone()

    if row is None:
        return None
    return Subscription(
        organization_id=int(row[0]),
        status=row[1],
        seats=int(row[2]),
        starts_at=row[3],
        expires_at=row[4],
    )


def save_subscription(
    *,
    organization_id: int,
    status: str,
    seats: int,
    starts_at: datetime,
    expires_at: datetime,
) -> Subscription:
    """ينشئ اشتراك الجهة أو يستبدله، ويعيده كما استقر في القاعدة."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _MERGE_SUBSCRIPTION,
                {
                    "organization_id": organization_id,
                    "status": status,
                    "seats": seats,
                    "starts_at": starts_at,
                    "expires_at": expires_at,
                },
            )
        connection.commit()

    stored = fetch_subscription(organization_id)
    if stored is None:  # pragma: no cover — لا يقع بعد MERGE ناجح
        from ..services.organization_settings_store import Subscription

        return Subscription(
            organization_id=organization_id,
            status=status,
            seats=seats,
            starts_at=starts_at,
            expires_at=expires_at,
        )
    return stored


def fetch_model_settings(organization_id: int) -> ModelSettings | None:
    """يقرأ إعدادات مودل الجهة، أو None إن لم تختر شيئًا بعد."""
    from ..services.organization_settings_store import ModelSettings

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _FETCH_MODEL_SETTINGS, {"organization_id": organization_id}
            )
            row = cursor.fetchone()

    if row is None:
        return None
    return ModelSettings(
        organization_id=int(row[0]), provider=row[1], updated_at=row[2]
    )


def save_model_settings(*, organization_id: int, provider: str) -> ModelSettings:
    """يثبّت مزود المودل للجهة ويعيد الصف كما استقر."""
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _MERGE_MODEL_SETTINGS,
                {"organization_id": organization_id, "provider": provider},
            )
        connection.commit()

    stored = fetch_model_settings(organization_id)
    if stored is None:  # pragma: no cover — لا يقع بعد MERGE ناجح
        from datetime import UTC

        from ..services.organization_settings_store import ModelSettings

        return ModelSettings(
            organization_id=organization_id,
            provider=provider,
            updated_at=datetime.now(UTC),
        )
    return stored
