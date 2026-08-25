"""الواجهة المشتركة لجميع مزودي المودل."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ModelProviderError(Exception):
    """خطأ صادر من مزود المودل (اتصال، إعدادات ناقصة، رد غير صالح)."""


@dataclass
class ChatResult:
    """نتيجة استدعاء المودل."""

    reply: str
    provider: str


class ModelProvider(ABC):
    """كل مزود مودل (mock / oracle / local) ينفذ هذه الواجهة.

    الهدف: يستطيع باقي النظام استدعاء المودل دون معرفة أي مزود يعمل خلفه،
    ويمكن تبديل المزود من متغير البيئة MODEL_PROVIDER فقط.
    """

    #: اسم المزود كما يظهر في الإعدادات والسجلات.
    name: str = "base"

    @abstractmethod
    def generate(self, message: str, system_prompt: str) -> ChatResult:
        """يستقبل رسالة المستخدم ويعيد رد المودل.

        Args:
            message: نص رسالة الموظف.
            system_prompt: تعليمات النظام التي تحدد دور الإيجنت.

        Raises:
            ModelProviderError: إذا فشل الاستدعاء.
        """
        raise NotImplementedError
