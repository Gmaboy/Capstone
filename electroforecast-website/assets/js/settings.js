(function () {
  'use strict';

  const allowedRoles = ['admin', 'guimelco', 'researcher', 'household'];
  const roleLabels = {
    admin: 'Administrator',
    guimelco: 'GUIMELCO Staff',
    researcher: 'Researcher',
    household: 'Household',
  };
  let loadedSettings = null;

  ElectroShell.mount('settings', 'Settings', { dateRange: false });

  function initials(name) {
    return String(name || 'User')
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map(part => part.charAt(0))
      .join('')
      .toUpperCase();
  }

  function setValue(id, value) {
    const element = document.getElementById(id);
    if (element) element.value = value ?? '';
  }

  function setChecked(id, value) {
    const element = document.getElementById(id);
    if (element) element.checked = Boolean(value);
  }

  function renderSettings(payload) {
    loadedSettings = payload;
    const profile = payload.profile;
    const preferences = payload.preferences;
    const dataSource = payload.data_source;

    setValue('profile-name', profile.full_name);
    setValue('profile-email', profile.email);
    setValue('profile-contact', profile.contact_no);
    setValue('profile-role', profile.role);
    document.getElementById('settings-avatar').textContent = initials(profile.full_name);
    document.getElementById('settings-role-badge').innerHTML =
      `<i data-feather="shield"></i> ${ElectroAPI.escapeHTML(roleLabels[profile.role] || profile.role)}`;

    setChecked('notify-high-demand', preferences.notify_high_demand);
    setChecked('notify-rating-updates', preferences.notify_rating_updates);
    setChecked('notify-weekly-summary', preferences.notify_weekly_summary);
    setValue('forecast-horizon', preferences.forecast_horizon);
    setValue('forecast-granularity', preferences.forecast_granularity);
    setValue('measurement-unit', preferences.measurement_unit);
    setValue('landing-page', preferences.landing_page);
    setChecked('show-confidence-intervals', preferences.show_confidence_intervals);
    setChecked('show-demand-gauge', preferences.show_demand_gauge);
    setChecked('compact-table-view', preferences.compact_table_view);

    setValue('refresh-frequency', dataSource.data_refresh_frequency);
    setValue('file-format', dataSource.default_file_format);
    if (window.feather) feather.replace({ 'stroke-width': 2, width: 17, height: 17 });
  }

  function preferencesPayload() {
    return {
      section: 'preferences',
      notify_high_demand: document.getElementById('notify-high-demand').checked,
      notify_rating_updates: document.getElementById('notify-rating-updates').checked,
      notify_weekly_summary: document.getElementById('notify-weekly-summary').checked,
      forecast_horizon: document.getElementById('forecast-horizon').value,
      forecast_granularity: document.getElementById('forecast-granularity').value,
      measurement_unit: document.getElementById('measurement-unit').value,
      landing_page: document.getElementById('landing-page').value,
      show_confidence_intervals: document.getElementById('show-confidence-intervals').checked,
      show_demand_gauge: document.getElementById('show-demand-gauge').checked,
      compact_table_view: document.getElementById('compact-table-view').checked,
    };
  }

  function setButtonLoading(button, loading, success) {
    if (!button.dataset.originalHtml) button.dataset.originalHtml = button.innerHTML;
    button.disabled = loading;
    if (loading) button.innerHTML = '<i data-feather="loader"></i> Savingâ€¦';
    else if (success) button.innerHTML = '<i data-feather="check"></i> Saved';
    else button.innerHTML = button.dataset.originalHtml;
    if (window.feather) feather.replace({ 'stroke-width': 2, width: 15, height: 15 });
  }

  window.showSettingsPanel = function (name) {
    const targetNav = document.getElementById(`nav-${name}`);
    const targetPanel = document.getElementById(`panel-${name}`);
    if (!targetNav || !targetPanel) return;
    document.querySelectorAll('.settings-nav .s-item').forEach(item => {
      const active = item === targetNav;
      item.classList.toggle('active', active);
      item.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('.settings-panel').forEach(panel => {
      const active = panel === targetPanel;
      panel.classList.toggle('active', active);
      panel.hidden = !active;
    });
    history.replaceState(null, '', `#${name}`);
  };

  window.showSettingsToast = function (message, isError) {
    const toast = document.getElementById('settings-toast');
    toast.classList.toggle('error', Boolean(isError));
    toast.querySelector('span').textContent = message;
    toast.classList.add('show');
    clearTimeout(window.settingsToastTimer);
    window.settingsToastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
  };

  window.saveSettings = async function (button, section) {
    if (!loadedSettings) {
      showSettingsToast('Settings are still loading. Please try again.', true);
      return;
    }
    setButtonLoading(button, true, false);
    try {
      if (section === 'profile') {
        const response = await ElectroAPI.request('/api/settings', {
          method: 'PATCH',
          body: {
            section: 'profile',
            full_name: document.getElementById('profile-name').value,
            email: document.getElementById('profile-email').value,
            contact_no: document.getElementById('profile-contact').value,
          },
        });
        await ElectroAPI.request('/api/settings', { method: 'PATCH', body: preferencesPayload() });
        loadedSettings.profile = {
          full_name: response.user.full_name,
          email: response.user.email,
          contact_no: response.user.contact_no || '',
          role: response.user.role,
        };
        ElectroShell.setUser(response.user);
        renderSettings(loadedSettings);
      } else if (section === 'preferences') {
        await ElectroAPI.request('/api/settings', { method: 'PATCH', body: preferencesPayload() });
      } else if (section === 'data_source') {
        await ElectroAPI.request('/api/settings', {
          method: 'PATCH',
          body: {
            section: 'data_source',
            data_refresh_frequency: document.getElementById('refresh-frequency').value,
            default_file_format: document.getElementById('file-format').value,
          },
        });
      } else {
        throw new Error('Unknown settings section');
      }
      setButtonLoading(button, false, true);
      showSettingsToast('Your settings were saved to your account.');
      setTimeout(() => setButtonLoading(button, false, false), 1300);
    } catch (error) {
      setButtonLoading(button, false, false);
      showSettingsToast(error.message || 'Unable to save settings.', true);
    }
  };

  window.updatePassword = async function (button) {
    const current = document.getElementById('current-password');
    const password = document.getElementById('new-password');
    const confirmation = document.getElementById('confirm-password');
    [current, password, confirmation].forEach(input => input.classList.remove('input-error'));
    if (!current.value || password.value.length < 8 || password.value !== confirmation.value) {
      if (!current.value) current.classList.add('input-error');
      if (password.value.length < 8) password.classList.add('input-error');
      if (!confirmation.value || password.value !== confirmation.value) confirmation.classList.add('input-error');
      showSettingsToast('Check the highlighted password fields.', true);
      return;
    }
    setButtonLoading(button, true, false);
    try {
      await ElectroAPI.request('/api/settings/password', {
        method: 'PATCH',
        body: {
          current_password: current.value,
          new_password: password.value,
          password_confirmation: confirmation.value,
        },
      });
      [current, password, confirmation].forEach(input => { input.value = ''; });
      setButtonLoading(button, false, true);
      showSettingsToast('Password updated successfully.');
      setTimeout(() => setButtonLoading(button, false, false), 1300);
    } catch (error) {
      setButtonLoading(button, false, false);
      showSettingsToast(error.message || 'Unable to update password.', true);
    }
  };

  document.querySelectorAll('.settings-nav .s-item').forEach((item, index, items) => {
    item.addEventListener('keydown', event => {
      if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft'].includes(event.key)) return;
      event.preventDefault();
      const direction = ['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : -1;
      items[(index + direction + items.length) % items.length].focus();
    });
  });

  const initialPanel = location.hash.slice(1);
  if (['profile', 'preferences', 'datasource', 'security', 'system'].includes(initialPanel)) {
    showSettingsPanel(initialPanel);
  }

  (async function initializeSettings() {
    try {
      await ElectroAPI.requireRole(allowedRoles);
      const payload = await ElectroAPI.request('/api/settings');
      renderSettings(payload);
    } catch (error) {
      if (error.status !== 401) showSettingsToast(error.message || 'Unable to load account settings.', true);
    }
    renderSystemModels();
  })();

  async function renderSystemModels() {
    const setText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    const trainedOn = run => ElectroAPI.formatDate(String(run.trained_at).replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(run.trained_at) ? '' : 'Z'),
      { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' });
    let runs = [];
    try {
      runs = (await ElectroAPI.request('/api/models/active')).runs || [];
    } catch (_) { /* tiles fall back to "not trained" below */ }
    const forecast = runs.find(r => r.task === 'monthly_energy');
    const classifier = runs.find(r => r.task === 'demand_class');
    if (forecast) {
      const mape = forecast.metrics && Number.isFinite(forecast.metrics.mean_mape) ? `MAPE ${forecast.metrics.mean_mape.toFixed(1)}%` : 'Active';
      setText('sysModel', ElectroAPI.titleCase(forecast.model_name));
      setText('sysModelSub', `${mape} · real GUIMELCO data`);
      setText('sysTrained', trainedOn(forecast));
      setText('sysTrainedSub', forecast.dataset_version);
    } else {
      setText('sysModel', 'Not trained');
      setText('sysModelSub', 'Run python -m tools.model.train');
      setText('sysTrained', '—');
      setText('sysTrainedSub', 'No model run stored');
    }
    if (classifier) {
      const f1 = classifier.metrics && Number.isFinite(classifier.metrics.macro_f1) ? `Macro-F1 ${classifier.metrics.macro_f1.toFixed(2)}` : 'Active';
      setText('sysClf', ElectroAPI.titleCase(classifier.model_name));
      setText('sysClfSub', `${f1} · synthetic data`);
    } else {
      setText('sysClf', 'Not trained');
      setText('sysClfSub', 'Run python -m tools.model.train');
    }
  }
})();
