import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get('DATABASE_URL', '')
SECRET_KEY = os.environ.get('ADMIN_SECRET_KEY', '')
if not SECRET_KEY:
    raise RuntimeError('Configura ADMIN_SECRET_KEY.')
DEBUG = False
ALLOWED_HOSTS = [host.strip() for host in os.environ.get('ADMIN_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if host.strip()]
ROOT_URLCONF = 'adminsite.urls'
INSTALLED_APPS = ['django.contrib.sessions']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.common.CommonMiddleware',
    'adminsite.middleware.SecurityHeadersMiddleware',
]
TEMPLATES = []
WSGI_APPLICATION = 'adminsite.wsgi.application'
db = urlparse(DATABASE_URL)
if db.scheme not in {'postgres', 'postgresql'}:
    raise RuntimeError('DATABASE_URL debe apuntar a PostgreSQL.')
db_options = parse_qs(db.query)
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': unquote(db.path.lstrip('/')),
    'USER': unquote(db.username or ''), 'PASSWORD': unquote(db.password or ''), 'HOST': db.hostname or '', 'PORT': db.port or 5432,
    'OPTIONS': {key: values[-1] for key, values in db_options.items() if key in {'sslmode', 'application_name'}},
    'CONN_MAX_AGE': 60}}
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = 'assetnext_admin_session'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
SESSION_COOKIE_SECURE = os.environ.get('ADMIN_ENV') == 'production'
SESSION_COOKIE_AGE = 30 * 60
CSRF_COOKIE_NAME = 'assetnext_admin_csrf'
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get('ADMIN_CSRF_TRUSTED_ORIGINS', '').split(',') if origin.strip()]
SECURE_SSL_REDIRECT = os.environ.get('ADMIN_ENV') == 'production'
if os.environ.get('ADMIN_TRUST_PROXY') == 'true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000 if SECURE_SSL_REDIRECT else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_SSL_REDIRECT
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'no-referrer'
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
