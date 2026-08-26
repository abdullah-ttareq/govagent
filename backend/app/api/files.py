"""مسارات رفع الملفات وقراءة بياناتها وحذفها.

**سياسة الصلاحيات:** القراءة داخل الجهة لكل موظفيها، والحذف لرافع الملف
أو لمسؤول الجهة، وأي موظف من جهة أخرى يعود **404 بلا تسريب**.

القراءة مشتركة داخل الجهة عمدًا: محتوى الملفات متاح لكل موظفيها عبر
البحث المتجهي، فحجب بياناتها كان يجعل `sources` تشير إلى مصدر لا يعرف
قارئ الرد ما هو. الشرح في `services/file_service.py`.

اسم الملف الذي يرسله الموظف لا يُستخدم في مسار القرص إطلاقًا — انظر
`services/file_service.py`.
"""

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from ..schemas import FileListResponse, FileOut, FileUploadResponse, PageMeta
from ..services.conversation_service import ConversationNotFoundError
from ..services.conversation_store import Page
from ..services.file_service import (
    FileNotFoundInScopeError,
    FilePermissionError,
    FileStorageError,
    can_modify,
    delete_file,
    get_file,
    list_files,
    upload_file,
)
from ..services.file_store import FileRecord
from ..services.user_store import User
from ..services.text_extraction import (
    SUPPORTED_EXTENSIONS,
    FileExtractionError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from .dependencies import CurrentUser

router = APIRouter(prefix="/api/files", tags=["files"])

_UNAUTHORIZED = {"description": "رمز الدخول مفقود أو غير صالح"}

#: 422 و 413 كأرقام لا كثوابت status: أسماء Starlette لهما تغيّرت
#: (UNPROCESSABLE_ENTITY ← UNPROCESSABLE_CONTENT) والاسم القديم صار
#: يطلق تحذير إهمال، بينما الأسماء الجديدة غير موجودة في النسخ التي
#: يسمح بها requirements.txt. الرقم ثابت عبر النسخ كلها.


def _to_file_out(record: FileRecord, viewer: User) -> FileOut:
    """يحوّل السجل إلى رد، بما يراه هذا الموظف تحديدًا."""
    is_uploader = record.user_id == viewer.id
    return FileOut(
        id=record.id,
        original_name=record.original_name,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        status=record.status,
        uploaded_by=record.user_id,
        can_modify=can_modify(actor=viewer, record=record),
        # الارتباط بمحادثة يظهر لرافع الملف وحده: المحادثة خاصة
        # بصاحبها، وكشف ارتباط ملف بها يكشف طرفًا من خصوصيتها.
        conversation_id=record.conversation_id if is_uploader else None,
        created_at=record.created_at,
    )


def _page_meta(page: Page) -> PageMeta:
    return PageMeta(total=page.total, limit=page.limit, offset=page.offset)


@router.post(
    "",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="رفع ملف",
    responses={
        401: _UNAUTHORIZED,
        404: {"description": "المحادثة المرتبطة غير موجودة لصاحب الرمز"},
        413: {"description": "حجم الملف يتجاوز الحد المسموح"},
        415: {"description": "صيغة الملف غير مدعومة"},
        422: {"description": "الملف فارغ أو بلا اسم"},
    },
)
async def add_file(
    user: CurrentUser,
    file: UploadFile = File(..., description="الملف المراد رفعه"),
    conversation_id: int | None = Form(
        None, description="ربط الملف بمحادثة يملكها صاحب الرمز (اختياري)"
    ),
) -> FileUploadResponse:
    """يرفع ملفًا ويحفظه ويفهرسه للبحث في محادثات الجهة.

    الصيغ المدعومة: `.pdf` و `.docx` و `.txt`، والحد الأقصى من
    `UPLOAD_MAX_BYTES` (١٠ ميجابايت افتراضيًا). التجاوز يعيد **413**
    والصيغة غير المدعومة **415**، ولكل منهما رسالة عربية تشرح السبب والحل.

    **فشل الفهرسة لا يُفشل الرفع:** الملف يُحفظ وتُضبط حالته `failed` ويُعاد
    سبب الفشل في `indexing_error`. مزود متجهات معطّل أو ملف PDF ممسوح ضوئيًا
    بلا نص يجب ألا يضيّع على الموظف ملفه.
    """
    if not file.filename:
        raise HTTPException(
            status_code=422,
            detail=(
                "لم يصل اسم الملف مع الطلب، فتعذّر تحديد نوعه. "
                f"الصيغ المدعومة: {'، '.join(SUPPORTED_EXTENSIONS)}."
            ),
        )

    data = await file.read()

    try:
        result = upload_file(
            actor=user,
            filename=file.filename,
            data=data,
            conversation_id=conversation_id,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=413, detail=str(exc)
        ) from exc
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except FileExtractionError as exc:
        # يبقى: الملف الفارغ. خطأ في المُدخَل لا في نوعه ولا في حجمه.
        raise HTTPException(
            status_code=422, detail=str(exc)
        ) from exc
    except FileStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return FileUploadResponse(
        file=_to_file_out(result.file, user),
        chunk_count=result.chunk_count,
        indexing_error=result.indexing_error,
    )


@router.get(
    "",
    response_model=FileListResponse,
    summary="قائمة ملفات الموظف",
    responses={401: _UNAUTHORIZED, 404: {"description": "المحادثة غير موجودة"}},
)
def read_files(
    user: CurrentUser,
    uploaded_by: int | None = Query(
        None,
        description="قصر القائمة على ملفات رافع بعينه — مرّر معرّفك لعرض «ملفاتي»",
    ),
    conversation_id: int | None = Query(
        None, description="قصر القائمة على ملفات محادثة يملكها صاحب الرمز"
    ),
    limit: int | None = Query(None, ge=1, description="عدد الملفات في الصفحة"),
    offset: int | None = Query(None, ge=0, description="عدد الملفات المتجاوَزة"),
) -> FileListResponse:
    """يعيد ملفات **الجهة** من الأحدث.

    الملفات معرفةٌ مشتركة داخل الجهة، فتظهر ملفات الزملاء كذلك. لعرض
    ملفاتك وحدها مرّر `uploaded_by` بمعرّفك من `/api/auth/me`.
    """
    try:
        page = list_files(
            actor=user,
            uploaded_by=uploaded_by,
            conversation_id=conversation_id,
            limit=limit,
            offset=offset,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    return FileListResponse(
        files=[_to_file_out(item, user) for item in page.items],
        page=_page_meta(page),
    )


@router.get(
    "/{file_id}",
    response_model=FileOut,
    summary="قراءة بيانات ملف",
    responses={
        401: _UNAUTHORIZED,
        404: {"description": "الملف غير موجود في جهة صاحب الرمز"},
    },
)
def read_file(file_id: int, user: CurrentUser) -> FileOut:
    """يعيد بيانات ملف **داخل جهة صاحب الرمز**، أيًّا كان رافعه.

    هذا ما يجعل كل مصدر يظهر في `sources` قابلًا للاستعلام عنه: محتوى
    الملف متاح للجهة عبر البحث، فبياناته كذلك.
    """
    try:
        return _to_file_out(get_file(actor=user, file_id=file_id), user)
    except FileNotFoundInScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{file_id}",
    response_model=FileOut,
    summary="حذف ملف",
    responses={
        401: _UNAUTHORIZED,
        403: {"description": "الحذف متاح لرافع الملف أو لمسؤول الجهة"},
        404: {"description": "الملف غير موجود في جهة صاحب الرمز"},
    },
)
def remove_file(file_id: int, user: CurrentUser) -> FileOut:
    """يحذف ملفًا: سجله ومقاطعه في البحث ونسخته على القرص.

    **لرافع الملف أو لمسؤول الجهة فقط.** القراءة مشتركة داخل الجهة، أما
    إزالة معرفة منها فقرارٌ لصاحبها أو لمن يديرها.

    **حذف فعلي لا تعطيل**، بخلاف حسابات الموظفين: بعد الحذف لا يعود
    الملف يظهر في `sources` إطلاقًا.
    """
    try:
        return _to_file_out(delete_file(actor=user, file_id=file_id), user)
    except FileNotFoundInScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except FilePermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
