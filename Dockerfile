# استخدام Python 3.12 كصورة أساسية
FROM python:3.12-slim

# تعيين مجلد العمل
WORKDIR /app

# نسخ ملف المتطلبات
COPY requirements.txt .

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

# إنشاء مجلد uploads إذا لم يكن موجوداً
RUN mkdir -p static/uploads

# تعيين متغيرات البيئة
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# فتح المنفذ
EXPOSE 4000

# تشغيل التطبيق
CMD ["python", "app.py"]

