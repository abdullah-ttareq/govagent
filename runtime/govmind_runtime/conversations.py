"""محادثات محفوظة **في تخزين يملكه الـRuntime**، لا في المتصفح.

**لماذا لا `localStorage`؟** ثلاثة أسباب، كلها أعطال حقيقية لا تفضيلات:

1. **يموت بلا سبب مفهوم.** مسحُ بيانات الموقع، أو نافذة خاصة، أو متصفح آخر
   — وتذهب محادثات الموظف كلها بلا إنذار. الملفات هنا تعيش بعمر التثبيت.
2. **لا يُفصل بالحساب.** المخزن مرتبط بالأصل (`127.0.0.1:8765`) وهو واحد
   لكل من يفتح الجهاز. حسابان على حاسب واحد كانا سيريان محادثات بعضهما.
3. **يُقرأ بأدوات المطوّر.** محتوى المحادثات بيانات عمل قد تكون حساسة،
   وإبقاؤها في مخزن يقرؤه أي سكربت في الصفحة يوسّع سطح التسريب بلا داعٍ.

**الفصل بالحساب.** كل حساب مجلدٌ باسم تجزئة بريده، لا بالبريد نفسه: اسم
الملف يظهر في مستكشف الملفات وفي أي سجلّ نسخ احتياطي، ولا داعي لأن يحمل
هوية أحد. والتجزئة كافية للفصل لأن الغرض تفريق لا إخفاء.

⚠️ **لا يُخزَّن هنا بيان اعتماد ولا رمز ولا سرّ** — نصوص المحادثة وعناوينها
وتواريخها فقط.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: أقصى عدد رسائل محفوظة في محادثة واحدة. محادثةٌ بلا سقف تجعل ملفًا واحدًا
#: ينمو بلا حدّ ويبطئ كل فتح للتطبيق.
MAX_MESSAGES = 500

#: أقصى طول عنوان مشتقّ. أطول من ذلك يُقصّ فلا يكسر الشريط الجانبي.
TITLE_MAX = 40

#: عنوان محادثة لم يكتب فيها المستخدم شيئًا بعد.
UNTITLED = "محادثة جديدة"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def derive_title(text: str) -> str:
    """عنوان عربي من أول رسالة للمستخدم.

    **لا يُنادى مودل لتوليده.** عنوانٌ من المودل يعني طلبًا مدفوعًا إضافيًا
    لكل محادثة جديدة، وانتظارًا قبل ظهور السطر في الشريط. وأول سطر من كلام
    المستخدم يصف محادثته وصفًا كافيًا في الغالب الأعمّ.
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return UNTITLED
    # يُقصّ عند حدّ كلمة لا في منتصفها: «ما هي أهم ثلاث نق…» تُقرأ أسوأ من
    # «ما هي أهم ثلاث…».
    if len(cleaned) <= TITLE_MAX:
        return cleaned
    cut = cleaned[:TITLE_MAX]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip("،.:؛") + "…"


def account_key(email: str | None) -> str:
    """مفتاح مجلد الحساب: تجزئة البريد، أو ``anonymous`` قبل الربط.

    ⚠️ **البريد لا يصير اسم ملف.** أسماء الملفات تظهر في النسخ الاحتياطي
    وفي أي سجلّ يمرّ على المجلد، ولا حاجة لأن تحمل هوية صاحبها.
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        return "anonymous"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


@dataclass
class Message:
    role: str
    content: str
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }


@dataclass
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[Message] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """ما يحتاجه الشريط الجانبي — **بلا نصوص الرسائل**.

        إرسال كل الرسائل مع كل قائمة يجعل فتح التطبيق ينقل ميجابايتات بلا
        أن يعرضها أحد.
        """
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "messages": [m.to_dict() for m in self.messages],
        }


class ConversationStore:
    """محادثات حساب واحد في ملف JSON واحد داخل مجلد بيانات الـRuntime."""

    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir) / "conversations"
        self._lock = threading.Lock()

    def _path(self, email: str | None) -> Path:
        return self._root / f"{account_key(email)}.json"

    # -- قراءة وكتابة الملف ---------------------------------------------
    def _read(self, email: str | None) -> list[Conversation]:
        path = self._path(email)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # ⚠️ **ملف تالف لا يُسقط التطبيق.** يُسجَّل ويُعامَل كفارغ؛
            # فقدُ سجلّ المحادثات مزعج، وشاشةٌ بيضاء أسوأ.
            logger.warning("تعذّرت قراءة سجلّ المحادثات؛ سيُبدأ سجلّ جديد.")
            return []
        out: list[Conversation] = []
        for item in raw if isinstance(raw, list) else []:
            try:
                out.append(
                    Conversation(
                        id=str(item["id"]),
                        title=str(item.get("title") or UNTITLED),
                        created_at=str(item.get("created_at") or _now()),
                        updated_at=str(item.get("updated_at") or _now()),
                        messages=[
                            Message(
                                role=str(m["role"]),
                                content=str(m["content"]),
                                created_at=str(m.get("created_at") or _now()),
                            )
                            for m in item.get("messages", [])
                            if m.get("role") in ("user", "assistant")
                        ],
                    )
                )
            except (KeyError, TypeError):
                continue
        return out

    def _write(self, email: str | None, items: list[Conversation]) -> None:
        path = self._path(email)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [c.to_dict() for c in items], ensure_ascii=False, indent=2
        )
        # كتابة إلى ملف مؤقّت ثم استبدال: انقطاعُ كهرباء في منتصف الكتابة
        # كان سيترك ملفًا مبتورًا يفقد السجلّ كله.
        temp = path.with_suffix(".tmp")
        temp.write_text(payload, encoding="utf-8")
        temp.replace(path)

    # -- العمليات ---------------------------------------------------------
    def list(self, email: str | None) -> list[dict[str, Any]]:
        """ملخّصات المحادثات، **الأحدث أولًا**."""
        with self._lock:
            items = self._read(email)
        items.sort(key=lambda c: c.updated_at, reverse=True)
        return [c.summary() for c in items]

    def get(self, email: str | None, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            for c in self._read(email):
                if c.id == conversation_id:
                    return c.to_dict()
        return None

    def create(self, email: str | None) -> dict[str, Any]:
        moment = _now()
        conversation = Conversation(
            id=uuid.uuid4().hex, title=UNTITLED, created_at=moment, updated_at=moment
        )
        with self._lock:
            items = self._read(email)
            items.append(conversation)
            self._write(email, items)
        return conversation.to_dict()

    def delete(self, email: str | None, conversation_id: str) -> bool:
        with self._lock:
            items = self._read(email)
            remaining = [c for c in items if c.id != conversation_id]
            if len(remaining) == len(items):
                return False
            self._write(email, remaining)
        return True

    def append(
        self,
        email: str | None,
        conversation_id: str,
        *,
        user_message: str,
        assistant_message: str,
    ) -> dict[str, Any] | None:
        """يضيف دورًا كاملًا، **ويشتقّ العنوان من أول رسالة مستخدم**."""
        with self._lock:
            items = self._read(email)
            target = next((c for c in items if c.id == conversation_id), None)
            if target is None:
                return None
            first_turn = not target.messages
            target.messages.append(Message(role="user", content=user_message))
            target.messages.append(
                Message(role="assistant", content=assistant_message)
            )
            # السقف يُطبَّق بإسقاط الأقدم: الأحدث هو ما يقرؤه المستخدم.
            if len(target.messages) > MAX_MESSAGES:
                target.messages = target.messages[-MAX_MESSAGES:]
            if first_turn or target.title == UNTITLED:
                target.title = derive_title(user_message)
            target.updated_at = _now()
            self._write(email, items)
            return target.to_dict()
