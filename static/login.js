document.querySelector('.password-toggle')?.addEventListener('click', ({ currentTarget: button }) => {
  const input = document.getElementById(button.getAttribute('aria-controls'));
  const visible = input.type === 'password';
  input.type = visible ? 'text' : 'password';
  button.setAttribute('aria-pressed', String(visible));
  button.setAttribute('aria-label', visible ? 'Ocultar contraseña' : 'Mostrar contraseña');
});
