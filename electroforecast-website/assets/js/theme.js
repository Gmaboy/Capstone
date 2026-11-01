/* GUIMPOWERCORE light/dark theme. Load in <head> so the saved theme applies before the page paints. */
(function () {
  'use strict';

  const KEY = 'electro_theme';
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function saved() {
    try { return localStorage.getItem(KEY); } catch (_) { return null; }
  }

  function preferred() {
    const choice = saved();
    if (choice === 'light' || choice === 'dark') return choice;
    return media && media.matches ? 'dark' : 'light';
  }

  // Update every toggle's label to describe what clicking it will do.
  function syncToggles() {
    const dark = root.getAttribute('data-theme') === 'dark';
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      const label = dark ? 'Switch to light mode' : 'Switch to dark mode';
      btn.setAttribute('aria-label', label);
      btn.setAttribute('title', label);
      btn.setAttribute('aria-pressed', String(dark));
    });
  }

  function apply(theme) {
    root.setAttribute('data-theme', theme);
    syncToggles();
    window.dispatchEvent(new CustomEvent('electro:themechange', { detail: theme }));
  }

  apply(preferred());

  // The collapsed sidebar is also applied here, before paint, so pages don't jump when they load.
  try { if (localStorage.getItem('electro_sidebar') === 'collapsed') root.setAttribute('data-sidebar', 'collapsed'); } catch (_) { /* default: expanded */ }

  if (media) {
    const follow = () => { if (!saved()) apply(preferred()); };
    if (media.addEventListener) media.addEventListener('change', follow);
    else if (media.addListener) media.addListener(follow);
  }

  document.addEventListener('click', event => {
    const btn = event.target.closest && event.target.closest('[data-theme-toggle]');
    if (!btn) return;
    const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(KEY, next); } catch (_) { /* still switch for this page */ }
    apply(next);
  });

  // Static pages mark where a toggle goes with <span data-theme-slot="extra classes"></span>.
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-theme-slot]').forEach(slot => {
      slot.outerHTML = window.ElectroTheme.toggleHTML(slot.getAttribute('data-theme-slot'));
    });
    syncToggles();
  });

  const ICONS = '<svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>'
    + '<svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>';

  window.ElectroTheme = {
    current: () => root.getAttribute('data-theme'),
    toggleHTML: className => `<button type="button" class="theme-toggle ${className || ''}" data-theme-toggle aria-label="Switch to dark mode">${ICONS}</button>`,
    sync: syncToggles
  };
})();
