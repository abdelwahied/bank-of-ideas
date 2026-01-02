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

# تشغيل التطبيق باستخدام Gunicorn للإنتاج
# --timeout 300: زيادة timeout للصفحات الثقيلة مثل Dashboard
# --workers 4: عدد العمال (processes)
# --bind 0.0.0.0:4000: الاستماع على جميع الـ interfaces
# --log-level debug: مستوى logging تفصيلي
# --access-logfile -: طباعة access logs إلى stdout
# --error-logfile -: طباعة error logs إلى stderr
CMD ["gunicorn", "--timeout", "300", "--workers", "4", "--bind", "0.0.0.0:4000", "--log-level", "debug", "--access-logfile", "-", "--error-logfile", "-", "app:app"]

