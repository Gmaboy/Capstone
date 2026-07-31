(function () {
  'use strict';

  const state = { appliances: [], categories: [] };
  const $ = selector => document.querySelector(selector);

  ElectroShell.mount('crowdsourced', 'Crowdsourced Appliance Ratings', { dateRange:false });

  function sourceLabel(value) {
    return {
      nameplate_label:'Nameplate label',
      user_manual:'User manual',
      retailer_specs:'Retailer specifications',
      manual_estimate:'Manual estimate'
    }[value] || ElectroAPI.titleCase(value);
  }

  function filteredCatalog() {
    const term = $('#catalog-search').value.trim().toLowerCase();
    const category = $('#catalog-category').value;
    return state.appliances.filter(item => {
      const text = [item.appliance_name,item.brand,item.model].filter(Boolean).join(' ').toLowerCase();
      return (!term || text.includes(term)) && (!category || item.category_name === category);
    });
  }

  function render() {
    const records = filteredCatalog();
    $('#catalog-result-count').textContent = `${records.length} approved ${records.length === 1 ? 'rating' : 'ratings'}`;
    $('#catalog-grid').innerHTML = records.length ? records.map(item => `
      <article class="catalog-item">
        <div class="catalog-item-top">
          <span class="catalog-icon"><i data-feather="zap"></i></span>
          ${ElectroAPI.statusBadge('approved')}
        </div>
        <div class="catalog-category">${ElectroAPI.escapeHTML(item.category_name)}</div>
        <h3>${ElectroAPI.escapeHTML(item.appliance_name)}</h3>
        <p>${ElectroAPI.escapeHTML([item.brand,item.model].filter(Boolean).join(' · ') || 'Community appliance record')}</p>
        <div class="catalog-rating-value"><b>${Number(item.power_rating_watts).toLocaleString()} W</b><span>approved power rating</span></div>
        <dl class="catalog-meta">
          <div><dt>Typical use</dt><dd>${Number(item.community_avg_hours).toFixed(1)} hr/day</dd></div>
          <div><dt>Evidence</dt><dd>${ElectroAPI.escapeHTML(sourceLabel(item.strongest_source))}</dd></div>
          <div><dt>Community matches</dt><dd>${item.contributor_count}</dd></div>
        </dl>
        <div class="catalog-contributors"><i data-feather="users"></i><span>Validated from ${ElectroAPI.escapeHTML(item.contributors)}</span></div>
        <a class="btn btn-primary catalog-use" href="my-appliances.html?catalog=${item.catalog_id}">Use This Appliance <i data-feather="arrow-right"></i></a>
      </article>`).join('')
      : `<div class="empty-catalog"><i data-feather="search"></i><b>No approved appliance matches</b><span>Try another name or select a different category.</span></div>`;
    feather.replace({ 'stroke-width':2 });
  }

  (async function init() {
    try {
      await ElectroAPI.requireRole(['household']);
      const [catalogPayload, categoryPayload] = await Promise.all([
        ElectroAPI.request('/api/crowdsource/appliances'),
        ElectroAPI.request('/api/categories')
      ]);
      state.appliances = catalogPayload.appliances;
      state.categories = categoryPayload.categories;
      $('#catalog-category').innerHTML += state.categories.map(item =>
        `<option value="${ElectroAPI.escapeHTML(item.category_name)}">${ElectroAPI.escapeHTML(item.category_name)}</option>`
      ).join('');
      $('#catalog-approved').textContent = state.appliances.length;
      $('#catalog-contributors').textContent = state.appliances.reduce((total,item)=>total + Number(item.contributor_count),0);
      render();
      $('#catalog-search').addEventListener('input',render);
      $('#catalog-category').addEventListener('change',render);
    } catch (error) {
      if (error.status !== 401) ElectroAPI.notify(error.message,'error');
    }
  })();
})();
