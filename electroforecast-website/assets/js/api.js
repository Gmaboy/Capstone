(function () {
  'use strict';

  async function request(path, options) {
    const config = { credentials: 'same-origin', ...options };
    const isFormData = typeof FormData !== 'undefined' && config.body instanceof FormData;
    if (config.body && typeof config.body !== 'string' && !isFormData) {
      config.headers = { 'Content-Type': 'application/json', ...(config.headers || {}) };
      config.body = JSON.stringify(config.body);
    }
    const response = await fetch(path, config);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.error || `Request failed (${response.status})`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  async function currentUser() {
    try {
      const payload = await request('/api/auth/me');
      sessionStorage.setItem('electro_user', JSON.stringify(payload.user));
      return payload.user;
    } catch (error) {
      sessionStorage.removeItem('electro_user');
      if (error.status === 401) window.location.href = 'login.html';
      throw error;
    }
  }

  async function requireRole(allowedRoles) {
    const user = await currentUser();
    if (!allowedRoles.includes(user.role)) {
      window.location.href = user.role === 'household' ? 'user-portal.html' : 'admin-dashboard.html';
      throw new Error('Role not permitted');
    }
    if (window.ElectroShell) ElectroShell.setUser(user);
    return user;
  }

  function escapeHTML(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function titleCase(value) {
    return String(value || '')
      .replaceAll('_', ' ')
      .replace(/\b\w/g, letter => letter.toUpperCase());
  }

  function statusBadge(status) {
    const safeStatus = ['pending', 'approved', 'rejected', 'active', 'inactive'].includes(status)
      ? status
      : 'neutral';
    const className = safeStatus === 'approved' || safeStatus === 'active'
      ? 'verified'
      : safeStatus;
    return `<span class="badge ${className}"><span class="badge-dot"></span>${titleCase(status)}</span>`;
  }

  function formatDate(value, options) {
    if (!value) return '—';
    const parsed = new Date(value.includes('T') ? value : value.replace(' ', 'T') + 'Z');
    if (Number.isNaN(parsed.getTime())) return value;
    return new Intl.DateTimeFormat('en-PH', options || {
      year: 'numeric', month: 'short', day: 'numeric'
    }).format(parsed);
  }

  function formatMonth(value) {
    if (!value) return '—';
    const [year, month] = value.split('-').map(Number);
    return new Intl.DateTimeFormat('en-PH', {
      year: 'numeric', month: 'long', timeZone: 'UTC'
    }).format(new Date(Date.UTC(year, month - 1, 1)));
  }

  function notify(message, type = 'success') {
    let toast = document.getElementById('app-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'app-toast';
      toast.className = 'app-toast';
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      document.body.appendChild(toast);
    }
    toast.className = `app-toast ${type} show`;
    toast.innerHTML = `<i data-feather="${type === 'error' ? 'alert-circle' : 'check-circle'}"></i><span>${escapeHTML(message)}</span>`;
    if (window.feather) feather.replace({ 'stroke-width': 2, width: 16, height: 16 });
    clearTimeout(window.electroToastTimer);
    window.electroToastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
  }

  async function logout() {
    try {
      await request('/api/auth/logout', { method: 'POST' });
    } finally {
      sessionStorage.removeItem('electro_user');
      window.location.href = 'login.html';
    }
  }

  window.ElectroAPI = {
    request,
    currentUser,
    requireRole,
    escapeHTML,
    titleCase,
    statusBadge,
    formatDate,
    formatMonth,
    notify,
    logout,
  };
})();
