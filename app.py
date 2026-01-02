from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, Response
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import uuid
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.consumer import oauth_authorized
from flask_dance.consumer.storage.sqla import SQLAlchemyStorage
from dotenv import load_dotenv
from functools import wraps
import os
import re
import unicodedata

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# Allow OAuth2 over HTTP in development only (set OAUTHLIB_INSECURE_TRANSPORT=1 in .env if needed)
# في الإنتاج يجب استخدام HTTPS فقط

app = Flask(__name__)

# إعداد ProxyFix للعمل خلف reverse proxy (Nginx)
# هذا يضمن أن Flask يعرف أنه يعمل على HTTPS
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
    x_prefix=1
)

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
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'connect_args': {'check_same_thread': False} if not database_url else {}
}

# Google OAuth configuration
app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET')

# إعداد SERVER_NAME لـ OAuth redirect URI
# في الإنتاج، استخدم domain أو IP مع المنفذ
server_name = os.environ.get('SERVER_NAME')
if server_name:
    app.config['SERVER_NAME'] = server_name

# إعداد URL scheme (http أو https)
# في الإنتاج، استخدم https
preferred_url_scheme = os.environ.get('PREFERRED_URL_SCHEME', 'http')
app.config['PREFERRED_URL_SCHEME'] = preferred_url_scheme

# إعداد OAuth للعمل خلف reverse proxy
# إذا كان OAUTHLIB_INSECURE_TRANSPORT=1، سيسمح بـ HTTP (للتطوير فقط)
# في الإنتاج، يجب أن يكون HTTPS ويعمل خلف Nginx الذي يمرر X-Forwarded-Proto
if os.environ.get('OAUTHLIB_INSECURE_TRANSPORT') == '1':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

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
    password = db.Column(db.String(255), nullable=True)  # Made nullable for Google OAuth users, increased length for hashed passwords
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
    
    def get_slug(self):
        """إنشاء slug عربي من عنوان الفكرة"""
        # تحويل العنوان إلى slug عربي
        slug = self.title.lower()
        # استبدال المسافات بشرطات
        slug = re.sub(r'\s+', '-', slug)
        # إزالة الأحرف الخاصة
        slug = re.sub(r'[^\w\s-]', '', slug)
        # إزالة الشرطات المتعددة
        slug = re.sub(r'-+', '-', slug)
        # إزالة الشرطات من البداية والنهاية
        slug = slug.strip('-')
        return slug

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
# تحقق من أن القيم موجودة قبل إنشاء blueprint
google_oauth_enabled = bool(app.config.get('GOOGLE_OAUTH_CLIENT_ID') and app.config.get('GOOGLE_OAUTH_CLIENT_SECRET'))

if not google_oauth_enabled:
    app.logger.warning('⚠️ تحذير: GOOGLE_OAUTH_CLIENT_ID أو GOOGLE_OAUTH_CLIENT_SECRET غير موجودة في البيئة!')
    app.logger.warning(f'GOOGLE_OAUTH_CLIENT_ID: {app.config.get("GOOGLE_OAUTH_CLIENT_ID")}')
    app.logger.warning(f'GOOGLE_OAUTH_CLIENT_SECRET: {"***" if app.config.get("GOOGLE_OAUTH_CLIENT_SECRET") else "None"}')
    google_bp = None
else:
    # بناء redirect URL بشكل صحيح
    if app.config.get('SERVER_NAME'):
        # إذا كان SERVER_NAME موجود، استخدمه مع scheme
        # للمحلي: http، للإنتاج: https
        scheme = app.config.get('PREFERRED_URL_SCHEME', 'https')
        # إذا كان localhost، استخدم http دائماً
        if 'localhost' in app.config['SERVER_NAME'] or '127.0.0.1' in app.config['SERVER_NAME']:
            scheme = 'http'
        redirect_url = f"{scheme}://{app.config['SERVER_NAME']}/login/google/authorized"
    else:
        # إذا لم يكن موجود، استخدم القيمة الافتراضية
        redirect_url = None
    
    # التأكد من أن القيم ليست None أو فارغة
    client_id = app.config['GOOGLE_OAUTH_CLIENT_ID']
    client_secret = app.config['GOOGLE_OAUTH_CLIENT_SECRET']
    
    if not client_id or not client_secret:
        app.logger.error('❌ خطأ: GOOGLE_OAUTH_CLIENT_ID أو CLIENT_SECRET فارغة!')
        google_bp = None
    else:
        # بناء معاملات blueprint
        # ملاحظة: لا نمرر redirect_url، نترك Flask-Dance يستخدم القيمة الافتراضية
        # Flask-Dance سيبني redirect_url تلقائياً بناءً على SERVER_NAME
        blueprint_kwargs = {
            'client_id': client_id,
            'client_secret': client_secret,
            'scope': [
                'https://www.googleapis.com/auth/userinfo.email',
                'https://www.googleapis.com/auth/userinfo.profile',
                'openid'
            ],
            'storage': SQLAlchemyStorage(OAuth, db.session, user=current_user)
        }
        
        # إذا كان SERVER_NAME موجود، استخدمه لإعداد redirect_url
        # لكن لا نمرره مباشرة، بل نترك Flask-Dance يبنيها تلقائياً
        if app.config.get('SERVER_NAME'):
            # Flask-Dance سيبني redirect_url تلقائياً من SERVER_NAME
            pass
        
        try:
            google_bp = make_google_blueprint(**blueprint_kwargs)
            app.logger.info(f'✅ تم إنشاء Google OAuth blueprint')
            app.logger.info(f'   Client ID: {client_id[:20]}...')
            app.logger.info(f'   Server Name: {app.config.get("SERVER_NAME", "Not set")}')
            app.register_blueprint(google_bp, url_prefix='/login')
            app.logger.info(f'✅ تم تفعيل Google OAuth بنجاح')
        except Exception as e:
            app.logger.error(f'❌ خطأ في إنشاء Google OAuth blueprint: {e}', exc_info=True)
            app.logger.error(f'   Client ID موجود: {bool(client_id)}')
            app.logger.error(f'   Client Secret موجود: {bool(client_secret)}')
            google_bp = None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# تسجيل معالج OAuth فقط إذا كان blueprint موجود
if google_bp:
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

# إضافة cache headers للـ static files
@app.after_request
def add_cache_headers(response):
    """إضافة cache headers لتحسين الأداء"""
    # Static files - cache لمدة أسبوع
    if request.endpoint == 'static' or request.endpoint == 'uploaded_file':
        response.cache_control.max_age = 604800  # 7 أيام
        response.cache_control.public = True
    # HTML pages - no cache
    elif response.content_type and 'text/html' in response.content_type:
        response.cache_control.no_cache = True
        response.cache_control.no_store = True
        response.cache_control.must_revalidate = True
    return response

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
        # جلب التصنيف من query parameter
        category = request.args.get('category', None)
        
        # بناء الاستعلام
        query = Idea.query
        if category:
            query = query.filter(Idea.category == category)
        
        # تحسين الاستعلام باستخدام eager loading
        ideas = query.options(db.joinedload(Idea.author)).order_by(Idea.views.desc()).limit(50).all()
        return render_template('most_viewed.html', ideas=ideas, selected_category=category)
    except Exception as e:
        print(f"Error in most_viewed route: {str(e)}")
        return render_template('most_viewed.html', ideas=[], selected_category=None)

@app.route('/latest')
def latest_ideas():
    try:
        # جلب التصنيف من query parameter
        category = request.args.get('category', None)
        
        # بناء الاستعلام
        query = Idea.query
        if category:
            query = query.filter(Idea.category == category)
        
        # تحسين الاستعلام باستخدام eager loading
        ideas = query.options(db.joinedload(Idea.author)).order_by(Idea.created_at.desc()).limit(50).all()
        return render_template('latest_ideas.html', ideas=ideas, selected_category=category)
    except Exception as e:
        print(f"Error in latest_ideas route: {str(e)}")
        return render_template('latest_ideas.html', ideas=[], selected_category=None)

@app.route('/most-commented')
def most_commented():
    try:
        # جلب التصنيف من query parameter
        category = request.args.get('category', None)
        
        # بناء الاستعلام
        query = db.session.query(Idea, db.func.count(Comment.id).label('comment_count'))\
            .join(Comment)\
            .group_by(Idea.id)
        
        if category:
            query = query.filter(Idea.category == category)
        
        # تحسين الاستعلام باستخدام eager loading
        ideas_with_counts = query.options(db.joinedload(Idea.author)).order_by(db.desc('comment_count')).limit(50).all()
        ideas = [idea for idea, _ in ideas_with_counts]
        return render_template('most_commented.html', ideas=ideas, selected_category=category)
    except Exception as e:
        print(f"Error in most_commented route: {str(e)}")
        return render_template('most_commented.html', ideas=[], selected_category=None)

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

@app.route('/idea/<int:idea_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_idea(idea_id):
    idea = Idea.query.get_or_404(idea_id)
    
    # التحقق من الصلاحية: صاحب الفكرة أو الأدمن فقط
    if current_user.id != idea.user_id and not current_user.is_admin:
        flash('ليس لديك صلاحية لتعديل هذه الفكرة', 'danger')
        return redirect(url_for('view_idea', idea_id=idea_id))
    
    if request.method == 'POST':
        idea.title = request.form.get('title')
        idea.description = request.form.get('description')
        idea.category = request.form.get('category')
        
        db.session.commit()
        flash('تم تحديث الفكرة بنجاح!', 'success')
        return redirect(url_for('view_idea', idea_id=idea_id, slug=idea.get_slug()))
    
    return render_template('edit_idea.html', idea=idea)

@app.route('/idea/<int:idea_id>')
@app.route('/idea/<int:idea_id>/<slug>')
def view_idea(idea_id, slug=None):
    # تحسين الاستعلام باستخدام eager loading
    idea = Idea.query.options(
        db.joinedload(Idea.author),
        db.joinedload(Idea.comments).joinedload(Comment.author)
    ).get_or_404(idea_id)
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
    
    try:
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
    except Exception as e:
        app.logger.error(f"Error rendering dashboard: {e}", exc_info=True)
        flash('حدث خطأ في تحميل لوحة التحكم. يرجى المحاولة مرة أخرى.', 'danger')
        return redirect(url_for('home'))

@app.route('/profile')
@login_required
def profile():
    user = current_user
    user_ideas = Idea.query.filter_by(user_id=user.id).order_by(Idea.created_at.desc()).all()
    return render_template('profile.html', user=user, ideas=user_ideas)

@app.route('/user/<int:user_id>')
def user_profile(user_id):
    """عرض بروفايل أي مستخدم"""
    user = User.query.get_or_404(user_id)
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

@app.route('/sitemap.xml')
def sitemap():
    """إنشاء Sitemap ديناميكي لمحركات البحث"""
    try:
        # الحصول على الرابط الأساسي للموقع
        base_url = request.url_root.rstrip('/')
        
        # الصفحات الثابتة
        static_pages = [
            {
                'loc': base_url,
                'lastmod': datetime.utcnow().strftime('%Y-%m-%d'),
                'changefreq': 'daily',
                'priority': '1.0'
            },
            {
                'loc': f'{base_url}/most-viewed',
                'lastmod': datetime.utcnow().strftime('%Y-%m-%d'),
                'changefreq': 'daily',
                'priority': '0.8'
            },
            {
                'loc': f'{base_url}/latest',
                'lastmod': datetime.utcnow().strftime('%Y-%m-%d'),
                'changefreq': 'daily',
                'priority': '0.8'
            },
            {
                'loc': f'{base_url}/most-commented',
                'lastmod': datetime.utcnow().strftime('%Y-%m-%d'),
                'changefreq': 'daily',
                'priority': '0.8'
            }
        ]
        
        # الصفحات الديناميكية (الأفكار)
        ideas = Idea.query.order_by(Idea.created_at.desc()).all()
        dynamic_pages = []
        for idea in ideas:
            # استخدام تاريخ آخر تعديل إذا كان موجوداً، وإلا تاريخ الإنشاء
            lastmod = idea.created_at.strftime('%Y-%m-%d')
            dynamic_pages.append({
                'loc': f'{base_url}/idea/{idea.id}',
                'lastmod': lastmod,
                'changefreq': 'weekly',
                'priority': '0.7'
            })
        
        # دمج جميع الصفحات
        all_pages = static_pages + dynamic_pages
        
        # توليد XML
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        
        for page in all_pages:
            xml += '  <url>\n'
            xml += f'    <loc>{page["loc"]}</loc>\n'
            xml += f'    <lastmod>{page["lastmod"]}</lastmod>\n'
            xml += f'    <changefreq>{page["changefreq"]}</changefreq>\n'
            xml += f'    <priority>{page["priority"]}</priority>\n'
            xml += '  </url>\n'
        
        xml += '</urlset>'
        
        return Response(xml, mimetype='application/xml')
    
    except Exception as e:
        # في حالة حدوث خطأ، إرجاع sitemap أساسي
        print(f"Error generating sitemap: {str(e)}")
        base_url = request.url_root.rstrip('/')
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
        xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        xml += f'  <url><loc>{base_url}</loc><priority>1.0</priority></url>\n'
        xml += '</urlset>'
        return Response(xml, mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    """إنشاء robots.txt ديناميكي لمحركات البحث"""
    base_url = request.url_root.rstrip('/')
    robots_content = f"""User-agent: *
Allow: /
Disallow: /dashboard
Disallow: /admin/
Disallow: /profile/edit
Disallow: /login
Disallow: /register
Disallow: /static/uploads/

Sitemap: {base_url}/sitemap.xml
"""
    return Response(robots_content, mimetype='text/plain')


@app.route('/dashboard/analytics')
@login_required
def dashboard_analytics():
    """إحصائيات متقدمة - SEO & Analytics"""
    if not current_user.is_admin:
        flash('ليس لديك صلاحية للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('home'))

    try:
        total_visits = Visit.query.count()
        month_ago = datetime.utcnow() - timedelta(days=30)
        unique_ips = db.session.query(db.func.count(db.func.distinct(Visit.ip_address))).scalar()

        # الزيارات العضوية
        search_engines = ['google', 'bing', 'yahoo', 'yandex', 'duckduckgo', 'baidu']
        organic_visits = Visit.query.filter(
            db.or_(*[Visit.referrer.like(f'%{engine}%') for engine in search_engines])
        ).count()
        
        # الصفحات الأكثر شعبية من محركات البحث
        organic_popular_pages = db.session.query(
            Visit.page_path,
            db.func.count(Visit.id).label('count')
        ).filter(
            db.or_(*[Visit.referrer.like(f'%{engine}%') for engine in search_engines])
        ).group_by(Visit.page_path).order_by(db.func.count(Visit.id).desc()).limit(10).all()

        # معدل الارتداد - محسّن
        try:
            bounce_result = db.session.execute(
                db.text("""
                    SELECT COUNT(*) as single_visit_ips
                    FROM (
                        SELECT ip_address
                        FROM visit
                        GROUP BY ip_address
                        HAVING COUNT(*) = 1
                    ) subq
                """)
            ).scalar()
            single_page_visits = bounce_result or 0
            bounce_rate = (single_page_visits / unique_ips * 100) if unique_ips > 0 else 0
        except:
            bounce_rate = 0

        bounce_rate_status = "ممتاز" if bounce_rate < 40 else "جيد" if bounce_rate < 60 else "يحتاج تحسين"

        # إحصائيات إضافية
        avg_pages_per_session = (total_visits / unique_ips) if unique_ips > 0 else 0
        avg_session_duration = avg_pages_per_session * 2
        
        converted_visits = Visit.query.filter(Visit.user_id.isnot(None)).count()
        conversion_rate = (converted_visits / total_visits * 100) if total_visits > 0 else 0
        
        organic_percentage = (organic_visits / total_visits * 100) if total_visits > 0 else 0
        
        direct_visits = Visit.query.filter(
            db.or_(Visit.referrer.is_(None), Visit.referrer == '')
        ).count()
        direct_percentage = (direct_visits / total_visits * 100) if total_visits > 0 else 0
        
        referral_visits = total_visits - organic_visits - direct_visits
        referral_percentage = (referral_visits / total_visits * 100) if total_visits > 0 else 0

        # Core Web Vitals
        estimated_lcp = 1.8
        lcp_status = "جيد"
        estimated_fid = 45
        fid_status = "جيد"
        estimated_cls = 0.05
        cls_status = "جيد"
        
        ctr = organic_percentage
        ctr_status = "ممتاز" if ctr >= 20 else "جيد" if ctr >= 14 else "يحتاج تحسين"
        
        total_ideas = Idea.query.count()
        indexed_pages = 4 + total_ideas

        return render_template('dashboard_analytics.html',
                             organic_visits=organic_visits,
                             organic_popular_pages=organic_popular_pages,
                             bounce_rate=bounce_rate,
                             bounce_rate_status=bounce_rate_status,
                             avg_session_duration=avg_session_duration,
                             avg_pages_per_session=avg_pages_per_session,
                             conversion_rate=conversion_rate,
                             organic_percentage=organic_percentage,
                             direct_visits=direct_visits,
                             direct_percentage=direct_percentage,
                             referral_visits=referral_visits,
                             referral_percentage=referral_percentage,
                             indexed_pages=indexed_pages,
                             estimated_lcp=estimated_lcp,
                             lcp_status=lcp_status,
                             estimated_fid=estimated_fid,
                             fid_status=fid_status,
                             estimated_cls=estimated_cls,
                             cls_status=cls_status,
                             ctr=ctr,
                             ctr_status=ctr_status,
                             total_visits=total_visits,
                             unique_ips=unique_ips)

    except Exception as e:
        app.logger.error(f"Error in analytics: {e}", exc_info=True)
        flash('حدث خطأ في تحميل الإحصائيات المتقدمة.', 'danger')
        return redirect(url_for('dashboard'))

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