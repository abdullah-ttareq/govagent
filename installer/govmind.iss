; ============================================================================
; GovMind — مثبّت ويندوز (Inno Setup 6)
;
; يُبنى بـ:  iscc installer\govmind.iss
; والأفضل عبر:  powershell -ExecutionPolicy Bypass -File installer\build.ps1
;
; ----------------------------------------------------------------------------
; ما يحزمه هذا المثبّت
; ----------------------------------------------------------------------------
;   * govmind-runtime.exe      — الخدمة المحلية (بايثون مجمَّعة بالكامل)
;   * llama.cpp\*              — محرّك المودل الرسمي (رخصة MIT)
;   * ui\*                     — واجهة GovMind الثابتة (تصدير Next.js)
;   * govmind.config.json      — عنوان Backend المستضاف. **قيمة عامة لا سرّ.**
;   * licenses\*               — تراخيص الأطراف الثالثة وشروط Gemma
;
; ⚠️ **لا يحزم ملف المودل** (نحو ٥٫٣ ج.ب): يُنزَّل بعد التفعيل من مدوّنة
; Azure منفصلة، ويُتحقَّق منه بـSHA-256 قبل اعتماده. حزمه هنا يجعل كل
; تحديث صغير في البرنامج يعيد تنزيله كاملًا.
;
; ⚠️ **لا يحزم أي سرّ**: لا مفتاح Supabase الخدمي، ولا سلسلة اتصال Azure،
; ولا مِلح تجزئة الأجهزة. كلها تبقى على Backend المستضاف.
;
; ----------------------------------------------------------------------------
; التوقيع
; ----------------------------------------------------------------------------
; هذا المثبّت **غير موقّع** في هذه المرحلة. ويندوز سيعرض SmartScreen بعبارة
; «ناشر غير معروف» (Unknown publisher)، وهو سلوك صحيح لملف غير موقّع.
;
; **لا يُلتفّ على ذلك ولا يُطلب من العميل تعطيل الحماية.** الحلّ الوحيد
; المقبول شهادة Code Signing — انظر installer\README.md.
; ============================================================================

#define AppName "GovMind"
#define AppNameAr "جوَف مايند"
#define AppVersion "1.0.0"
#define AppPublisher "GovMind"
#define RuntimeExe "govmind-runtime.exe"

; مجلد التجهيز الذي يبنيه build.ps1. لا يُودَع في المستودع.
#define StageDir "staging"

[Setup]
AppId={{7C3E2F51-9A64-4E7B-9F2D-1B8A6C4D5E30}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=output
OutputBaseFilename=GovMindSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; ⚠️ **التثبيت لكل الأجهزة (per-machine).** هوية الجهاز في %ProgramData%
; ويجب أن يجدها الـRuntime أيًّا كان الحساب الذي يشغّله. هذا يستدعي رفع
; الصلاحيات، وويندوز سيعرض نافذة UAC — **وهذا مقصود ولا يُتجاوَز**.
PrivilegesRequired=admin

; عربي أولًا: الواجهة كلها عربية RTL.
ShowLanguageDialog=no

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; ٦٥٠ م.ب تقريبًا بعد فكّ الضغط (المحرّك + الواجهة + المفسّر).
; **لا تشمل المودل** الذي يُنزَّل لاحقًا — رسالة المساحة في الـRuntime تذكره.
ExtraDiskSpaceRequired=52428800

UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#RuntimeExe}

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[CustomMessages]
arabic.LaunchAfterInstall=تشغيل GovMind الآن
arabic.CreateDesktopIcon=إنشاء اختصار على سطح المكتب
arabic.ModelNotice=سيُنزَّل ملف المودل (نحو ٥٫٣ ج.ب) بعد تفعيل الجهاز من إضافة المتصفح. تأكد من وجود مساحة كافية واتصال بالإنترنت.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "اختصارات:"; Flags: unchecked

[Files]
; الخدمة المحلية — بايثون مجمَّعة داخلها، فلا يحتاج العميل تثبيت بايثون.
Source: "{#StageDir}\{#RuntimeExe}"; DestDir: "{app}"; Flags: ignoreversion

; محرّك المودل الرسمي وكل مكتباته.
Source: "{#StageDir}\llama.cpp\*"; DestDir: "{app}\llama.cpp"; Flags: ignoreversion recursesubdirs createallsubdirs

; واجهة GovMind — تصدير ساكن، فلا يحتاج العميل Node.js.
Source: "{#StageDir}\ui\*"; DestDir: "{app}\ui"; Flags: ignoreversion recursesubdirs createallsubdirs

; إعداد عام: عنوان Backend المستضاف وحده. **لا أسرار.**
Source: "{#StageDir}\govmind.config.json"; DestDir: "{app}"; Flags: ignoreversion

; التراخيص — إلزامية للتوزيع. انظر installer\licenses\README.md.
Source: "{#StageDir}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; مجلد بيانات الجهاز: الهوية والمودل والسجلّات.
; صلاحيات كاملة للمستخدمين حتى يعمل الـRuntime بحساب المستخدم كذلك.
Name: "{commonappdata}\{#AppName}"; Permissions: users-modify
Name: "{commonappdata}\{#AppName}\models"; Permissions: users-modify
Name: "{commonappdata}\{#AppName}\logs"; Permissions: users-modify

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#RuntimeExe}"; Comment: "فتح GovMind"
Name: "{group}\إلغاء تثبيت {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#RuntimeExe}"; Tasks: desktopicon

[Run]
; ⚠️ `nowait` و `runasoriginaluser`: الخدمة تعمل بحساب المستخدم لا كمسؤول.
; و`postinstall` يجعلها اختيارًا يراه المستخدم لا تشغيلًا صامتًا.
Filename: "{app}\{#RuntimeExe}"; Description: "{cm:LaunchAfterInstall}"; \
    Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
; إيقاف الخدمة قبل حذف ملفاتها، وإلا بقي الملف التنفيذي محجوزًا.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#RuntimeExe}"; \
    Flags: runhidden; RunOnceId: "StopGovMindRuntime"

[UninstallDelete]
; السجلّات ورمز الجلسة يُحذفان. **هوية الجهاز والمودل يبقيان** عمدًا:
; إعادة التثبيت فوق تثبيت قائم يجب ألا تُبطل التفعيل ولا تعيد تنزيل
; خمسة جيجابايت. حذفهما نهائيًا في القسم أدناه عند إلغاء التثبيت الكامل.
Type: filesandordirs; Name: "{commonappdata}\{#AppName}\logs"
Type: files; Name: "{commonappdata}\{#AppName}\session.txt"

[Code]
{ ملاحظة للمستخدم عن حجم المودل قبل أن يبدأ التثبيت. }
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MsgBox(ExpandConstant('{cm:ModelNotice}'), mbInformation, MB_OK);
  end;
end;

{ إلغاء التثبيت: يسأل عن حذف المودل والهوية بدل أن يقرّر عن المستخدم. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{commonappdata}\{#AppName}');
    if MsgBox('هل تريد حذف ملف المودل وبيانات تفعيل هذا الجهاز أيضًا؟' + #13#10 +
              'الحذف يعني إعادة تنزيل المودل وإعادة التفعيل عند التثبيت مرة أخرى، ' +
              'وقد يحتاج التفعيل الجديد إلغاء تفعيل الجهاز السابق من مسؤول النظام.',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(DataDir, True, True, True);
    end;
  end;
end;
