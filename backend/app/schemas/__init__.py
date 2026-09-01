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
from .entitlements import (
    AccountLoginRequest,
    AccountOut,
    AccountSessionResponse,
    ActiveDeviceOut,
    DeviceActivateRequest,
    DeviceListResponse,
    DeviceVerifyRequest,
    InstallerDownloadRequest,
    InstallerDownloadResponse,
    SubscriptionStatusResponse,
)
from .runtime import (
    InstallationSessionResponse,
    ModelArtifactResponse,
    RuntimeActivateRequest,
    RuntimeActivationResponse,
    RuntimeEntitlementResponse,
)
from .chat import (
    ChatMessageIn,
    ChatRequest,
    ChatResponse,
    ChatSource,
    DependencyHealth,
    HealthResponse,
    OracleHealth,
)

__all__ = [
    # الحساب والاشتراك وتفعيل الجهاز وتحميل المثبّت
    "AccountLoginRequest",
    "AccountOut",
    "AccountSessionResponse",
    "ActiveDeviceOut",
    "DeviceActivateRequest",
    "DeviceListResponse",
    "DeviceVerifyRequest",
    "InstallerDownloadRequest",
    "InstallerDownloadResponse",
    "SubscriptionStatusResponse",
    # الـRuntime وجلسات التركيب
    "InstallationSessionResponse",
    "ModelArtifactResponse",
    "RuntimeActivateRequest",
    "RuntimeActivationResponse",
    "RuntimeEntitlementResponse",
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
    "DependencyHealth",
    "HealthResponse",
    "OracleHealth",
]
