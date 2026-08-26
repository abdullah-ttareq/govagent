"""مخزن بيانات الملفات المرفوعة، يُختار من ``DATA_STORE``.

هنا **البيانات الوصفية فقط** (الاسم والحجم والنوع والمالك والجهة والمحادثة)؛
الملف نفسه على قرص السيرفر، والمخزن يحمل مساره لا محتواه — كما في جدول
``files`` بالمخطط.

**قاعدة العزل — نطاق الجهة للقراءة، والمالك للتعديل:**

* **القراءة** مقيّدة بـ``organization_id`` وحده. الملفات معرفةٌ مشتركة داخل
  الجهة: محتواها متاح لكل موظفيها عبر البحث المتجهي
  (``search_chunks`` مقيّد بالجهة لا بالمالك)، فلو بقيت **بياناتها** خاصة
  بالمالك لاستشهد الرد بمصدر لا يستطيع قارئه معرفة ما هو. صلاحية المصدر
  يجب أن توازي صلاحية محتواه.
* **التعديل والحذف** للرافع أو لمسؤول الجهة فقط — يفرضه
  `file_service` لا هذا الملف.
* جهة أخرى: لا شيء. كل دالة هنا تأخذ ``organization_id`` ولا توجد دالة
  تقرأ ملفًا بمعرّفه وحده.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import settings
from .conversation_store import Page

#: حالة استخراج النص: pending ← processed | failed، مطابقة لقيد ck_files_status.
FileStatus = ("pending", "processed", "failed")

#: نوع المحتوى المشتق من الامتداد المعتمد. لا يُؤخذ من العميل: ترويسة
#: Content-Type يكتبها المتصفح ويمكن تزويرها، والامتداد مُتحقَّق منه أصلًا.
MIME_BY_EXTENSION: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".txt": "text/plain; charset=utf-8",
}


class FileStoreError(Exception):
    """خطأ في مخزن الملفات، برسالة عربية صالحة للعرض."""


@dataclass(frozen=True)
class FileRecord:
    """بيانات ملف مرفوع واحد."""

    id: int
    organization_id: int
    user_id: int
    conversation_id: int | None
    original_name: str
    storage_path: str
    mime_type: str
    size_bytes: int
    status: str
    created_at: datetime


class FileStore(ABC):
    """واجهة تخزين بيانات الملفات."""

    name: str = "base"

    @abstractmethod
    def create_file(
        self,
        *,
        organization_id: int,
        user_id: int,
        conversation_id: int | None,
        original_name: str,
        storage_path: str,
        mime_type: str,
        size_bytes: int,
    ) -> FileRecord:
        """يسجّل ملفًا جديدًا بحالة pending."""
        raise NotImplementedError

    @abstractmethod
    def get_file(
        self, *, file_id: int, organization_id: int
    ) -> FileRecord | None:
        """يقرأ ملفًا **داخل جهته**، أو None. أي موظف في الجهة يقرؤه."""
        raise NotImplementedError

    @abstractmethod
    def list_files(
        self,
        *,
        organization_id: int,
        uploaded_by: int | None,
        conversation_id: int | None,
        limit: int,
        offset: int,
    ) -> Page:
        """يعيد ملفات الجهة من الأحدث.

        Args:
            uploaded_by: قصر القائمة على رافع بعينه، أو None لكل الجهة.
            conversation_id: قصرها على محادثة، وملكيتها تُتحقَّق قبلها.
        """
        raise NotImplementedError

    @abstractmethod
    def set_status(
        self, *, file_id: int, organization_id: int, status: str
    ) -> FileRecord | None:
        """يحدّث حالة الاستخراج بعد المعالجة."""
        raise NotImplementedError

    @abstractmethod
    def delete_file(self, *, file_id: int, organization_id: int) -> bool:
        """يحذف سجل ملف داخل جهته. يعيد False إن لم يوجد فيها.

        صلاحية الحذف (الرافع أو مسؤول الجهة) تُفحص في `file_service`
        قبل الوصول إلى هنا.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# المخزن المحلي
# ---------------------------------------------------------------------------
class MemoryFileStore(FileStore):
    """بيانات ملفات داخل ذاكرة العملية، للتطوير والاختبار فقط.

    الملف نفسه يبقى على القرص في الحالتين — هذا المخزن للبيانات الوصفية.
    """

    name = "memory"

    _files: dict[int, FileRecord] = {}
    _next_id: int = 1
    _lock = threading.Lock()

    def create_file(
        self,
        *,
        organization_id: int,
        user_id: int,
        conversation_id: int | None,
        original_name: str,
        storage_path: str,
        mime_type: str,
        size_bytes: int,
    ) -> FileRecord:
        with MemoryFileStore._lock:
            record = FileRecord(
                id=MemoryFileStore._next_id,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=conversation_id,
                original_name=original_name,
                storage_path=storage_path,
                mime_type=mime_type,
                size_bytes=size_bytes,
                status="pending",
                created_at=datetime.now(UTC),
            )
            MemoryFileStore._files[record.id] = record
            MemoryFileStore._next_id += 1
        return record

    def get_file(
        self, *, file_id: int, organization_id: int
    ) -> FileRecord | None:
        record = MemoryFileStore._files.get(file_id)
        # شرط الجهة هنا لا في المستدعي: العزل لا يُترك لانضباط النداء.
        if record is None or record.organization_id != organization_id:
            return None
        return record

    def list_files(
        self,
        *,
        organization_id: int,
        uploaded_by: int | None,
        conversation_id: int | None,
        limit: int,
        offset: int,
    ) -> Page:
        with MemoryFileStore._lock:
            visible = [
                record
                for record in MemoryFileStore._files.values()
                if record.organization_id == organization_id
                and (uploaded_by is None or record.user_id == uploaded_by)
                and (
                    conversation_id is None
                    or record.conversation_id == conversation_id
                )
            ]
        visible.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        return Page(
            items=visible[offset : offset + limit],
            total=len(visible),
            limit=limit,
            offset=offset,
        )

    def set_status(
        self, *, file_id: int, organization_id: int, status: str
    ) -> FileRecord | None:
        with MemoryFileStore._lock:
            record = MemoryFileStore._files.get(file_id)
            if record is None or record.organization_id != organization_id:
                return None
            updated = FileRecord(
                id=record.id,
                organization_id=record.organization_id,
                user_id=record.user_id,
                conversation_id=record.conversation_id,
                original_name=record.original_name,
                storage_path=record.storage_path,
                mime_type=record.mime_type,
                size_bytes=record.size_bytes,
                status=status,
                created_at=record.created_at,
            )
            MemoryFileStore._files[file_id] = updated
            return updated

    def delete_file(self, *, file_id: int, organization_id: int) -> bool:
        with MemoryFileStore._lock:
            record = MemoryFileStore._files.get(file_id)
            if record is None or record.organization_id != organization_id:
                return False
            del MemoryFileStore._files[file_id]
            return True

    @classmethod
    def reset(cls) -> None:
        """يفرغ المخزن. للاختبارات ولإعادة التشغيل النظيفة."""
        with cls._lock:
            cls._files = {}
            cls._next_id = 1


# ---------------------------------------------------------------------------
# مخزن Oracle
# ---------------------------------------------------------------------------
class OracleFileStore(FileStore):
    """بيانات الملفات في جدول files."""

    name = "oracle"

    def create_file(
        self,
        *,
        organization_id: int,
        user_id: int,
        conversation_id: int | None,
        original_name: str,
        storage_path: str,
        mime_type: str,
        size_bytes: int,
    ) -> FileRecord:
        from ..database.files import insert_file

        return insert_file(
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=conversation_id,
            original_name=original_name,
            storage_path=storage_path,
            mime_type=mime_type,
            size_bytes=size_bytes,
        )

    def get_file(
        self, *, file_id: int, organization_id: int
    ) -> FileRecord | None:
        from ..database.files import fetch_file

        return fetch_file(file_id=file_id, organization_id=organization_id)

    def list_files(
        self,
        *,
        organization_id: int,
        uploaded_by: int | None,
        conversation_id: int | None,
        limit: int,
        offset: int,
    ) -> Page:
        from ..database.files import fetch_files

        return fetch_files(
            organization_id=organization_id,
            uploaded_by=uploaded_by,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )

    def set_status(
        self, *, file_id: int, organization_id: int, status: str
    ) -> FileRecord | None:
        from ..database.files import update_file_status

        return update_file_status(
            file_id=file_id, organization_id=organization_id, status=status
        )

    def delete_file(self, *, file_id: int, organization_id: int) -> bool:
        from ..database.files import delete_file_row

        return delete_file_row(
            file_id=file_id, organization_id=organization_id
        )


_STORES: dict[str, type[FileStore]] = {
    "memory": MemoryFileStore,
    "oracle": OracleFileStore,
}


def get_file_store(name: str | None = None) -> FileStore:
    """يعيد مخزن بيانات الملفات المفعّل.

    Raises:
        FileStoreError: إذا كان الاسم غير مدعوم.
    """
    store_name = (name or settings.data_store or "memory").strip().lower()
    store_class = _STORES.get(store_name)
    if store_class is None:
        supported = "، ".join(sorted(_STORES))
        raise FileStoreError(
            f"DATA_STORE='{store_name}' غير مدعوم. القيم المدعومة: {supported}."
        )
    return store_class()
