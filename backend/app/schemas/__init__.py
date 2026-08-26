"""نماذج الطلبات والردود (Pydantic)."""

from .auth import LoginRequest, LogoutResponse, TokenResponse, UserOut
from .directory import (
    OrganizationCreatedResponse,
    OrganizationCreateRequest,
    OrganizationOut,
    OrganizationUpdateRequest,
    UserCreateRequest,
    UserListResponse,
    UserUpdateRequest,
)
from .workspace import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationOut,
    ConversationRenameRequest,
    FileListResponse,
    FileOut,
    FileUploadResponse,
    MessageListResponse,
    MessageOut,
    PageMeta,
)
from .errors import ErrorResponse, FieldError
from .governance import (
    AuditEventOut,
    AuditListResponse,
    ModelSettingsOut,
    ModelSettingsUpdateRequest,
    SubscriptionOut,
    SubscriptionUpdateRequest,
)
from .chat import (
    ChatMessageIn,
    ChatRequest,
    ChatResponse,
    ChatSource,
    HealthResponse,
    OracleHealth,
)

__all__ = [
    # المصادقة
    "LoginRequest",
    "LogoutResponse",
    "TokenResponse",
    "UserOut",
    # الجهات والمستخدمون
    "OrganizationCreateRequest",
    "OrganizationCreatedResponse",
    "OrganizationOut",
    "OrganizationUpdateRequest",
    "UserCreateRequest",
    "UserListResponse",
    "UserUpdateRequest",
    # المحادثات والرسائل والملفات
    "ConversationCreateRequest",
    "ConversationListResponse",
    "ConversationOut",
    "ConversationRenameRequest",
    "FileListResponse",
    "FileOut",
    "FileUploadResponse",
    "MessageListResponse",
    "MessageOut",
    "PageMeta",
    # الأخطاء
    "ErrorResponse",
    "FieldError",
    # الاشتراك وإعدادات المودل وسجل التدقيق
    "AuditEventOut",
    "AuditListResponse",
    "ModelSettingsOut",
    "ModelSettingsUpdateRequest",
    "SubscriptionOut",
    "SubscriptionUpdateRequest",
    # المحادثة
    "ChatMessageIn",
    "ChatRequest",
    "ChatResponse",
    "ChatSource",
    "HealthResponse",
    "OracleHealth",
]
