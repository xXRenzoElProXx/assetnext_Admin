const refreshEvery = 60_000;
let audio;
const loadedAt = Date.now();
const pendingSupport = () => Number(document.querySelector('[data-pending-support]')?.dataset.pendingSupport || 0);
const latestUserMessage = () => Number(document.querySelector('[data-latest-user-message]')?.dataset.latestUserMessage || 0);
const unlockSound = () => {
  if (!window.AudioContext) return;
  audio ||= new AudioContext();
  if (audio.state === 'suspended') audio.resume().catch(() => {});
};
const bubble = () => {
  unlockSound();
  if (!audio || audio.state !== 'running') return;
  [0, .1].forEach((offset, index) => {
    const oscillator = audio.createOscillator(), gain = audio.createGain(), at = audio.currentTime + offset;
    oscillator.type = 'sine'; oscillator.frequency.setValueAtTime(index ? 880 : 660, at);
    gain.gain.setValueAtTime(.0001, at); gain.gain.exponentialRampToValueAtTime(.045, at + .012); gain.gain.exponentialRampToValueAtTime(.0001, at + .09);
    oscillator.connect(gain).connect(audio.destination); oscillator.start(at); oscillator.stop(at + .1);
  });
};
const updateSupportNotice = () => {
  const current = pendingSupport(), previous = sessionStorage.getItem('assetnext_admin_pending_support');
  const latest = latestUserMessage(), knownLatest = sessionStorage.getItem('assetnext_admin_latest_user_message');
  if ((previous !== null && current > Number(previous) || knownLatest !== null && latest > Number(knownLatest)) && !document.hidden) bubble();
  sessionStorage.setItem('assetnext_admin_pending_support', String(current));
  if (latest) sessionStorage.setItem('assetnext_admin_latest_user_message', String(latest));
  document.title = `${current ? `(${current}) ` : ''}${document.title.replace(/^\(\d+\)\s*/, '')}`;
};
const isEditing = () => /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
updateSupportNotice();
document.addEventListener('pointerdown', unlockSound, { once: true });
document.addEventListener('keydown', unlockSound, { once: true });
setInterval(() => { if (!document.hidden && !isEditing()) location.reload(); }, refreshEvery);
document.addEventListener('visibilitychange', () => { if (!document.hidden && Date.now() - loadedAt >= refreshEvery && !isEditing()) location.reload(); });
