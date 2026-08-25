"""الواجهة المشتركة لجميع مزودي المودل."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

#: أدوار الرسائل داخل سياق المحادثة. تعليمات النظام تُمرَّر منفصلة في
#: system_prompt ولا تُكتب كرسالة بدور "system" هنا.
MessageRole = Literal["user", "assistant"]


class ModelProviderError(Exception):
    """خطأ صادر من مزود المودل (اتصال، إعدادات ناقصة، مهلة، رد غير صالح).

    رسالة هذا الخطأ تصل إلى المستخدم كما هي في رد 503، لذلك تُكتب دائمًا
    بالعربية وبصياغة مفهومة لموظف غير تقني.
    """


@dataclass(frozen=True)
class ChatMessage:
    """رسالة واحدة داخل سياق المحادثة."""

    role: MessageRole
    content: str


@dataclass
class ChatResult:
    """نتيجة استدعاء المودل."""

    reply: str
    provider: str


def ensure_conversation(messages: Iterable[ChatMessage]) -> list[ChatMessage]:
    """يتحقق من صحة سياق المحادثة ويعيده كقائمة جاهزة للإرسال.

    يستدعيها كل مزود في أول سطر من generate حتى تكون رسالة الخطأ موحّدة.

    Raises:
        ModelProviderError: إذا كان السياق فارغًا أو لا ينتهي برسالة مستخدم.
    """
    conversation = list(messages or [])
    if not conversation:
        raise ModelProviderError(
            "سياق المحادثة فارغ: لا توجد رسالة لإرسالها إلى المودل."
        )
    if conversation[-1].role != "user":
        raise ModelProviderError(
            "سياق المحادثة غير صالح: آخر رسالة يجب أن تكون من المستخدم."
        )
    return conversation


class ModelProvider(ABC):
    """كل مزود مودل (mock / oracle / local) ينفذ هذه الواجهة.

    الهدف: يستطيع باقي النظام استدعاء المودل دون معرفة أي مزود يعمل خلفه،
    ويمكن تبديل المزود من متغير البيئة MODEL_PROVIDER فقط.
    """

    #: اسم المزود كما يظهر في الإعدادات والسجلات.
    name: str = "base"

    @abstractmethod
    def generate(
        self, messages: list[ChatMessage], system_prompt: str
    ) -> ChatResult:
        """يستقبل سياق المحادثة كاملًا ويعيد رد المودل.

        Args:
            messages: رسائل المحادثة بالترتيب الزمني، آخرها رسالة المستخدم
                الحالية. الرسائل السابقة تُمرَّر كسياق حتى يفهم المودل ما
                سبق دون إعادة شرحه.
            system_prompt: تعليمات النظام التي تحدد دور الإيجنت.

        Raises:
            ModelProviderError: إذا فشل الاستدعاء.
        """
        raise NotImplementedError
