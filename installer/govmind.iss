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

; تُمرَّران من build.ps1. القيم هنا احتياطٌ للتشغيل المباشر بـiscc.
#ifndef Channel
  #define Channel "development"
#endif
#ifndef ControlPlaneUrl
  #define ControlPlaneUrl "http://127.0.0.1:8000"
#endif

#define IsDev (Channel == "development")

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
; ⚠️ اسم النسخة يحمل القناة: بناء التطوير يجب أن يُعرف من «إضافة أو إزالة
; البرامج» وحدها، لا بفتح ملف إعداد داخله.
#if IsDev
AppVerName={#AppName} {#AppVersion} (بناء تطوير — غير موقّع)
#else
AppVerName={#AppName} {#AppVersion}
#endif
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

#if IsDev
UninstallDisplayName={#AppName} (بناء تطوير)
#else
UninstallDisplayName={#AppName}
#endif
UninstallDisplayIcon={app}\{#RuntimeExe}

[Languages]
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[CustomMessages]
arabic.LaunchAfterInstall=تشغيل GovMind الآن
arabic.CreateDesktopIcon=إنشاء اختصار على سطح المكتب
arabic.DevBuildNotice=⚠️ هذه نسخة تطوير من GovMind، غير موقّعة رقميًا ولم تُختبر على خدمة حقيقية.%n%nعنوان الخدمة المضبوط فيها: {#ControlPlaneUrl}%n%nلا تُوزَّع هذه النسخة على مستخدمين نهائيين.
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
; ⚠️ **`--open` لا الملف التنفيذي وحده.** الملف بلا وسائط خادمٌ بلا نافذة:
; يبدأ ويحجز منفذًا ويجلس صامتًا، فلا يرى المستخدم شيئًا حين يضغط الاختصار.
; هذا هو العطل الذي ظهر في أول تثبيت فعلي — انظر govmind_runtime\opener.py.
Name: "{group}\{#AppName}"; Filename: "{app}\{#RuntimeExe}"; \
    Parameters: "--open"; Comment: "فتح GovMind"
Name: "{group}\إلغاء تثبيت {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#RuntimeExe}"; \
    Parameters: "--open"; Tasks: desktopicon

[Run]
; ⚠️ `nowait` و `runasoriginaluser`: الخدمة تعمل بحساب المستخدم لا كمسؤول.
; و`postinstall` يجعلها اختيارًا يراه المستخدم لا تشغيلًا صامتًا.
; ⚠️ `--open` كذلك: خانة «تشغيل GovMind الآن» يجب أن **تفتح الواجهة**، لا
; أن تبدأ خدمة صامتة ثم تترك المستخدم أمام شاشة لم يتغيّر فيها شيء.
Filename: "{app}\{#RuntimeExe}"; Parameters: "--open"; \
    Description: "{cm:LaunchAfterInstall}"; \
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
{ تحذير قناة التطوير **قبل** أن يبدأ التثبيت، لا بعده: من يرفض المتابعة
  يجب ألا يكون قد نسخ ملفًا واحدًا إلى جهازه. }
function InitializeSetup(): Boolean;
begin
  Result := True;
#if IsDev
  Result := MsgBox(ExpandConstant('{cm:DevBuildNotice}') + #13#10#13#10 +
                   'هل تريد المتابعة؟',
                   mbConfirmation, MB_YESNO) = IDYES;
#endif
end;

{ ملاحظة للمستخدم عن حجم المودل بعد اكتمال نسخ الملفات. }
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
    if MsgBox('هل تريد حذف ملف المودل وبيانات ربط هذا الجهاز أيضًا؟' + #13#10 +
              'الحذف يعني إعادة تنزيل المودل وإعادة الربط من إضافة المتصفح ' +
              'عند التثبيت مرة أخرى.',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(DataDir, True, True, True);
    end;
  end;
end;
