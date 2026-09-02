# صورة GovMind Frontend — أبسط صورة تعمل.

FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# ⚠️ متغيرات NEXT_PUBLIC_* تُدمج في ملفات الواجهة وقت البناء لا وقت التشغيل،
# لذلك تصل كـARG من docker-compose. تغييرها يستلزم إعادة بناء الصورة.
# القيمة الافتراضية localhost لأن المتصفح هو من يتصل بالـBackend، لا الحاوية.
ARG NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL

RUN npm run build

EXPOSE 3000

CMD ["npm", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
