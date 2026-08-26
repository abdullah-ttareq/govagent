"""رفع الملفات: التحقق، والحفظ على القرص، والبيانات الوصفية، والفهرسة.

**سياسة الصلاحيات (مراجعة P2-03):**

* **القراءة داخل الجهة.** أي موظف في الجهة يقرأ بيانات أي ملف فيها. السبب أن
  محتوى الملفات متاح لهم أصلًا عبر البحث المتجهي — ``search_chunks`` مقيّد
  بـ``organization_id`` لا بالمالك — فلو بقيت **بيانات** الملف خاصة بالرافع
  لظهر في ``sources`` مصدرٌ لا يستطيع قارئ الرد معرفة ما هو. صلاحية المصدر
  يجب أن توازي صلاحية محتواه.
* **الحذف للرافع أو لمسؤول الجهة.** القراءة مشتركة، أما إزالة معرفة من
  الجهة فقرارٌ لصاحبها أو لمن يدير الجهة.
* **جهة أخرى: 404 بلا تسريب.** لا يُفرَّق بين «غير موجود» و«لجهة أخرى».

**المحادثات تبقى خاصة بمالكها** — انظر `conversation_service`. وعليه لا يُعرض
ارتباط الملف بمحادثة إلا لرافعه؛ الارتباط جزء من خصوصية المحادثة لا الملف.

**أمان المسار:** اسم الملف الذي يرسله الموظف **لا يُستخدم في المسار إطلاقًا**.
اسم مثل ``../../.env`` أو ``C:\\Windows\\x`` كان سيكتب خارج مجلد الرفع. الاسم
على القرص معرّف عشوائي + الامتداد المُتحقَّق منه، والاسم الأصلي يبقى بيانًا
وصفيًا في القاعدة فقط.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from ..core.config import settings
from .audit_service import record_for
from .audit_store import ACTION_FILE_DELETED, ACTION_FILE_UPLOADED
from .conversation_service import get_conversation
from .conversation_store import Page, resolve_page
from .file_store import MIME_BY_EXTENSION, FileRecord, get_file_store
from .text_extraction import FileExtractionError, validate_upload
from .user_store import User


class FileError(Exception):
    """خطأ في التعامل مع الملفات، برسالة عربية صالحة للعرض."""


class FileNotFoundInScopeError(FileError):
    """الملف غير موجود **في جهة صاحب الطلب**. يشمل ملفات الجهات الأخرى."""


class FilePermissionError(FileError):
    """الملف داخل الجهة، لكن صاحب الطلب ليس رافعه ولا مسؤولها."""


class FileStorageError(FileError):
    """تعذّر كتابة الملف على قرص السيرفر."""


@dataclass(frozen=True)
class UploadResult:
    """نتيجة رفع ملف واحد."""

    file: FileRecord
    #: عدد المقاطع المفهرسة للبحث، و0 إن لم تنجح الفهرسة.
    chunk_count: int
    #: سبب فشل الفهرسة بالعربية، أو None إن نجحت.
    indexing_error: str | None


def can_modify(*, actor: User, record: FileRecord) -> bool:
    """هل يملك ``actor`` صلاحية تعديل هذا الملف أو حذفه؟

    الرافع أو مسؤول الجهة. تُصدَّر للواجهة كذلك حتى تعرف أيّ ملف تعرض له زر
    حذف، بدل أن تكتشف المنع بعد الضغط.
    """
    return record.user_id == actor.id or actor.role == "admin"


def _storage_root() -> Path:
    return Path(settings.upload_dir)


def _build_storage_path(*, organization_id: int, extension: str) -> Path:
    """يبني مسار حفظ آمنًا لا يعتمد على اسم الملف الذي أرسله الموظف.

    التقسيم بالجهة يجعل ملفات الجهات منفصلة على القرص كذلك، لا في القاعدة
    وحدها، فيسهل حذف جهة أو نسخها احتياطيًا.
    """
    # uuid4 يمنع تخمين مسار ملف، ويمنع تصادم اسمين متطابقين.
    return _storage_root() / str(organization_id) / f"{uuid.uuid4().hex}{extension}"


def upload_file(
    *,
    actor: User,
    filename: str,
    data: bytes,
    conversation_id: int | None = None,
) -> UploadResult:
    """يتحقق من الملف ويحفظه ويسجّل بياناته ثم يفهرسه للبحث.

    الترتيب مقصود: التحقق قبل الكتابة، والكتابة قبل التسجيل، والفهرسة أخيرًا.
    فشل الفهرسة **لا يُفشل الرفع**: الملف محفوظ ومسجّل، وتُضبط حالته
    ``failed`` ويُعاد سبب الفشل — يبقى للموظف ملفه ويعرف أنه لن يُبحث فيه.

    Args:
        conversation_id: ربط الملف بمحادثة، ويجب أن يملكها ``actor``.

    Raises:
        FileExtractionError: امتداد غير مدعوم أو حجم يتجاوز الحد.
        ConversationNotFoundError: إذا مُرِّرت محادثة لا يملكها ``actor``.
        FileStorageError: إذا تعذّرت الكتابة على القرص.
    """
    # المحادثة أولًا: لا يُكتب شيء على القرص لطلب سيُرفض أصلًا.
    if conversation_id is not None:
        get_conversation(actor=actor, conversation_id=conversation_id)

    extension = validate_upload(filename, len(data))
    destination = _build_storage_path(
        organization_id=actor.organization_id, extension=extension
    )

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    except OSError as exc:
        raise FileStorageError(
            "تعذّر حفظ الملف على قرص السيرفر. تأكد من صلاحيات الكتابة على "
            f"المجلد «{settings.upload_dir}» ومن توفّر مساحة كافية."
        ) from exc

    store = get_file_store()
    record = store.create_file(
        organization_id=actor.organization_id,
        user_id=actor.id,
        conversation_id=conversation_id,
        original_name=filename,
        storage_path=str(destination),
        mime_type=MIME_BY_EXTENSION.get(extension, "application/octet-stream"),
        size_bytes=len(data),
    )

    chunk_count, indexing_error = _index_for_search(
        file_id=record.id,
        organization_id=actor.organization_id,
        filename=filename,
        data=data,
    )
    status = "processed" if indexing_error is None else "failed"
    record = (
        store.set_status(
            file_id=record.id, organization_id=actor.organization_id, status=status
        )
        or record
    )

    record_for(
        actor,
        action=ACTION_FILE_UPLOADED,
        details=f"رفع الملف «{filename}» ({len(data)} بايت، الحالة {status})",
    )
    return UploadResult(
        file=record, chunk_count=chunk_count, indexing_error=indexing_error
    )


def _index_for_search(
    *, file_id: int, organization_id: int, filename: str, data: bytes
) -> tuple[int, str | None]:
    """يفهرس الملف للبحث المتجهي، ويبتلع أي فشل ويصفه بدل أن يرفعه.

    الفهرسة خدمة إضافية على الرفع لا شرط له: مزود متجهات معطّل أو ملف PDF
    ممسوح ضوئيًا بلا نص يجب ألا يمنع الموظف من حفظ ملفه.
    """
    from .document_service import ingest_document

    try:
        result = ingest_document(
            file_id=file_id,
            organization_id=organization_id,
            filename=filename,
            data=data,
        )
    except FileExtractionError as exc:
        # ملف بلا نص أو تالف: رسالة الاستخراج نفسها مكتوبة للعرض.
        return 0, str(exc)
    except Exception as exc:  # noqa: BLE001 — أي فشل هنا لا يُسقط الرفع
        detail = str(exc).strip()
        return 0, (
            detail
            or "تعذّرت فهرسة الملف للبحث. الملف محفوظ، ولن يظهر في نتائج البحث."
        )
    return result.chunk_count, None


def get_file(*, actor: User, file_id: int) -> FileRecord:
    """يقرأ بيانات ملف **داخل جهة ``actor``**، أيًّا كان رافعه.

    القراءة مشتركة داخل الجهة عمدًا: محتوى الملف متاح لكل موظفيها عبر البحث،
    فحجب بياناته كان يجعل ``sources`` تشير إلى مصدر مجهول لقارئه.

    Raises:
        FileNotFoundInScopeError: إذا لم يوجد أو كان لجهة أخرى.
    """
    record = get_file_store().get_file(
        file_id=file_id, organization_id=actor.organization_id
    )
    if record is None:
        raise FileNotFoundInScopeError("الملف المطلوب غير موجود.")
    return record


def list_files(
    *,
    actor: User,
    uploaded_by: int | None = None,
    conversation_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page:
    """يعيد ملفات جهة ``actor``.

    Args:
        uploaded_by: قصر القائمة على رافع بعينه — تستخدمه الواجهة لعرض
            «ملفاتي» بتمرير معرّف صاحب الطلب.
        conversation_id: قصرها على محادثة **يملكها** ``actor``.
    """
    if conversation_id is not None:
        get_conversation(actor=actor, conversation_id=conversation_id)

    resolved_limit, resolved_offset = resolve_page(limit, offset)
    return get_file_store().list_files(
        organization_id=actor.organization_id,
        uploaded_by=uploaded_by,
        conversation_id=conversation_id,
        limit=resolved_limit,
        offset=resolved_offset,
    )


def delete_file(*, actor: User, file_id: int) -> FileRecord:
    """يحذف ملفًا: سجله ومقاطعه ونسخته على القرص.

    **للرافع أو لمسؤول الجهة فقط.** القراءة مشتركة داخل الجهة، أما إزالة
    معرفة منها فقرارٌ لصاحبها أو لمن يديرها.

    المقاطع تُحذف قبل السجل: مقاطع باقية بعد اختفاء الملف تعني محتوى يظل
    قابلًا للاستشهاد به في ``sources`` من ملف لم يعد موجودًا.

    Raises:
        FileNotFoundInScopeError: إذا لم يوجد أو كان لجهة أخرى.
        FilePermissionError: إذا كان داخل الجهة ولم يكن الطالب رافعه ولا مسؤولها.
    """
    from .retrieval import get_chunk_store

    record = get_file(actor=actor, file_id=file_id)
    if not can_modify(actor=actor, record=record):
        raise FilePermissionError(
            "حذف الملف متاح لرافعه أو لمسؤول الجهة فقط."
        )

    try:
        get_chunk_store().delete_file_chunks(
            file_id=record.id, organization_id=actor.organization_id
        )
    except Exception:  # noqa: BLE001
        # مخزن مقاطع معطّل يجب ألا يمنع الموظف من إزالة ملفه؛ الحذف من
        # القاعدة يزيلها كذلك بـON DELETE CASCADE على fk_chunks_file.
        pass

    get_file_store().delete_file(
        file_id=record.id, organization_id=actor.organization_id
    )

    # النسخة على القرص أخيرًا: سجل بلا ملف أهون من ملف بلا سجل يبقى للأبد.
    try:
        Path(record.storage_path).unlink(missing_ok=True)
    except OSError:
        pass

    record_for(
        actor,
        action=ACTION_FILE_DELETED,
        details=f"حذف الملف «{record.original_name}» رقم {record.id}",
    )
    return record
