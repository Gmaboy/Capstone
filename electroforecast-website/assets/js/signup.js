(function () {
  'use strict';

  const form = document.getElementById('signup-form');
  const password = document.getElementById('password');
  const confirmation = document.getElementById('password-confirmation');
  const municipality = document.getElementById('municipality');
  const barangay = document.getElementById('barangay');
  const barangayCount = document.getElementById('barangay-count');
  const errorBox = document.getElementById('signup-error');
  const submitButton = document.getElementById('signup-button');
  let municipalities = [];

  function refreshIcons() {
    if (window.feather) feather.replace({ 'stroke-width':2 });
  }

  function updatePasswordRules() {
    const value = password.value;
    const rules = {
      length:value.length >= 8,
      case:/[a-z]/.test(value) && /[A-Z]/.test(value),
      number:/\d/.test(value)
    };
    Object.entries(rules).forEach(([rule,valid])=>{
      const item = document.querySelector(`[data-rule="${rule}"]`);
      item.classList.toggle('valid',valid);
      item.innerHTML = `<i data-feather="${valid ? 'check-circle' : 'circle'}"></i> ${item.textContent.trim()}`;
    });
    refreshIcons();
  }

  function renderBarangays() {
    const selected = municipalities.find(item=>item.name === municipality.value);
    barangay.innerHTML = selected
      ? `<option value="">Select barangay</option>${selected.barangays.map(name=>`<option value="${ElectroAPI.escapeHTML(name)}">${ElectroAPI.escapeHTML(name)}</option>`).join('')}`
      : '<option value="">Select municipality first</option>';
    barangay.disabled = !selected;
    barangayCount.textContent = selected
      ? `${selected.barangays.length} official barangays in ${selected.name}`
      : 'Select a municipality to load its barangays.';
  }

  async function loadLocations() {
    try {
      const payload = await ElectroAPI.request('/api/locations/guimaras');
      municipalities = payload.municipalities;
      municipality.innerHTML = `<option value="">Select municipality</option>${municipalities.map(item=>`<option value="${ElectroAPI.escapeHTML(item.name)}">${ElectroAPI.escapeHTML(item.name)}</option>`).join('')}`;
      municipality.disabled = false;
      renderBarangays();
    } catch (error) {
      municipality.innerHTML = '<option value="">Locations unavailable</option>';
      barangayCount.textContent = 'Unable to load Guimaras locations. Refresh the page to try again.';
      errorBox.querySelector('span').textContent = error.message;
      errorBox.hidden = false;
      refreshIcons();
    }
  }

  document.querySelectorAll('[data-password-target]').forEach(toggle=>{
    toggle.addEventListener('click',()=>{
      const input = document.getElementById(toggle.dataset.passwordTarget);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      toggle.setAttribute('aria-pressed',String(show));
      toggle.setAttribute('aria-label',show ? 'Hide password' : 'Show password');
      toggle.innerHTML = `<i data-feather="${show ? 'eye-off' : 'eye'}"></i>`;
      refreshIcons();
    });
  });

  password.addEventListener('input',updatePasswordRules);
  municipality.addEventListener('change',renderBarangays);
  confirmation.addEventListener('input',()=>{
    confirmation.setCustomValidity(
      confirmation.value && confirmation.value !== password.value ? 'Passwords do not match' : ''
    );
  });

  form.addEventListener('submit',async event=>{
    event.preventDefault();
    confirmation.setCustomValidity(confirmation.value !== password.value ? 'Passwords do not match' : '');
    if (!form.reportValidity()) return;
    errorBox.hidden = true;
    submitButton.disabled = true;
    submitButton.innerHTML = '<span class="button-spinner"></span> Creating account…';
    try {
      const formData = new FormData(form);
      const payload = await ElectroAPI.request('/api/auth/register',{
        method:'POST',
        body:{
          ...Object.fromEntries(formData.entries()),
          terms_accepted:document.getElementById('terms-accepted').checked
        }
      });
      sessionStorage.setItem('electro_user',JSON.stringify(payload.user));
      window.location.href = payload.redirect;
    } catch (error) {
      errorBox.querySelector('span').textContent = error.message;
      errorBox.hidden = false;
      submitButton.disabled = false;
      submitButton.innerHTML = '<i data-feather="user-plus"></i> Create Household Account';
      refreshIcons();
      errorBox.scrollIntoView({behavior:'smooth',block:'center'});
    }
  });

  refreshIcons();
  loadLocations();
})();
