from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename
import uuid
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized
from flask_dance.consumer.storage.sqla import SQLAlchemyStorage
from dotenv import load_dotenv
import os
import re

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# Allow OAuth2 over HTTP in development only (set OAUTHLIB_INSECURE_TRANSPORT=1 in .env if needed)
# في الإنتاج يجب استخدام HTTPS فقط

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())

# إعدادات قاعدة البيانات
# دعم SQLite للتطوير و PostgreSQL للإنتاج
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # PostgreSQL للإنتاج
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # SQLite للتطوير
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bank_of_ideas.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Google OAuth configuration
app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET')
# SERVER_NAME معطل للإنتاج - يسبب مشاكل مع الوصول من IP خارجي
# app.config['SERVER_NAME'] = os.environ.get('SERVER_NAME', 'localhost:4000')
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_browser_name(user_agent):
    """تحديد اسم المتصفح من User-Agent"""
    if not user_agent:
        return 'Unknown'
    user_agent = user_agent.lower()
    if 'chrome' in user_agent and 'edg' not in user_agent:
        return 'Chrome'
    elif 'firefox' in user_agent:
        return 'Firefox'
    elif 'safari' in user_agent and 'chrome' not in user_agent:
        return 'Safari'
    elif 'edg' in user_agent:
        return 'Edge'
    elif 'opera' in user_agent:
        return 'Opera'
    else:
        return 'Other'

def get_device_type(user_agent):
    """تحديد نوع الجهاز من User-Agent"""
    if not user_agent:
        return 'Unknown'
    user_agent = user_agent.lower()
    if any(mobile in user_agent for mobile in ['mobile', 'android', 'iphone', 'ipad', 'ipod', 'blackberry', 'windows phone']):
        if 'tablet' in user_agent or 'ipad' in user_agent:
            return 'Tablet'
        return 'Mobile'
    return 'Desktop'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=True)  # Made nullable for Google OAuth users
    google_id = db.Column(db.String(120), unique=True, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    profile_picture = db.Column(db.String(200), nullable=True)
    full_name = db.Column(db.String(100), nullable=True)
    location = db.Column(db.String(100), nullable=True)
    website = db.Column(db.String(200), nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ideas = db.relationship('Idea', backref='author', lazy=True)
    comments = db.relationship('Comment', backref='author', lazy=True)

class OAuth(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False)
    provider_user_id = db.Column(db.String(256), nullable=False)
    token = db.Column(db.JSON, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship('User', backref=db.backref('oauth', lazy=True))

class Idea(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    views = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comments = db.relationship('Comment', backref='idea', lazy=True)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    idea_id = db.Column(db.Integer, db.ForeignKey('idea.id'), nullable=False)

class Visit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.Text, nullable=True)
    browser = db.Column(db.String(100), nullable=True)
    device_type = db.Column(db.String(50), nullable=True)  # mobile, desktop, tablet
    page_path = db.Column(db.String(500), nullable=True)
    referrer = db.Column(db.String(500), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('visits', lazy=True))

# Google OAuth blueprint
google_bp = make_google_blueprint(
    client_id=app.config['GOOGLE_OAUTH_CLIENT_ID'],
    client_secret=app.config['GOOGLE_OAUTH_CLIENT_SECRET'],
    scope=[
        'https://www.googleapis.com/auth/userinfo.email',
        'https://www.googleapis.com/auth/userinfo.profile',
        'openid'
    ],
    storage=SQLAlchemyStorage(OAuth, db.session, user=current_user)
)
app.register_blueprint(google_bp, url_prefix='/login')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    if not token:
        flash('فشل تسجيل الدخول باستخدام Google', 'danger')
        return False

    resp = google.get('/oauth2/v2/userinfo')
    if not resp.ok:
        flash('فشل في الحصول على معلومات المستخدم من Google', 'danger')
        return False

    google_info = resp.json()
    google_id = google_info['id']
    email = google_info['email']
    username = email.split('@')[0]  # Use email username as default username

    # Check if user exists
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        # Check if email exists
        user = User.query.filter_by(email=email).first()
        if user:
            # Update existing user with Google ID
            user.google_id = google_id
        else:
            # Create new user
            user = User(
                username=username,
                email=email,
                google_id=google_id
            )
            db.session.add(user)
            db.session.commit()

    login_user(user)
    flash('تم تسجيل الدخول بنجاح باستخدام Google!', 'success')
    return False

# Routes
@app.before_request
def log_visit():
    """تسجيل الزيارات تلقائياً قبل كل طلب"""
    # تجنب تسجيل الزيارات لملفات static
    if request.path.startswith('/static'):
        return
    
    # تجنب تسجيل زيارات dashboard
    if request.path.startswith('/dashboard'):
        return
    
    # تجنب تسجيل زيارات الأدمن (صفحات الإدارة)
    if request.path.startswith('/admin'):
        return
    
    # تجنب تسجيل زيارات الأدمن (إذا كان المستخدم الحالي أدمن)
    if current_user.is_authenticated and current_user.is_admin:
        return
    
    # الحصول على IP Address
    ip_address = request.remote_addr
    if request.headers.get('X-Forwarded-For'):
        ip_address = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    
    # الحصول على User-Agent
    user_agent = request.headers.get('User-Agent', '')
    
    # تحديد المتصفح والجهاز
    browser = get_browser_name(user_agent)
    device_type = get_device_type(user_agent)
    
    # الحصول على المسار والمرجع
    page_path = request.path
    referrer = request.headers.get('Referer', '')
    
    # الحصول على معرف المستخدم إذا كان مسجل دخول
    user_id = current_user.id if current_user.is_authenticated else None
    
    # تسجيل الزيارة
    visit = Visit(
        ip_address=ip_address,
        user_agent=user_agent,
        browser=browser,
        device_type=device_type,
        page_path=page_path,
        referrer=referrer,
        user_id=user_id
    )
    db.session.add(visit)
    db.session.commit()

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/most-viewed')
def most_viewed():
    try:
        ideas = Idea.query.order_by(Idea.views.desc()).all()
        return render_template('most_viewed.html', ideas=ideas)
    except Exception as e:
        print(f"Error in most_viewed route: {str(e)}")
        return render_template('most_viewed.html', ideas=[])

@app.route('/latest')
def latest_ideas():
    try:
        ideas = Idea.query.order_by(Idea.created_at.desc()).all()
        return render_template('latest_ideas.html', ideas=ideas)
    except Exception as e:
        print(f"Error in latest_ideas route: {str(e)}")
        return render_template('latest_ideas.html', ideas=[])

@app.route('/most-commented')
def most_commented():
    try:
        ideas = db.session.query(Idea, db.func.count(Comment.id).label('comment_count'))\
            .join(Comment)\
            .group_by(Idea.id)\
            .order_by(db.desc('comment_count'))\
            .all()
        ideas = [idea for idea, _ in ideas]
        return render_template('most_commented.html', ideas=ideas)
    except Exception as e:
        print(f"Error in most_commented route: {str(e)}")
        return render_template('most_commented.html', ideas=[])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('تم تسجيل الدخول بنجاح!', 'success')
            return redirect(url_for('home'))
        else:
            flash('البريد الإلكتروني أو كلمة المرور غير صحيحة', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('كلمات المرور غير متطابقة', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash('اسم المستخدم موجود بالفعل', 'danger')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('البريد الإلكتروني موجود بالفعل', 'danger')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('تم إنشاء الحساب بنجاح! يمكنك الآن تسجيل الدخول', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('home'))

@app.route('/submit_idea', methods=['GET', 'POST'])
@login_required
def submit_idea():
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        category = request.form.get('category')
        
        new_idea = Idea(
            title=title,
            description=description,
            category=category,
            user_id=current_user.id
        )
        
        db.session.add(new_idea)
        db.session.commit()
        
        flash('تم نشر الفكرة بنجاح!', 'success')
        return redirect(url_for('home'))
    
    return render_template('submit_idea.html')

@app.route('/idea/<int:idea_id>')
def view_idea(idea_id):
    idea = Idea.query.get_or_404(idea_id)
    # زيادة عدد المشاهدات
    idea.views += 1
    db.session.commit()
    
    # جلب جميع التعليقات (لصاحب الفكرة يمكنه رؤية غير المنشورة)
    all_comments = idea.comments
    if current_user.is_authenticated and current_user.id == idea.user_id:
        # صاحب الفكرة يرى جميع التعليقات
        comments = all_comments
    else:
        # الآخرون يرون فقط المنشورة
        comments = [c for c in all_comments if c.is_published]
    
    return render_template('view_idea.html', idea=idea, comments=comments)

@app.route('/idea/<int:idea_id>/comment', methods=['POST'])
@login_required
def add_comment(idea_id):
    idea = Idea.query.get_or_404(idea_id)
    content = request.form.get('content')
    
    if content:
        comment = Comment(
            content=content,
            user_id=current_user.id,
            idea_id=idea.id
        )
        db.session.add(comment)
        db.session.commit()
        flash('تم إضافة التعليق بنجاح!', 'success')
    else:
        flash('يرجى كتابة تعليق', 'danger')
    
    return redirect(url_for('view_idea', idea_id=idea_id))

@app.route('/comment/<int:comment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    
    # التحقق من أن المستخدم هو صاحب التعليق
    if comment.user_id != current_user.id:
        flash('ليس لديك صلاحية لتعديل هذا التعليق', 'danger')
        return redirect(url_for('view_idea', idea_id=comment.idea_id))
    
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            comment.content = content
            comment.updated_at = datetime.utcnow()
            db.session.commit()
            flash('تم تحديث التعليق بنجاح!', 'success')
            return redirect(url_for('view_idea', idea_id=comment.idea_id))
        else:
            flash('يرجى كتابة تعليق', 'danger')
    
    return render_template('edit_comment.html', comment=comment)

@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    idea_id = comment.idea_id
    
    # التحقق من أن المستخدم هو صاحب التعليق
    if comment.user_id != current_user.id:
        flash('ليس لديك صلاحية لحذف هذا التعليق', 'danger')
        return redirect(url_for('view_idea', idea_id=idea_id))
    
    db.session.delete(comment)
    db.session.commit()
    flash('تم حذف التعليق بنجاح!', 'success')
    return redirect(url_for('view_idea', idea_id=idea_id))

@app.route('/comment/<int:comment_id>/toggle-publish', methods=['POST'])
@login_required
def toggle_comment_publish(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    idea = Idea.query.get_or_404(comment.idea_id)
    
    # التحقق من أن المستخدم هو صاحب الفكرة
    if idea.user_id != current_user.id:
        flash('ليس لديك صلاحية لتعديل حالة هذا التعليق', 'danger')
        return redirect(url_for('view_idea', idea_id=idea.id))
    
    comment.is_published = not comment.is_published
    db.session.commit()
    
    status = 'نشر' if comment.is_published else 'إخفاء'
    flash(f'تم {status} التعليق بنجاح!', 'success')
    return redirect(url_for('view_idea', idea_id=idea.id))


@app.route('/dashboard')
@login_required
def dashboard():
    # التحقق من أن المستخدم هو أدمن
    if not current_user.is_admin:
        flash('ليس لديك صلاحية للوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('home'))
    
    # الإحصائيات العامة
    total_users = User.query.count()
    total_ideas = Idea.query.count()
    total_comments = Comment.query.count()
    total_visits = Visit.query.count()
    
    # الزيارات اليوم
    today = datetime.utcnow().date()
    visits_today = Visit.query.filter(Visit.created_at >= today).count()
    
    # الزيارات هذا الأسبوع
    week_ago = datetime.utcnow() - timedelta(days=7)
    visits_this_week = Visit.query.filter(Visit.created_at >= week_ago).count()
    
    # الزيارات هذا الشهر
    month_ago = datetime.utcnow() - timedelta(days=30)
    visits_this_month = Visit.query.filter(Visit.created_at >= month_ago).count()
    
    # الإحصائيات حسب المتصفح
    browser_stats = db.session.query(
        Visit.browser, 
        db.func.count(Visit.id).label('count')
    ).group_by(Visit.browser).all()
    
    # الإحصائيات حسب نوع الجهاز
    device_stats = db.session.query(
        Visit.device_type, 
        db.func.count(Visit.id).label('count')
    ).group_by(Visit.device_type).all()
    
    # Pagination للزيارات
    page = request.args.get('page', 1, type=int)
    per_page = 20
    visits_pagination = Visit.query.order_by(Visit.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    recent_visits = visits_pagination.items
    
    # أكثر الصفحات زيارة
    popular_pages = db.session.query(
        Visit.page_path,
        db.func.count(Visit.id).label('count')
    ).group_by(Visit.page_path).order_by(db.func.count(Visit.id).desc()).limit(10).all()
    
    # IPs الفريدة
    unique_ips = db.session.query(db.func.count(db.func.distinct(Visit.ip_address))).scalar()
    
    # المستخدمون الجدد هذا الشهر
    new_users_month = User.query.filter(User.created_at >= month_ago).count()
    
    # الأفكار الجديدة هذا الشهر
    new_ideas_month = Idea.query.filter(Idea.created_at >= month_ago).count()
    
    return render_template('dashboard.html',
                         total_users=total_users,
                         total_ideas=total_ideas,
                         total_comments=total_comments,
                         total_visits=total_visits,
                         visits_today=visits_today,
                         visits_this_week=visits_this_week,
                         visits_this_month=visits_this_month,
                         browser_stats=browser_stats,
                         device_stats=device_stats,
                         recent_visits=recent_visits,
                         visits_pagination=visits_pagination,
                         popular_pages=popular_pages,
                         unique_ips=unique_ips,
                         new_users_month=new_users_month,
                         new_ideas_month=new_ideas_month)

@app.route('/profile')
@login_required
def profile():
    user = current_user
    user_ideas = Idea.query.filter_by(user_id=user.id).order_by(Idea.created_at.desc()).all()
    return render_template('profile.html', user=user, ideas=user_ideas)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        user = current_user
        
        # تحديث المعلومات الأساسية
        user.full_name = request.form.get('full_name', '')
        user.bio = request.form.get('bio', '')
        user.location = request.form.get('location', '')
        user.website = request.form.get('website', '')
        
        # معالجة رفع الصورة
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename != '' and allowed_file(file.filename):
                # حذف الصورة القديمة إن وجدت
                if user.profile_picture:
                    old_file_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_picture)
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                
                # حفظ الصورة الجديدة
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4()}_{filename}"
                upload_path = os.path.join(app.config['UPLOAD_FOLDER'])
                os.makedirs(upload_path, exist_ok=True)
                file.save(os.path.join(upload_path, unique_filename))
                user.profile_picture = unique_filename
        
        db.session.commit()
        flash('تم تحديث البروفايل بنجاح!', 'success')
        return redirect(url_for('profile'))
    
    return render_template('edit_profile.html', user=current_user)

@app.route('/admin/users')
@login_required
def admin_users():
    # التحقق من أن المستخدم هو أدمن
    if not current_user.is_admin:
        flash('ليس لديك صلاحية للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('home'))
    
    # جلب جميع المستخدمين مع إحصائياتهم
    users = User.query.all()
    users_data = []
    for user in users:
        ideas_count = Idea.query.filter_by(user_id=user.id).count()
        comments_count = Comment.query.filter_by(user_id=user.id).count()
        visits_count = Visit.query.filter_by(user_id=user.id).count()
        
        users_data.append({
            'user': user,
            'ideas_count': ideas_count,
            'comments_count': comments_count,
            'visits_count': visits_count
        })
    
    return render_template('admin_users.html', users_data=users_data)

@app.route('/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
def toggle_user_admin(user_id):
    # التحقق من أن المستخدم هو أدمن
    if not current_user.is_admin:
        flash('ليس لديك صلاحية للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('home'))
    
    # منع المستخدم من تغيير صلاحياته بنفسه
    if user_id == current_user.id:
        flash('لا يمكنك تغيير صلاحياتك بنفسك', 'danger')
        return redirect(url_for('admin_users'))
    
    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    db.session.commit()
    
    status = 'أدمن' if user.is_admin else 'مستخدم عادي'
    flash(f'تم تغيير صلاحيات المستخدم {user.username} إلى {status} بنجاح!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    # التحقق من أن المستخدم هو أدمن
    if not current_user.is_admin:
        flash('ليس لديك صلاحية للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        # تحديث المعلومات الأساسية
        user.username = request.form.get('username', user.username)
        user.email = request.form.get('email', user.email)
        user.full_name = request.form.get('full_name', '')
        user.bio = request.form.get('bio', '')
        user.location = request.form.get('location', '')
        user.website = request.form.get('website', '')
        
        # تحديث كلمة المرور إذا تم إدخالها
        new_password = request.form.get('password', '')
        if new_password:
            user.password = generate_password_hash(new_password)
        
        # تحديث صلاحيات الأدمن
        is_admin = request.form.get('is_admin') == 'on'
        if user_id != current_user.id:  # منع تغيير صلاحيات نفسه
            user.is_admin = is_admin
        
        # معالجة رفع الصورة
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename and allowed_file(file.filename):
                # حذف الصورة القديمة إن وجدت
                if user.profile_picture:
                    old_file_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_picture)
                    if os.path.exists(old_file_path):
                        os.remove(old_file_path)
                
                # حفظ الصورة الجديدة
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4()}_{filename}"
                upload_path = os.path.join(app.config['UPLOAD_FOLDER'])
                os.makedirs(upload_path, exist_ok=True)
                file.save(os.path.join(upload_path, unique_filename))
                user.profile_picture = unique_filename
        
        db.session.commit()
        flash('تم تحديث معلومات المستخدم بنجاح!', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin_edit_user.html', user=user)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    # التحقق من أن المستخدم هو أدمن
    if not current_user.is_admin:
        flash('ليس لديك صلاحية للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        full_name = request.form.get('full_name', '').strip()
        bio = request.form.get('bio', '').strip()
        location = request.form.get('location', '').strip()
        website = request.form.get('website', '').strip()
        is_admin = request.form.get('is_admin') == 'on'
        
        # التحقق من البيانات المطلوبة
        if not username or not email or not password:
            flash('يرجى إدخال اسم المستخدم والبريد الإلكتروني وكلمة المرور', 'danger')
            return redirect(url_for('add_user'))
        
        # التحقق من عدم وجود مستخدم بنفس الاسم أو البريد
        if User.query.filter_by(username=username).first():
            flash('اسم المستخدم موجود بالفعل', 'danger')
            return redirect(url_for('add_user'))
        
        if User.query.filter_by(email=email).first():
            flash('البريد الإلكتروني موجود بالفعل', 'danger')
            return redirect(url_for('add_user'))
        
        # إنشاء المستخدم الجديد
        hashed_password = generate_password_hash(password)
        new_user = User(
            username=username,
            email=email,
            password=hashed_password,
            full_name=full_name,
            bio=bio,
            location=location,
            website=website,
            is_admin=is_admin
        )
        
        # معالجة رفع الصورة
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4()}_{filename}"
                upload_path = os.path.join(app.config['UPLOAD_FOLDER'])
                os.makedirs(upload_path, exist_ok=True)
                file.save(os.path.join(upload_path, unique_filename))
                new_user.profile_picture = unique_filename
        
        db.session.add(new_user)
        db.session.commit()
        
        flash(f'تم إضافة المستخدم {username} بنجاح!', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin_add_user.html')

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@login_required
def delete_user(user_id):
    # التحقق من أن المستخدم هو أدمن
    if not current_user.is_admin:
        flash('ليس لديك صلاحية للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('home'))
    
    # منع المستخدم من حذف نفسه
    if user_id == current_user.id:
        flash('لا يمكنك حذف حسابك بنفسك', 'danger')
        return redirect(url_for('admin_users'))
    
    user = User.query.get_or_404(user_id)
    username = user.username
    
    # حذف جميع الأفكار والتعليقات والزيارات المرتبطة بالمستخدم
    Idea.query.filter_by(user_id=user.id).delete()
    Comment.query.filter_by(user_id=user.id).delete()
    Visit.query.filter_by(user_id=user.id).delete()
    
    # حذف الصورة الشخصية إن وجدت
    if user.profile_picture:
        old_file_path = os.path.join(app.config['UPLOAD_FOLDER'], user.profile_picture)
        if os.path.exists(old_file_path):
            os.remove(old_file_path)
    
    # حذف المستخدم
    db.session.delete(user)
    db.session.commit()
    
    flash(f'تم حذف المستخدم {username} بنجاح!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    with app.app_context():
        # إنشاء الجداول إذا لم تكن موجودة
        db.create_all()
        # إنشاء مجلد رفع الملفات
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        
        # تفعيل المستخدم abdelwahied كأدمن
        admin_user = User.query.filter_by(email='abdelwahied@gmail.com').first()
        if admin_user:
            admin_user.is_admin = True
            db.session.commit()
            print(f"تم تفعيل المستخدم {admin_user.username} كأدمن بنجاح!")
        else:
            print("لم يتم العثور على المستخدم abdelwahied@gmail.com")
    
    # استخدام 0.0.0.0 للسماح بالوصول من خارج الحاوية (مطلوب في Docker)
    host = '0.0.0.0'
    debug = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug, host=host, port=4000) 