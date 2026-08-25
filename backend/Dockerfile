# صورة GovAgent Backend — أبسط صورة تعمل.
# لا تُبنى داخلها أي أسرار: كل الإعدادات تصل من متغيرات البيئة وقت التشغيل.

FROM python:3.12-slim

WORKDIR /app

# طبقة الاعتماديات منفصلة عن الكود حتى لا تُعاد عند كل تعديل بسيط.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# 0.0.0.0 ضرورية داخل الحاوية: 127.0.0.1 لا تُرى من خارجها.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
