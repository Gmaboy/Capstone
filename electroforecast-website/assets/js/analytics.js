(function () {
  'use strict';

  const esc = value => ElectroAPI.escapeHTML(value);

  function dataBadge(source) {
    const real = source === 'real';
    return `<span class="data-badge ${real ? 'real' : 'synthetic'}">${real ? 'Real GUIMELCO data' : 'Synthetic'}</span>`;
  }

  function modelCard(run, metricLabel, metricValue) {
    const trained = run && run.trained_at ? ElectroAPI.formatDate(/[T ]/.test(String(run.trained_at)) ? String(run.trained_at) : run.trained_at + 'T00:00:00Z', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }) : '—';
    return `<div class="model-card">
      <div class="model-card-name">${esc(ElectroAPI.titleCase(run && run.model_name))}</div>
      <div class="model-card-meta">Trained ${esc(trained)}</div>
      <div class="model-card-metric"><span>${esc(metricLabel)}</span><b>${esc(metricValue)}</b></div>
    </div>`;
  }

  function emptyState(container) {
    container.innerHTML = `<div class="card"><div class="empty-table">
      <i data-feather="database"></i><b>No trained model yet</b>
      <span>Run <code>python -m tools.model.train</code> to train the models, then reload this page.</span>
    </div></div>`;
    if (window.feather) feather.replace();
  }

  window.ElectroAnalytics = { dataBadge, modelCard, emptyState };
})();
