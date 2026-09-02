# حزم بايثون المجمَّعة داخل GovMind Runtime

الملف التنفيذي `govmind-runtime.exe` يحوي مفسّر بايثون والحزم أدناه.
تُولَّد القائمة من `runtime/requirements.txt` وتُحدَّث معه.

| الحزمة | الرخصة | الغرض |
|---|---|---|
| CPython | PSF License | مفسّر بايثون المجمَّع |
| FastAPI | MIT | الواجهة المحلية على 127.0.0.1 |
| Starlette | BSD-3-Clause | أساس FastAPI |
| Uvicorn | BSD-3-Clause | خادم ASGI |
| Pydantic | MIT | التحقق من صحة الطلبات |
| pydantic-core | MIT | نواة Pydantic |
| httpx | BSD-3-Clause | نداء Backend المستضاف وتنزيل المودل |
| httpcore | BSD-3-Clause | أساس httpx |
| h11 | MIT | تحليل HTTP/1.1 |
| anyio | MIT | التزامن |
| idna | BSD-3-Clause | أسماء النطاقات |
| certifi | MPL-2.0 | شهادات الجذر |
| sniffio | MIT / Apache-2.0 | كشف مكتبة التزامن |
| typing-extensions | PSF License | تلميحات الأنواع |
| annotated-types | MIT | قيود Pydantic |

## التحديث

```powershell
python -m pip install pip-licenses
python -m pip_licenses --format=markdown --with-urls
```

## ملاحظة

كل الرخص أعلاه تسمح بإعادة التوزيع ضمن منتج مغلق المصدر بشرط **إرفاق نصّ
الرخصة والإسناد**. `certifi` بـMPL-2.0: لا تُعدَّل ملفاتها، وإن عُدِّلت
وجب نشر التعديل.
