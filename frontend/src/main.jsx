import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../../static/styles.css';
import '../../static/support.css';
import '../../static/premium.css';
import '../../static/premium-components.css';

function App() {
  const [path, setPath] = useState(location.pathname);
  const [routeKey, setRouteKey] = useState(0);
  const [auth, setAuth] = useState(null);
  const [csrf, setCsrf] = useState('');
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [query, setQuery] = useState(new URLSearchParams(location.search).get('q') || '');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [reply, setReply] = useState('');
  const [confirmEmail, setConfirmEmail] = useState('');

  const go = (url) => { history.pushState({}, '', url); setPath(location.pathname); setQuery(new URLSearchParams(location.search).get('q') || ''); setRouteKey(value => value + 1); setNotice(null); };
  const request = async (url, options = {}) => {
    const response = await fetch(url, { credentials: 'same-origin', ...options,
      headers: { ...(options.body ? { 'Content-Type': 'application/json', 'X-CSRFToken': csrf } : {}), ...options.headers } });
    const result = await response.json().catch(() => ({}));
    if (response.status === 401) { setAuth({ authenticated: false, pending: false }); go('/'); }
    if (!response.ok) throw Error(result.error || 'No se pudo completar la solicitud.');
    return result;
  };
  const loadAuth = async () => {
    const state = await fetch('/api/auth/', { credentials: 'same-origin' }).then(r => r.json());
    setCsrf(state.csrfToken); setAuth(state);
  };
  const report = (message, kind = 'success') => setNotice({ message, kind });
  const run = async (action, message = true) => {
    setBusy(true);
    try { const result = await action(); if (message && result.message) report(result.message); await refresh(); return true; }
    catch (error) { report(error.message, 'error'); }
    finally { setBusy(false); }
  };
  const refresh = async () => {
    if (!auth?.authenticated) return;
    const userMatch = path.match(/^\/users\/(\d+)$/);
    const conversationMatch = path.match(/^\/support\/(\d+)$/);
    const url = userMatch ? `/api/users/${userMatch[1]}/` : conversationMatch ? `/api/support/${conversationMatch[1]}/` : path === '/support' ? '/api/support/' : `/api/dashboard/?q=${encodeURIComponent(query)}`;
    const result = await request(url);
    setData(result);
  };
  useEffect(() => { loadAuth().catch(() => report('No se pudo iniciar el panel.', 'error')); const pop = () => { setPath(location.pathname); setQuery(new URLSearchParams(location.search).get('q') || ''); setRouteKey(value => value + 1); }; addEventListener('popstate', pop); return () => removeEventListener('popstate', pop); }, []);
  useEffect(() => { if (auth?.authenticated) refresh().catch(error => report(error.message, 'error')); else setData(null); }, [auth?.authenticated, path, query, routeKey]);

  const action = (url, body = {}) => request(url, { method: 'POST', body: JSON.stringify(body) });
  const formAction = (event, fn) => { event.preventDefault(); run(() => fn(new FormData(event.currentTarget))); event.currentTarget.reset(); };
  const logout = () => run(async () => { const r = await action('/api/logout/'); await loadAuth(); go('/'); return r; }, false);

  if (!auth) return <main className="shell"><p>Cargando panel…</p></main>;
  if (!auth.authenticated) return <main className="login-page"><section className="login-card"><p className="brand">ASSETNEXT <span>ADMIN</span></p><p className="eyebrow">OPERACIONES PRIVADAS</p><h1>{auth.pending ? 'Verifica tu acceso' : 'Administración segura'}</h1><p className="muted">{auth.pending ? 'Ingresa el código enviado a tu correo. Es único y vence en cinco minutos.' : 'Acceso exclusivo para el equipo autorizado de AssetNext.'}</p>{notice && <p className={`flash ${notice.kind}`} role="status">{notice.message}</p>}{auth.pending ? <form className="stack" onSubmit={e => { e.preventDefault(); run(async () => { const r = await action('/api/login/verify-code/', { code }); await loadAuth(); go('/'); return r; }, false); }}><label>Código de 6 dígitos<input value={code} onChange={e => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength="6" required autoFocus /></label><button disabled={busy}>Verificar y entrar</button><button className="link-button" type="button" onClick={() => run(() => action('/api/login/request-code/', { email }), false)}>Reenviar código</button></form> : <form className="stack" onSubmit={e => { e.preventDefault(); run(async () => { const r = await action('/api/login/request-code/', { email }); await loadAuth(); report(r.message); return {}; }, false); }}><label>Correo administrador<input type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus /></label><button disabled={busy}>Enviar código seguro</button></form>}<div className="login-security"><strong>Acceso protegido</strong><span>Verificación por correo · sesión aislada · actividad auditada</span></div></section></main>;

  const Header = () => <header className="topbar"><a className="brand" href="/" onClick={e => { e.preventDefault(); go('/'); }}>ASSETNEXT <span>ADMIN</span></a><nav className="topbar-actions"><a href="/" onClick={e => { e.preventDefault(); go('/'); }}>Usuarios</a><a href="/support" onClick={e => { e.preventDefault(); go('/support'); }}>Soporte</a><button className="quiet" onClick={logout}>Cerrar sesión</button></nav></header>;
  const Flash = () => notice && <p className={`flash ${notice.kind}`} role="status">{notice.message}</p>;
  const date = value => value ? new Date(value).toLocaleString('es-PE', { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }) : 'Sin registro';
  const shell = content => <><Header /><main className="shell"><Flash />{content}</main></>;

  if (path === '/support') return shell(<><section className="page-title"><p className="eyebrow">CENTRO DE AYUDA</p><h1>Conversaciones de soporte</h1><p>Responde las dudas de los usuarios desde un único lugar.</p></section><section className="panel inbox">{data?.conversations?.length ? data.conversations.map(item => <a className="conversation-row" key={item.id} href={`/support/${item.id}`} onClick={e => { e.preventDefault(); go(`/support/${item.id}`); }}><div className="conversation-avatar">{(item.nombre || item.email)[0].toUpperCase()}</div><div className="conversation-main"><strong>{item.nombre} {item.apellido}</strong><small>{item.email}</small><p>{item.ultimo_mensaje}</p></div><div className="conversation-meta">{item.pendientes > 0 && <span className="unread">{item.pendientes} nuevo(s)</span>}<time>{date(item.actualizado_en)}</time></div></a>) : <div className="empty">No hay conversaciones todavía.</div>}</section></>);

  const conversationMatch = path.match(/^\/support\/(\d+)$/);
  if (conversationMatch) return shell(data?.conversation ? <><a className="back" href="/support" onClick={e => { e.preventDefault(); go('/support'); }}>Volver a conversaciones</a><section className="user-hero"><div><p className="eyebrow">CONVERSACIÓN CON</p><h1>{data.conversation.nombre} {data.conversation.apellido}</h1><p>{data.conversation.email}</p></div><button className="button-link" onClick={() => go(`/users/${data.conversation.usuario_id}`)}>Gestionar cuenta</button></section><section className="panel admin-thread"><div className="admin-messages">{data.messages.map(item => <article className={`admin-message ${item.remitente}`} key={item.id}><strong>{item.remitente === 'admin' ? 'Equipo AssetNext' : data.conversation.nombre || data.conversation.email}</strong><p>{item.cuerpo}</p><time>{date(item.creado_en)} UTC</time></article>)}</div><form className="reply-form" onSubmit={e => { e.preventDefault(); run(() => action(`/api/support/${conversationMatch[1]}/reply/`, { body: reply })); setReply(''); }}><label>Responder a {data.conversation.email}<textarea value={reply} onChange={e => setReply(e.target.value)} minLength="1" maxLength="5000" rows="5" required /></label><button disabled={busy}>Enviar respuesta</button></form></section></> : <p>Cargando conversación…</p>);

  const userMatch = path.match(/^\/users\/(\d+)$/);
  if (userMatch) {
    const user = data?.user;
    if (!user) return shell(<p>Cargando cuenta…</p>);
    const mutate = (endpoint, form, fields) => run(() => action(`/api/users/${user.id}/${endpoint}/`, Object.fromEntries(fields.map(key => [key, form.get(key)]))));
    return shell(<><a className="back" href="/" onClick={e => { e.preventDefault(); go('/'); }}>Volver a usuarios</a><section className="user-hero"><div><p className="eyebrow">CUENTA</p><h1>{user.nombre} {user.apellido}</h1><p>{user.email}</p></div><span className={`status ${user.online_now ? 'online' : 'offline'}`}>{user.online_now ? 'En línea' : 'Desconectado'}</span></section><section className="admin-grid">
      <article className="panel"><h2>Créditos</h2><p className="number">{user.creditos}</p><form className="stack" onSubmit={e => formAction(e, f => mutate('credits', f, ['mode','amount']))}><label>Operación<select name="mode"><option value="add">Agregar</option><option value="subtract">Restar</option><option value="set">Establecer total</option></select></label><label>Cantidad<input name="amount" type="number" min="0" max="10000000" required /></label><button disabled={busy}>Guardar créditos</button></form></article>
      <article className="panel"><h2>Racha</h2><p className="muted">Máximo histórico: {user.max_racha} días</p><form className="stack" onSubmit={e => formAction(e, f => mutate('streak', f, ['racha_actual','resurrecciones']))}><label>Racha actual<input name="racha_actual" type="number" min="0" max="10000000" defaultValue={user.racha_actual} required /></label><label>Resurrecciones<input name="resurrecciones" type="number" min="0" max="10000000" defaultValue={user.resurrecciones} required /></label><button disabled={busy}>Guardar racha</button></form></article>
      <article className="panel"><h2>Premium</h2><p className="muted">{user.premium_active ? `Vence ${date(user.premium_hasta)}` : 'Sin Premium activo'}</p><form className="stack" onSubmit={e => {e.preventDefault(); mutate('premium', new FormData(e.currentTarget), ['days']);}}><label>Días a añadir<input name="days" type="number" min="1" max="3650" defaultValue="30" required /></label><button name="action" value="extend" disabled={busy}>Añadir días</button><button className="danger-outline" type="button" disabled={busy} onClick={() => run(() => action(`/api/users/${user.id}/premium/`, {action:'revoke'}))}>Retirar Premium</button></form></article>
      <article className="panel danger-panel"><h2>Sesión</h2><p className="muted">Última actividad: {date(user.ultima_actividad)} UTC</p><button className="danger" disabled={busy} onClick={() => run(() => action(`/api/users/${user.id}/logout/`))}>Cerrar sesión remota</button></article>
      <article className="panel danger-panel"><h2>Eliminar cuenta</h2><p className="muted">Elimina permanentemente la cuenta y sus datos personales. No se puede deshacer.</p><form className="stack" onSubmit={e => {e.preventDefault(); if (confirm(`¿Eliminar permanentemente la cuenta ${user.email}?`)) run(() => action(`/api/users/${user.id}/delete/`, {confirm_email:confirmEmail})).then(ok => { if (ok) go('/'); });}}><label>Escribe {user.email} para confirmar<input type="email" autoComplete="off" value={confirmEmail} onChange={e => setConfirmEmail(e.target.value)} required /></label><button className="danger" disabled={busy}>Eliminar cuenta y datos</button></form></article>
    </section><section className="panel audit"><h2>Auditoría reciente</h2><div className="table-wrap"><table><thead><tr><th>Acción</th><th>Detalle</th><th>Fecha</th></tr></thead><tbody>{data.events.map((event,i)=><tr key={i}><td>{event.accion}</td><td>{JSON.stringify(event.detalles)}</td><td>{date(event.creado_en)}</td></tr>)}</tbody></table></div></section></>);
  }

  const metrics = data?.metrics || {};
  return shell(<><section className="page-title"><div><p className="eyebrow">OPERACIONES INTERNAS</p><h1>Usuarios y acceso</h1><p>Supervisa cuentas, beneficios y solicitudes con trazabilidad.</p></div><aside className="admin-live"><span className="live-pulse"/><div><strong>Panel protegido</strong><small>Actualización en vivo cada minuto</small></div></aside></section><section className="metrics"><article><span>Usuarios</span><strong>{metrics.total ?? '—'}</strong></article><article><span>En línea ahora</span><strong>{metrics.online ?? '—'}</strong></article><article><span>Premium activo</span><strong>{metrics.premium ?? '—'}</strong></article><article><span>Consultas pendientes</span><strong>{metrics.soporte_pendiente ?? '—'}</strong></article></section><section className="panel"><form className="search" onSubmit={e => {e.preventDefault(); go(`/?q=${encodeURIComponent(query)}`);}}><label htmlFor="q">Buscar usuario</label><div><input id="q" value={query} onChange={e => setQuery(e.target.value)} placeholder="Nombre o correo"/><button>Buscar</button></div></form><div className="table-wrap"><table><thead><tr><th>Usuario</th><th>Estado</th><th>Créditos</th><th>Racha</th><th>Premium</th><th></th></tr></thead><tbody>{(data?.users || []).map(user=><tr key={user.id}><td><strong>{user.nombre} {user.apellido}</strong><small>{user.email}</small></td><td><span className={`status ${user.online_now ? 'online' : user.esta_online ? 'stale' : 'offline'}`}>{user.online_now ? 'En línea' : user.esta_online ? 'Sin confirmar' : 'Desconectado'}</span></td><td>{user.creditos}</td><td>{user.racha_actual} días</td><td>{user.premium_hasta && new Date(user.premium_hasta) > new Date() ? 'Activo' : 'No activo'}</td><td><button className="button-link" onClick={() => go(`/users/${user.id}`)}>Gestionar</button></td></tr>)}</tbody></table></div></section></>);
}

createRoot(document.getElementById('root')).render(<App />);
