"""منطق المحادثة — يفصل الـRoutes عن مزود المودل وعن البحث المتجهي."""

from collections.abc import Sequence

from ..ai import ChatMessage, get_model_provider
from ..ai.system_prompt import build_system_prompt
from ..schemas import ChatMessageIn, ChatResponse, ChatSource
from .model_settings_service import resolve_provider_name
from .rag_service import retrieve_context


def send_message(
    message: str,
    history: Sequence[ChatMessageIn] | None = None,
    organization_id: int | None = None,
) -> ChatResponse:
    """يمرر رسالة الموظف مع سياق المحادثة وملفات جهته إلى المزود المفعّل.

    Args:
        message: نص الرسالة الحالية.
        history: الرسائل السابقة بالترتيب الزمني، أو None لمحادثة جديدة.
        organization_id: جهة الموظف، **مأخوذة من رمز الدخول** في
            `api/chat.py` لا من جسم الطلب. بدونها لا يجري أي بحث في الملفات
            إطلاقًا، ويجيب الإيجنت من معرفته العامة، ويُستخدم المزود
            الافتراضي. ومعها يُستخدم مزود الجهة إن اختارت واحدًا (P2-04).

    مسار الملفات **اختياري بالكامل**: بلا جهة، أو بلا ملفات مرفوعة، أو مع
    قاعدة بيانات غير مضبوطة، تمضي المحادثة كما كانت قبل الـRAG تمامًا.

    لاحقًا (مهمة P2-03) يُحفظ السياق في قاعدة البيانات بدل استقباله من العميل.
    """
    conversation = [
        ChatMessage(role=item.role, content=item.content) for item in (history or [])
    ]
    conversation.append(ChatMessage(role="user", content=message))

    outcome = (
        retrieve_context(question=message, organization_id=organization_id)
        if organization_id is not None
        else None
    )
    context = outcome.context if outcome else ""

    # مزود الجهة إن اختارت واحدًا، وإلا فـMODEL_PROVIDER (تعيد None).
    provider = get_model_provider(resolve_provider_name(organization_id))
    result = provider.generate(
        messages=conversation,
        system_prompt=build_system_prompt(context),
    )

    sources = [
        ChatSource(
            file_id=chunk.file_id,
            file_name=chunk.file_name,
            chunk_index=chunk.chunk_index,
            score=round(chunk.score, 4),
        )
        for chunk in (outcome.chunks if outcome else [])
    ]
    return ChatResponse(reply=result.reply, provider=result.provider, sources=sources)
