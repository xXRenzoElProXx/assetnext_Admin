import hmac
import json
import os
import secrets
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from html import escape

from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
MAX_CHANGE = 10_000_000
LOCK_SECONDS = 15 * 60
MAX_ATTEMPTS = 5
CODE_LIFETIME = timedelta(minutes=5)
CODE_REQUEST_WINDOW = 10 * 60
MAX_CODE_REQUESTS = 3
admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
database_url = os.environ.get('DATABASE_URL')
if not database_url or not admin_email:
    raise RuntimeError('Configura DATABASE_URL y ADMIN_EMAIL.')
engine = create_engine(database_url, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=1800)
allowed_ips = {ip.strip() for ip in os.environ.get('ADMIN_ALLOWED_IPS', '').split(',') if ip.strip()}
attempts = {}  # ponytail: memoria local; usa Redis o WAF al ejecutar varias instancias.
code_requests = {}


def json_response(data=None, status=200):
    return JsonResponse(data or {}, status=status, json_dumps_params={'default': str})


def reject_ip(request):
    return bool(allowed_ips and request.META.get('REMOTE_ADDR') not in allowed_ips)


def admin_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if reject_ip(request):
            return json_response({'error': 'Acceso denegado.'}, 403)
        if not request.session.get('admin_authenticated'):
            return json_response({'error': 'La sesión venció.', 'authenticated': False}, 401)
        return view(request, *args, **kwargs)
    return wrapped


def csrf_state(request):
    if reject_ip(request):
        return json_response({'error': 'Acceso denegado.'}, 403)
    return json_response({'csrfToken': get_token(request), 'authenticated': bool(request.session.get('admin_authenticated')),
                          'pending': bool(request.session.get('pending_admin_email'))})


@require_GET
@ensure_csrf_cookie
def auth_state(request):
    return csrf_state(request)


def code_email_html(code):
    safe_code = escape(code)
    return f'''<!doctype html><html lang="es"><body style="font-family:Arial,sans-serif"><h1>Verifica tu acceso</h1><p>Código de un solo uso:</p><strong style="font-size:32px;letter-spacing:8px">{safe_code}</strong><p>Válido durante 5 minutos. No lo compartas.</p></body></html>'''


def email_is_configured():
    return all((os.environ.get('MAIL_SERVER'), os.environ.get('MAIL_USERNAME'), os.environ.get('MAIL_PASSWORD')))


def send_login_code(code):
    message = EmailMessage()
    message['Subject'] = 'Tu código de acceso | AssetNext Admin'
    message['From'] = os.environ.get('MAIL_DEFAULT_SENDER') or os.environ['MAIL_USERNAME']
    message['To'] = admin_email
    message.set_content(f'Tu código de acceso de AssetNext Admin es: {code}\nVence en 5 minutos y solo puede utilizarse una vez.')
    message.add_alternative(code_email_html(code), subtype='html')
    with smtplib.SMTP(os.environ['MAIL_SERVER'], int(os.environ.get('MAIL_PORT', '587')), timeout=15) as smtp:
        if os.environ.get('MAIL_USE_TLS', 'true').lower() in {'1', 'true', 'yes'}:
            smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ['MAIL_USERNAME'], os.environ['MAIL_PASSWORD'])
        smtp.send_message(message)


def code_digest(code):
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), 'sha256').hexdigest()


@require_POST
def request_login_code(request):
    if reject_ip(request):
        return json_response({'error': 'Acceso denegado.'}, 403)
    ip = request.META.get('REMOTE_ADDR') or 'unknown'
    now = time.monotonic()
    requested = [stamp for stamp in code_requests.get(ip, []) if now - stamp < CODE_REQUEST_WINDOW]
    code_requests[ip] = requested
    if len(requested) >= MAX_CODE_REQUESTS:
        return json_response({'error': 'Espera unos minutos antes de solicitar otro código.'}, 429)
    try:
        payload = json.loads(request.body or '{}')
    except (ValueError, UnicodeDecodeError):
        return json_response({'error': 'Solicitud inválida.'}, 400)
    if not isinstance(payload, dict):
        return json_response({'error': 'Solicitud inválida.'}, 400)
    email = str(payload.get('email', '')).strip().lower()
    pending_resend = request.session.get('pending_admin_email') == admin_email and not email
    if not pending_resend and not hmac.compare_digest(email, admin_email):
        return json_response({'error': 'No se pudo enviar un código a ese correo.'}, 400)
    if not email_is_configured():
        return json_response({'error': 'El envío de correos del panel aún no está configurado.'}, 503)
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    try:
        with engine.begin() as connection:
            connection.execute(text('UPDATE admin_login_code SET usado_en = NOW() WHERE email = :email AND usado_en IS NULL'), {'email': admin_email})
            connection.execute(text('''INSERT INTO admin_login_code (email, codigo_hash, expira_en, ip_solicitud)
                VALUES (:email, :code_hash, :expires_at, :ip)'''), {'email': admin_email, 'code_hash': code_digest(code),
                'expires_at': datetime.now(timezone.utc) + CODE_LIFETIME, 'ip': ip})
        send_login_code(code)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('No se pudo enviar el código de acceso administrativo.')
        return json_response({'error': 'No se pudo enviar el código. Revisa la configuración de correo.'}, 503)
    code_requests[ip] = requested + [now]
    request.session['pending_admin_email'] = admin_email
    request.session.set_expiry(5 * 60)
    return json_response({'message': 'Te enviamos un código de un solo uso. Vence en 5 minutos.', 'pending': True})


@require_POST
def verify_login_code(request):
    if reject_ip(request):
        return json_response({'error': 'Acceso denegado.'}, 403)
    ip = request.META.get('REMOTE_ADDR') or 'unknown'
    now = time.monotonic()
    state = attempts.get(ip, {'count': 0, 'until': 0})
    if state['until'] > now:
        return json_response({'error': 'Demasiados intentos. Espera 15 minutos.'}, 429)
    try:
        payload = json.loads(request.body or '{}')
    except (ValueError, UnicodeDecodeError):
        return json_response({'error': 'Solicitud inválida.'}, 400)
    if not isinstance(payload, dict):
        return json_response({'error': 'Solicitud inválida.'}, 400)
    code = str(payload.get('code', '')).strip()
    valid = False
    if request.session.get('pending_admin_email') == admin_email and len(code) == 6 and code.isdigit():
        with engine.begin() as connection:
            row = connection.execute(text('''SELECT id, codigo_hash FROM admin_login_code WHERE email = :email AND usado_en IS NULL
                AND expira_en > NOW() ORDER BY id DESC LIMIT 1 FOR UPDATE'''), {'email': admin_email}).mappings().first()
            if row and hmac.compare_digest(row['codigo_hash'], code_digest(code)):
                connection.execute(text('UPDATE admin_login_code SET usado_en = NOW() WHERE id = :id'), {'id': row['id']})
                valid = True
    if not valid:
        state['count'] += 1
        attempts[ip] = {'count': 0, 'until': now + LOCK_SECONDS} if state['count'] >= MAX_ATTEMPTS else state
        return json_response({'error': 'Código inválido, vencido o ya utilizado.'}, 400)
    request.session.flush()
    request.session.update({'admin_authenticated': True, 'admin_email': admin_email})
    request.session.set_expiry(30 * 60)
    rotate_token(request)
    return json_response({'authenticated': True})


@require_POST
@admin_required
def logout(request):
    request.session.flush()
    return json_response({'ok': True})


def audit(connection, action, user_id, details):
    connection.execute(text('''INSERT INTO admin_audit (admin_email, accion, usuario_id, detalles, creado_en)
        VALUES (:admin_email, :action, :user_id, CAST(:details AS jsonb), :created_at)'''), {
        'admin_email': admin_email, 'action': action, 'user_id': user_id, 'details': json.dumps(details),
        'created_at': datetime.now(timezone.utc)})


def user_or_404(connection, user_id):
    user = connection.execute(text('''SELECT u.id, u.email, COALESCE(p.nombre, '') AS nombre, COALESCE(p.apellido, '') AS apellido,
        COALESCE(s.creditos, 0) AS creditos, COALESCE(s.racha_actual, 0) AS racha_actual, COALESCE(s.max_racha, 0) AS max_racha,
        COALESCE(s.resurrecciones_disponibles, 0) AS resurrecciones, COALESCE(s.esta_online, false) AS esta_online,
        s.inicio_sesion_actual, s.ultima_actividad, COALESCE(s.esta_online, false) AND s.ultima_actividad >= NOW() - INTERVAL '15 minutes' AS online_now,
        COALESCE(s.sesion_version, 1) AS sesion_version, pr.premium_desde, pr.premium_hasta, COALESCE(pr.premium_hasta > NOW(), false) AS premium_active
        FROM usuario u LEFT JOIN usuario_profile p ON p.usuario_id = u.id LEFT JOIN usuario_streak s ON s.usuario_id = u.id
        LEFT JOIN usuario_premium pr ON pr.usuario_id = u.id WHERE u.id = :user_id'''), {'user_id': user_id}).mappings().first()
    if not user:
        return None
    return dict(user)


@require_GET
@admin_required
def dashboard(request):
    query = request.GET.get('q', '').strip()[:200]
    pattern = f'%{query.lower()}%'
    with engine.connect() as connection:
        metrics = dict(connection.execute(text('''SELECT COUNT(*) AS total,
            COUNT(*) FILTER (WHERE s.esta_online AND s.ultima_actividad >= NOW() - INTERVAL '15 minutes') AS online,
            COUNT(*) FILTER (WHERE pr.premium_hasta > NOW()) AS premium,
            (SELECT COUNT(*) FROM soporte_mensaje WHERE remitente = 'usuario' AND leido_en IS NULL) AS soporte_pendiente
            FROM usuario u LEFT JOIN usuario_streak s ON s.usuario_id = u.id LEFT JOIN usuario_premium pr ON pr.usuario_id = u.id''')).mappings().one())
        users = connection.execute(text('''SELECT u.id, u.email, COALESCE(p.nombre, '') AS nombre, COALESCE(p.apellido, '') AS apellido,
            COALESCE(s.creditos, 0) AS creditos, COALESCE(s.racha_actual, 0) AS racha_actual, COALESCE(s.esta_online, false) AS esta_online,
            s.ultima_actividad, pr.premium_hasta, COALESCE(s.esta_online, false) AND s.ultima_actividad >= NOW() - INTERVAL '15 minutes' AS online_now
            FROM usuario u LEFT JOIN usuario_profile p ON p.usuario_id = u.id LEFT JOIN usuario_streak s ON s.usuario_id = u.id
            LEFT JOIN usuario_premium pr ON pr.usuario_id = u.id WHERE :query = '' OR LOWER(u.email) LIKE :pattern
            OR LOWER(COALESCE(p.nombre, '')) LIKE :pattern ORDER BY u.id DESC LIMIT 200'''), {'query': query, 'pattern': pattern}).mappings().all()
    return json_response({'metrics': metrics, 'users': [dict(row) for row in users], 'query': query})


@require_GET
@admin_required
def support_inbox(request):
    with engine.connect() as connection:
        rows = connection.execute(text('''SELECT c.id, c.actualizado_en, u.id AS usuario_id, u.email,
            COALESCE(p.nombre, '') AS nombre, COALESCE(p.apellido, '') AS apellido,
            COUNT(m.id) FILTER (WHERE m.remitente = 'usuario' AND m.leido_en IS NULL) AS pendientes,
            (SELECT cuerpo FROM soporte_mensaje last_message WHERE last_message.conversacion_id = c.id
             ORDER BY last_message.creado_en DESC LIMIT 1) AS ultimo_mensaje
            FROM soporte_conversacion c JOIN usuario u ON u.id = c.usuario_id LEFT JOIN usuario_profile p ON p.usuario_id = u.id
            LEFT JOIN soporte_mensaje m ON m.conversacion_id = c.id GROUP BY c.id, u.id, p.usuario_id ORDER BY c.actualizado_en DESC''')).mappings().all()
    return json_response({'conversations': [dict(row) for row in rows]})


@require_GET
@admin_required
def support_conversation(request, conversation_id):
    with engine.begin() as connection:
        conversation = connection.execute(text('''SELECT c.id, c.usuario_id, u.email, COALESCE(p.nombre, '') AS nombre,
            COALESCE(p.apellido, '') AS apellido FROM soporte_conversacion c JOIN usuario u ON u.id = c.usuario_id
            LEFT JOIN usuario_profile p ON p.usuario_id = u.id WHERE c.id = :id'''), {'id': conversation_id}).mappings().first()
        if not conversation:
            return json_response({'error': 'Conversación no encontrada.'}, 404)
        messages = connection.execute(text('SELECT id, remitente, cuerpo, creado_en FROM soporte_mensaje WHERE conversacion_id = :id ORDER BY id ASC'), {'id': conversation_id}).mappings().all()
        connection.execute(text("UPDATE soporte_mensaje SET leido_en = NOW() WHERE conversacion_id = :id AND remitente = 'usuario' AND leido_en IS NULL"), {'id': conversation_id})
    return json_response({'conversation': dict(conversation), 'messages': [dict(row) for row in messages]})


@require_POST
@admin_required
def reply_support(request, conversation_id):
    try:
        body = ' '.join(str(json.loads(request.body or '{}').get('body', '')).split())
    except (ValueError, UnicodeDecodeError):
        return json_response({'error': 'Solicitud inválida.'}, 400)
    if not 1 <= len(body) <= 5000:
        return json_response({'error': 'La respuesta debe tener entre 1 y 5000 caracteres.'}, 400)
    with engine.begin() as connection:
        conversation = connection.execute(text('SELECT usuario_id FROM soporte_conversacion WHERE id = :id FOR UPDATE'), {'id': conversation_id}).mappings().first()
        if not conversation:
            return json_response({'error': 'Conversación no encontrada.'}, 404)
        connection.execute(text("INSERT INTO soporte_mensaje (conversacion_id, remitente, cuerpo) VALUES (:id, 'admin', :body)"), {'id': conversation_id, 'body': body})
        connection.execute(text('UPDATE soporte_conversacion SET actualizado_en = NOW() WHERE id = :id'), {'id': conversation_id})
        connection.execute(text("UPDATE soporte_mensaje SET leido_en = NOW() WHERE conversacion_id = :id AND remitente = 'usuario' AND leido_en IS NULL"), {'id': conversation_id})
        connection.execute(text("INSERT INTO alerta (mensaje, tipo, leida, fecha_creacion, usuario_id) VALUES (:message, 'contacto', false, NOW(), :user_id)"), {'message': 'El equipo de AssetNext respondió tu consulta.', 'user_id': conversation['usuario_id']})
        audit(connection, 'respuesta_soporte', conversation['usuario_id'], {'conversacion_id': conversation_id})
    return json_response({'message': 'Respuesta enviada al usuario.'})


@require_GET
@admin_required
def user_detail(request, user_id):
    with engine.connect() as connection:
        user = user_or_404(connection, user_id)
        if not user:
            return json_response({'error': 'Usuario no encontrado.'}, 404)
        events = connection.execute(text('SELECT accion, detalles, creado_en FROM admin_audit WHERE usuario_id = :user_id ORDER BY creado_en DESC LIMIT 12'), {'user_id': user_id}).mappings().all()
    return json_response({'user': user, 'events': [dict(row) for row in events]})


def payload(request):
    try:
        value = json.loads(request.body or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return None


@require_POST
@admin_required
def update_credits(request, user_id):
    data = payload(request)
    if data is None:
        return json_response({'error': 'Solicitud inválida.'}, 400)
    try:
        amount, mode = int(data.get('amount', '')), data.get('mode')
        if not 0 <= amount <= MAX_CHANGE or mode not in {'add', 'subtract', 'set'}:
            raise ValueError
        with engine.begin() as connection:
            user = user_or_404(connection, user_id)
            if not user:
                return json_response({'error': 'Usuario no encontrado.'}, 404)
            value = amount if mode == 'set' else user['creditos'] + (amount if mode == 'add' else -amount)
            if value < 0:
                raise ValueError
            connection.execute(text('UPDATE usuario_streak SET creditos = :value WHERE usuario_id = :user_id'), {'value': value, 'user_id': user_id})
            audit(connection, 'creditos_' + mode, user_id, {'anterior': user['creditos'], 'nuevo': value})
    except (ValueError, TypeError):
        return json_response({'error': 'Indica un valor válido. Los créditos no pueden ser negativos.'}, 400)
    return json_response({'message': 'Créditos actualizados.'})


@require_POST
@admin_required
def update_streak(request, user_id):
    data = payload(request)
    if data is None:
        return json_response({'error': 'Solicitud inválida.'}, 400)
    try:
        streak, resurrections = int(data.get('racha_actual', '')), int(data.get('resurrecciones', ''))
        if min(streak, resurrections) < 0 or max(streak, resurrections) > MAX_CHANGE:
            raise ValueError
        with engine.begin() as connection:
            user = user_or_404(connection, user_id)
            if not user:
                return json_response({'error': 'Usuario no encontrado.'}, 404)
            connection.execute(text('''UPDATE usuario_streak SET racha_actual = :streak, max_racha = :max_streak,
                resurrecciones_disponibles = :resurrections WHERE usuario_id = :user_id'''), {
                'streak': streak, 'max_streak': max(streak, user['max_racha']), 'resurrections': resurrections, 'user_id': user_id})
            audit(connection, 'racha_actualizada', user_id, {'racha': streak, 'resurrecciones': resurrections})
    except (ValueError, TypeError):
        return json_response({'error': 'Indica valores enteros no negativos.'}, 400)
    return json_response({'message': 'Racha actualizada.'})


@require_POST
@admin_required
def update_premium(request, user_id):
    data = payload(request)
    if data is None:
        return json_response({'error': 'Solicitud inválida.'}, 400)
    action = data.get('action')
    try:
        with engine.begin() as connection:
            user = user_or_404(connection, user_id)
            if not user:
                return json_response({'error': 'Usuario no encontrado.'}, 404)
            if action == 'revoke':
                connection.execute(text('DELETE FROM usuario_premium WHERE usuario_id = :user_id'), {'user_id': user_id})
                audit(connection, 'premium_retirado', user_id, {})
            else:
                days = int(data.get('days', ''))
                if not 1 <= days <= 3650:
                    raise ValueError
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                base = user['premium_hasta'] if user['premium_hasta'] and user['premium_hasta'] > now else now
                until = base + timedelta(days=days)
                connection.execute(text('''INSERT INTO usuario_premium (usuario_id, premium_desde, premium_hasta) VALUES (:user_id, :started, :until)
                    ON CONFLICT (usuario_id) DO UPDATE SET premium_hasta = EXCLUDED.premium_hasta'''), {'user_id': user_id, 'started': now, 'until': until})
                audit(connection, 'premium_agregado', user_id, {'dias': days, 'hasta': until.isoformat()})
    except (ValueError, TypeError):
        return json_response({'error': 'Indica entre 1 y 3650 días.'}, 400)
    return json_response({'message': 'Premium actualizado.'})


@require_POST
@admin_required
def force_logout(request, user_id):
    with engine.begin() as connection:
        user = user_or_404(connection, user_id)
        if not user:
            return json_response({'error': 'Usuario no encontrado.'}, 404)
        connection.execute(text('''UPDATE usuario_streak SET esta_online = false, inicio_sesion_actual = NULL, sesion_version = sesion_version + 1 WHERE usuario_id = :user_id'''), {'user_id': user_id})
        audit(connection, 'sesion_cerrada_remotamente', user_id, {})
    return json_response({'message': 'La sesión fue invalidada.'})


@require_POST
@admin_required
def delete_user(request, user_id):
    data = payload(request)
    if data is None:
        return json_response({'error': 'Solicitud inválida.'}, 400)
    with engine.begin() as connection:
        user = user_or_404(connection, user_id)
        if not user:
            return json_response({'error': 'Usuario no encontrado.'}, 404)
        confirmation = str(data.get('confirm_email', '')).strip().lower()
        if not hmac.compare_digest(confirmation, user['email'].lower()):
            return json_response({'error': 'Escribe el correo exacto para confirmar la eliminación.'}, 400)
        for table in ('alerta', 'chatbot_interaccion', 'compra_tienda', 'logro_usuario', 'prediccion', 'presupuesto', 'transaccion', 'meta', 'categoria'):
            connection.execute(text(f'DELETE FROM {table} WHERE usuario_id = :user_id'), {'user_id': user_id})
        audit(connection, 'cuenta_eliminada', user_id, {'email': user['email']})
        connection.execute(text('DELETE FROM usuario WHERE id = :user_id'), {'user_id': user_id})
    return json_response({'message': 'Cuenta eliminada permanentemente.'})


@require_GET
def frontend(request):
    if reject_ip(request):
        return JsonResponse({'error': 'Acceso denegado.'}, status=403)
    from django.http import FileResponse
    return FileResponse(open(settings.BASE_DIR / 'frontend' / 'dist' / 'index.html', 'rb'))


def frontend_asset(request, path):
    from django.views.static import serve
    return serve(request, path, document_root=settings.BASE_DIR / 'frontend' / 'dist' / 'assets')


def legacy_asset(request, path):
    from django.views.static import serve
    return serve(request, path, document_root=settings.BASE_DIR / 'static')
