# AssetNext Admin

Panel privado para administrar la base PostgreSQL de AssetNext. La API y las sesiones usan Django; la interfaz usa React y Vite. La API solo acepta solicitudes del mismo origen y exige sesión autenticada más CSRF para cada operación que modifica datos.

## Preparación

1. Aplica primero las migraciones de la aplicación AssetNext que habilitan el cierre remoto, el soporte y los códigos temporales:

```powershell
cd 'D:\Proyectos - Renzo\assetNext-c748048'
$env:PYTHONPATH = "$PWD\.python-deps"
py -3 -m flask --app app db upgrade
```

2. En esta carpeta, copia `.env.example` a `.env` y define `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_SECRET_KEY` y los datos SMTP. Usa una contraseña de aplicación para Gmail.
3. Instala dependencias y crea la tabla de sesiones revocables de Django:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
..venv\Scripts\python manage.py migrate
cd frontend
npm install
npm run build
cd ..
```

4. Inicia el panel:

```powershell
.\.venv\Scripts\python manage.py runserver 127.0.0.1:5101
```

Abre `http://127.0.0.1:5101`. Si el puerto está ocupado, usa `ADMIN_PORT` con un servidor ASGI/WSGI de producción; `runserver` es solo para desarrollo.

## Seguridad

- Acceso independiente de las cuentas normales, por código de un solo uso enviado al correo autorizado; el código se almacena como HMAC, vence en cinco minutos y se consume una vez.
- Sesiones Django en PostgreSQL, revocables al cerrar sesión, con expiración de 30 minutos, cookies `HttpOnly` y `SameSite=Strict`; en producción también `Secure`.
- Protección CSRF de Django en todas las solicitudes de escritura, consultas SQL parametrizadas, confirmación por correo exacto para borrar usuarios, auditoría y cabeceras CSP.
- Limita el panel a HTTPS detrás de un proxy confiable o VPN. Configura `ADMIN_ENV=production`, `ADMIN_ALLOWED_HOSTS`, `ADMIN_ALLOWED_IPS` y, si aplica, `ADMIN_CSRF_TRUSTED_ORIGINS`. Activa `ADMIN_TRUST_PROXY=true` solo si el proxy confiable elimina y fija `X-Forwarded-Proto`. No expongas el servidor de desarrollo a Internet.

Los contadores de intentos y solicitudes OTP viven en memoria del proceso. Para varias instancias, coloca un proxy con limitación de tasa compartida o migra esos contadores a Redis antes de escalar.
