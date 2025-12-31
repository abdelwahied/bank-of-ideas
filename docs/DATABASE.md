# دليل قاعدة البيانات - Database Guide

## 📊 نظرة عامة

يدعم التطبيق نوعين من قواعد البيانات:
- **SQLite**: للتطوير والاختبار (افتراضي)
- **PostgreSQL**: للإنتاج والاستخدام الفعلي

## 🔧 التطوير (Development)

### SQLite (افتراضي)

SQLite هو الخيار الافتراضي للتطوير. لا يحتاج أي إعداد إضافي:

```bash
# التطبيق يستخدم SQLite تلقائياً
python3 app.py
```

**المميزات:**
- لا يحتاج إعداد
- سريع وسهل
- مناسب للتطوير

**العيوب:**
- غير مناسب للإنتاج
- لا يدعم الوصول المتزامن بشكل جيد
- محدود في الأداء

## 🚀 الإنتاج (Production)

### PostgreSQL (موصى به)

PostgreSQL هو الخيار الموصى به للإنتاج.

#### 1. التثبيت

**على Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

**على macOS:**
```bash
brew install postgresql
brew services start postgresql
```

**على Windows:**
قم بتحميل PostgreSQL من [الموقع الرسمي](https://www.postgresql.org/download/)

#### 2. إنشاء قاعدة البيانات

```bash
# الدخول إلى PostgreSQL
sudo -u postgres psql

# إنشاء قاعدة بيانات
CREATE DATABASE bank_of_ideas;

# إنشاء مستخدم
CREATE USER bank_user WITH PASSWORD 'your_secure_password';

# منح الصلاحيات
GRANT ALL PRIVILEGES ON DATABASE bank_of_ideas TO bank_user;

# الخروج
\q
```

#### 3. إعداد متغيرات البيئة

أنشئ ملف `.env` في جذر المشروع:

```bash
# .env
DATABASE_URL=postgresql://bank_user:your_secure_password@localhost:5432/bank_of_ideas
SECRET_KEY=your-very-secure-secret-key-here
FLASK_ENV=production
```

#### 4. تثبيت PostgreSQL Driver

```bash
pip install psycopg2-binary
```

#### 5. تشغيل التطبيق

```bash
python3 app.py
```

## 🐳 Docker (PostgreSQL)

### استخدام Docker Compose

`docker-compose.yml` يتضمن PostgreSQL تلقائياً:

```bash
# تشغيل التطبيق مع PostgreSQL
docker-compose up --build
```

**ما يتم إعداده تلقائياً:**
- حاوية PostgreSQL
- قاعدة بيانات `bank_of_ideas`
- مستخدم `bank_user`
- كلمة مرور `bank_password`
- Volume لحفظ البيانات

### تخصيص إعدادات قاعدة البيانات

عدّل `docker-compose.yml`:

```yaml
services:
  db:
    environment:
      - POSTGRES_DB=your_database_name
      - POSTGRES_USER=your_username
      - POSTGRES_PASSWORD=your_secure_password
```

## 📦 Migration قاعدة البيانات

### إنشاء الجداول

عند أول تشغيل، يتم إنشاء الجداول تلقائياً:

```python
# في app.py
db.create_all()
```

### للبيئات الإنتاجية

**استخدام Flask-Migrate (موصى به):**

```bash
# تثبيت Flask-Migrate
pip install Flask-Migrate

# تهيئة Migration
flask db init

# إنشاء Migration
flask db migrate -m "Initial migration"

# تطبيق Migration
flask db upgrade
```

## 🔄 نسخ البيانات من SQLite إلى PostgreSQL

### الطريقة الأولى: استخدام SQLAlchemy

```python
# migrate_data.py
from app import app, db
from app import User, Idea, Comment, Visit
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# SQLite source
sqlite_engine = create_engine('sqlite:///bank_of_ideas.db')
SqliteSession = sessionmaker(bind=sqlite_engine)
sqlite_session = SqliteSession()

# PostgreSQL destination
pg_engine = create_engine('postgresql://user:pass@localhost/db')
PgSession = sessionmaker(bind=pg_engine)
pg_session = PgSession()

# نسخ البيانات
with app.app_context():
    # نسخ المستخدمين
    for user in sqlite_session.query(User).all():
        pg_session.merge(user)
    
    # نسخ الأفكار
    for idea in sqlite_session.query(Idea).all():
        pg_session.merge(idea)
    
    # نسخ التعليقات
    for comment in sqlite_session.query(Comment).all():
        pg_session.merge(comment)
    
    # نسخ الزيارات
    for visit in sqlite_session.query(Visit).all():
        pg_session.merge(visit)
    
    pg_session.commit()
```

### الطريقة الثانية: استخدام pgloader

```bash
# تثبيت pgloader
sudo apt install pgloader  # Ubuntu/Debian
brew install pgloader       # macOS

# نسخ البيانات
pgloader sqlite:///path/to/bank_of_ideas.db postgresql://user:pass@localhost/db
```

## 🔐 الأمان

### كلمات المرور

**⚠️ مهم جداً:**
- استخدم كلمات مرور قوية لقاعدة البيانات
- لا تضع كلمات المرور في الكود
- استخدم متغيرات البيئة أو ملف `.env`
- لا ترفع ملف `.env` إلى Git

### الاتصال الآمن

**للاتصال الآمن في الإنتاج:**
```python
# استخدام SSL
DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require
```

## 📊 الصيانة

### Backup قاعدة البيانات

**PostgreSQL:**
```bash
# Backup
pg_dump -U bank_user bank_of_ideas > backup.sql

# Restore
psql -U bank_user bank_of_ideas < backup.sql
```

**SQLite:**
```bash
# Backup
cp bank_of_ideas.db backup.db
```

### تنظيف قاعدة البيانات

```sql
-- حذف الزيارات القديمة (أكثر من 90 يوم)
DELETE FROM visit WHERE created_at < NOW() - INTERVAL '90 days';

-- حذف التعليقات غير المنشورة القديمة
DELETE FROM comment WHERE is_published = false AND created_at < NOW() - INTERVAL '30 days';
```

## 🐛 استكشاف الأخطاء

### مشكلة الاتصال

```python
# التحقق من الاتصال
from app import db
with app.app_context():
    db.engine.connect()
```

### مشكلة الصلاحيات

```sql
-- التحقق من الصلاحيات
\du

-- منح الصلاحيات
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bank_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bank_user;
```

### مشكلة Migration

```bash
# إعادة تهيئة Migration
flask db init --directory migrations

# إنشاء Migration جديد
flask db migrate -m "Description"
```

## 📚 موارد إضافية

- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Flask-Migrate Documentation](https://flask-migrate.readthedocs.io/)

---

**آخر تحديث**: ديسمبر 2025

