(function () {
  'use strict';

  const esc = value => ElectroAPI.escapeHTML(value);

  function dataBadge(source) {
    if (source === 'crowdsourced') return '<span class="data-badge crowdsourced">Crowdsourced, admin-approved</span>';
    const real = source === 'real';
    return `<span class="data-badge ${real ? 'real' : 'synthetic'}">${real ? 'Real GUIMELCO data' : 'Synthetic'}</span>`;
  }

  function modelCard(run, metricLabel, metricValue) {
    const trained = run && run.trained_at ? ElectroAPI.formatDate(/[T ]/.test(String(run.trained_at)) ? String(run.trained_at) : run.trained_at + 'T00:00:00Z', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }) : '—';
    return `<div class="model-card">
      <div class="model-card-name">${esc(ElectroAPI.modelLabel(run && run.model_name))}</div>
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

  // Toggle the inline explanation panel that an .info-btn controls (aria-controls).
  function initInfoButtons(root) {
    (root || document).querySelectorAll('.info-btn[aria-controls]').forEach(btn => {
      if (btn.dataset.infoReady) return;
      btn.dataset.infoReady = '1';
      const panel = document.getElementById(btn.getAttribute('aria-controls'));
      if (!panel) return;
      btn.addEventListener('click', () => {
        const open = btn.getAttribute('aria-expanded') !== 'true';
        btn.setAttribute('aria-expanded', String(open));
        panel.hidden = !open;
      });
    });
  }
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.info-btn[aria-expanded="true"]').forEach(btn => {
      btn.setAttribute('aria-expanded', 'false');
      const panel = document.getElementById(btn.getAttribute('aria-controls'));
      if (panel) panel.hidden = true;
    });
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => initInfoButtons());
  else initInfoButtons();

  const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const num = v => Math.round(Number(v)).toLocaleString('en-US');
  const signed = v => `${v >= 0 ? '+' : '−'}${num(Math.abs(v))}`;

  // Index the stored forecast breakdown (trend / seasonality / customer growth, MWh) by "year-month".
  function breakdownIndex(rows) {
    const index = {};
    (rows || []).forEach(r => { index[`${r.year}-${r.month}`] = r; });
    return index;
  }

  // Plain-language hover card for one chart month, built only from the model's own numbers.
  function explainMonth({ actual, forecast, breakdown, lastYear }) {
    const row = actual || forecast;
    const title = `${MONTH_NAMES[row.month - 1]} ${row.year}`;
    if (actual) {
      let change = '';
      if (lastYear && Number.isFinite(lastYear.energy_mwh) && lastYear.energy_mwh > 0) {
        const diff = actual.energy_mwh - lastYear.energy_mwh;
        change = `<p>${signed(diff)} MWh (${signed((diff / lastYear.energy_mwh) * 100)}%) compared with ${esc(MONTH_NAMES[row.month - 1])} ${esc(lastYear.year)}.</p>`;
      }
      return `<b>${esc(title)}: ${esc(num(actual.energy_mwh))} MWh actual</b>${change}<small>Real GUIMELCO data</small>`;
    }
    const lines = [];
    if (breakdown && Number.isFinite(breakdown.trend)) {
      lines.push(`<p>The long-term <b>trend</b> accounts for about ${esc(num(breakdown.trend))} MWh.</p>`);
      const season = breakdown.seasonality;
      if (Number.isFinite(season) && Math.abs(season) >= 1) {
        const high = season > 0;
        lines.push(`<p>${esc(MONTH_NAMES[row.month - 1])} is a <b>${high ? 'higher' : 'lower'}-demand month</b>: the yearly pattern ${high ? 'adds' : 'removes'} about ${esc(num(Math.abs(season)))} MWh.</p>`);
      }
      const growth = breakdown.customer_growth;
      if (Number.isFinite(growth) && Math.abs(growth) >= 1) {
        lines.push(`<p><b>Customer growth</b> adds about ${esc(signed(growth))} MWh.</p>`);
      }
    } else {
      lines.push('<p>No breakdown is stored for this month.</p>');
    }
    return `<b>${esc(title)}: ${esc(num(forecast.forecast_mwh))} MWh forecast</b>
      <p class="chart-tip-range">80% range ${esc(num(forecast.lo80))}–${esc(num(forecast.hi80))} MWh</p>
      ${lines.join('')}<small>From the forecast breakdown (trend + seasonality)</small>`;
  }

  // Chart tooltip for an actual-then-forecast chart: points 0..history.length-1 are actuals, the rest forecasts.
  // allHistory is the full actual series, used to find the same month a year earlier.
  function forecastTooltip(allHistory, history, forecast, breakdownRows) {
    const byMonth = breakdownIndex(allHistory);
    const parts = breakdownIndex(breakdownRows);
    return index => {
      if (index < history.length) {
        const actual = history[index];
        return explainMonth({ actual, lastYear: byMonth[`${actual.year - 1}-${actual.month}`] });
      }
      const row = forecast[index - history.length];
      return row ? explainMonth({ forecast: row, breakdown: parts[`${row.year}-${row.month}`] }) : null;
    };
  }

  window.ElectroAnalytics = { dataBadge, modelCard, emptyState, initInfoButtons, breakdownIndex, explainMonth, forecastTooltip };
})();
