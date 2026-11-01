(function () {
  'use strict';

  const state = { user:null, categories:[], appliances:[], consumption:[] };
  const $ = selector => document.querySelector(selector);

  ElectroShell.mount('user-portal', 'My Energy Portal', { dateRange:false });

  function sourceLabel(value) {
    return {
      nameplate_label:'Nameplate label',
      user_manual:'User manual',
      retailer_specs:'Retailer specifications',
      manual_estimate:'Manual estimate',
      electric_bill:'Electric bill',
      meter_reading:'Meter reading',
      utility_portal:'Utility portal',
      manual_entry:'Manual entry'
    }[value] || ElectroAPI.titleCase(value);
  }

  function actionButtons(type, id) {
    return `<div class="row-actions portal-actions">
      <button type="button" data-edit-${type}="${id}" title="Edit record" aria-label="Edit record"><i data-feather="edit-2"></i></button>
      <button type="button" class="reject" data-delete-${type}="${id}" title="Delete record" aria-label="Delete record"><i data-feather="trash-2"></i></button>
    </div>`;
  }

  function renderAppliances() {
    const body = $('#appliance-table-body');
    if (!state.appliances.length) {
      body.innerHTML = `<tr><td colspan="6"><div class="empty-table"><i data-feather="zap"></i><b>No appliances yet</b><span>Add your household appliances to support consumption forecasting.</span></div></td></tr>`;
      feather.replace({ 'stroke-width':2 });
      return;
    }
    body.innerHTML = state.appliances.map(item=>`
      <tr>
        <td data-label="Appliance"><div class="record-title"><b>${ElectroAPI.escapeHTML(item.appliance_name)}</b><small>${ElectroAPI.escapeHTML([item.brand,item.model,item.category_name].filter(Boolean).join(' · '))}</small></div></td>
        <td data-label="Power & Usage"><b>${Number(item.power_rating_watts).toLocaleString()} W</b><div class="text-sm text-muted">Qty ${item.quantity} · ${item.avg_daily_usage_hours} hr/day</div></td>
        <td data-label="Estimated Load"><b>${Number(item.estimated_daily_kwh).toFixed(2)} kWh/day</b><div class="text-sm text-muted">${(Number(item.estimated_daily_kwh)*30).toFixed(1)} kWh/month</div></td>
        <td data-label="Source">${ElectroAPI.escapeHTML(sourceLabel(item.source_of_info))}</td>
        <td data-label="Status"><span class="badge verified"><span class="badge-dot"></span>In Inventory</span></td>
        <td data-label="Actions">${actionButtons('appliance',item.inventory_id)}</td>
      </tr>`).join('');
    feather.replace({ 'stroke-width':2 });
  }

  function renderConsumption() {
    const body = $('#consumption-table-body');
    if (!state.consumption.length) {
      body.innerHTML = `<tr><td colspan="6"><div class="empty-table"><i data-feather="bar-chart-2"></i><b>No monthly records yet</b><span>Add the consumption shown on your electricity bill.</span></div></td></tr>`;
      feather.replace({ 'stroke-width':2 });
      return;
    }
    body.innerHTML = state.consumption.map(item=>`
      <tr>
        <td data-label="Billing Month"><div class="record-title"><b>${ElectroAPI.formatMonth(item.billing_month)}</b><small>Updated ${ElectroAPI.formatDate(item.updated_at)}</small></div></td>
        <td data-label="Consumption"><b>${Number(item.consumption_kwh).toLocaleString(undefined,{maximumFractionDigits:2})} kWh</b>${item.meter_reading != null ? `<div class="text-sm text-muted">Meter ${Number(item.meter_reading).toLocaleString()}</div>`:''}</td>
        <td data-label="Bill Amount">${item.bill_amount_php != null ? `₱${Number(item.bill_amount_php).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`:'—'}</td>
        <td data-label="Source">${ElectroAPI.escapeHTML(sourceLabel(item.source_of_info))}</td>
        <td data-label="Status">${ElectroAPI.statusBadge(item.verification_status)}${item.reviewer_notes ? `<div class="review-note">${ElectroAPI.escapeHTML(item.reviewer_notes)}</div>`:''}</td>
        <td data-label="Actions">${actionButtons('consumption',item.consumption_id)}</td>
      </tr>`).join('');
    feather.replace({ 'stroke-width':2 });
  }

  function renderSummary(summary) {
    $('#stat-appliances').textContent = summary.appliance_count;
    $('#stat-daily').textContent = `${Number(summary.estimated_daily_kwh).toFixed(2)} kWh`;
    $('#stat-pending').textContent = summary.pending_count;
    $('#stat-latest').textContent = summary.latest_consumption
      ? `${Number(summary.latest_consumption.consumption_kwh).toFixed(1)} kWh`
      : '—';
    $('#stat-latest-month').textContent = summary.latest_consumption
      ? `${ElectroAPI.formatMonth(summary.latest_consumption.billing_month)} · ${ElectroAPI.titleCase(summary.latest_consumption.verification_status)}`
      : 'No record yet';
    $('#readiness-value').textContent = `${summary.data_readiness_pct}%`;
    $('#readiness-detail').textContent = `${summary.approved_count} of ${summary.total_submissions} records approved`;
    $('#readiness-bar').style.width = `${summary.data_readiness_pct}%`;
  }

  async function loadData() {
    const [summary, appliances, consumption] = await Promise.all([
      ElectroAPI.request('/api/portal/summary'),
      ElectroAPI.request('/api/my-appliances'),
      ElectroAPI.request('/api/consumption')
    ]);
    state.appliances = appliances.appliances;
    state.consumption = consumption.records;
    renderSummary(summary.summary);
    renderAppliances();
    renderConsumption();
  }

  function openModal(type, record) {
    const isAppliance = type === 'appliance';
    if (isAppliance) {
      window.location.href = `my-appliances.html?edit=${record?.inventory_id || ''}`;
      return;
    }
    $('#modal-title').textContent = `${record ? 'Edit' : 'Add'} ${isAppliance ? 'Appliance' : 'Monthly Record'}`;
    $('#modal-eyebrow').textContent = record ? 'Update crowdsourced record' : 'New crowdsourced record';
    $('#appliance-form').hidden = !isAppliance;
    $('#consumption-form').hidden = isAppliance;
    $('#record-modal').hidden = false;
    document.body.classList.add('modal-open');

    if (isAppliance) {
      $('#appliance-form').reset();
      $('#appliance-id').value = record?.appliance_id || '';
      $('#appliance-name').value = record?.appliance_name || '';
      $('#appliance-category').value = record?.category_id || state.categories[0]?.category_id || '';
      $('#appliance-brand').value = record?.brand || '';
      $('#appliance-model').value = record?.model || '';
      $('#appliance-watts').value = record?.power_rating_watts || '';
      $('#appliance-quantity').value = record?.quantity || 1;
      $('#appliance-hours').value = record?.avg_daily_usage_hours ?? '';
      $('#appliance-source').value = record?.source_of_info || 'nameplate_label';
      $('#appliance-name').focus();
    } else {
      $('#consumption-form').reset();
      $('#consumption-id').value = record?.consumption_id || '';
      $('#billing-month').max = new Date().toISOString().slice(0,7);
      $('#billing-month').value = record?.billing_month || '';
      $('#consumption-kwh').value = record?.consumption_kwh || '';
      $('#bill-amount').value = record?.bill_amount_php ?? '';
      $('#meter-reading').value = record?.meter_reading ?? '';
      $('#consumption-source').value = record?.source_of_info || 'electric_bill';
      $('#billing-month').focus();
    }
    feather.replace({ 'stroke-width':2 });
  }

  function closeModal() {
    $('#record-modal').hidden = true;
    document.body.classList.remove('modal-open');
  }

  function formData(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  async function submitAppliance(event) {
    event.preventDefault();
    const id = $('#appliance-id').value;
    const button = $('#save-appliance');
    button.disabled = true;
    try {
      await ElectroAPI.request(id ? `/api/appliances/${id}` : '/api/appliances', {
        method:id ? 'PATCH' : 'POST',
        body:formData(event.currentTarget)
      });
      closeModal();
      await loadData();
      ElectroAPI.notify(`Appliance ${id ? 'updated' : 'submitted'} successfully.`);
    } catch (error) {
      ElectroAPI.notify(error.message,'error');
    } finally {
      button.disabled = false;
    }
  }

  async function submitConsumption(event) {
    event.preventDefault();
    const id = $('#consumption-id').value;
    const button = $('#save-consumption');
    button.disabled = true;
    try {
      await ElectroAPI.request(id ? `/api/consumption/${id}` : '/api/consumption', {
        method:id ? 'PATCH' : 'POST',
        body:formData(event.currentTarget)
      });
      closeModal();
      await loadData();
      ElectroAPI.notify(`Monthly record ${id ? 'updated' : 'submitted'} successfully.`);
    } catch (error) {
      ElectroAPI.notify(error.message,'error');
    } finally {
      button.disabled = false;
    }
  }

  async function deleteRecord(type,id) {
    const label = type === 'appliance' ? 'appliance' : 'monthly consumption record';
    if (!(await ElectroAPI.confirm(`Delete this ${label}? This action cannot be undone.`, { title: 'Delete record?' }))) return;
    try {
      await ElectroAPI.request(type === 'appliance' ? `/api/my-appliances/${id}` : `/api/consumption/${id}`, { method:'DELETE' });
      await loadData();
      ElectroAPI.notify(`${ElectroAPI.titleCase(label)} deleted.`);
    } catch (error) {
      ElectroAPI.notify(error.message,'error');
    }
  }

  document.addEventListener('click', event=>{
    const target = event.target.closest('button');
    if (!target) return;
    if (target.matches('[data-close-modal]')) closeModal();
    if (target.dataset.editAppliance) openModal('appliance',state.appliances.find(item=>String(item.inventory_id)===target.dataset.editAppliance));
    if (target.dataset.editConsumption) openModal('consumption',state.consumption.find(item=>String(item.consumption_id)===target.dataset.editConsumption));
    if (target.dataset.deleteAppliance) deleteRecord('appliance',target.dataset.deleteAppliance);
    if (target.dataset.deleteConsumption) deleteRecord('consumption',target.dataset.deleteConsumption);
  });

  $('#quick-add-appliance').addEventListener('click',()=>{ window.location.href='my-appliances.html?add=1'; });
  $('#add-appliance').addEventListener('click',()=>{ window.location.href='my-appliances.html?add=1'; });
  $('#add-consumption').addEventListener('click',()=>openModal('consumption'));
  $('#appliance-form').addEventListener('submit',submitAppliance);
  $('#consumption-form').addEventListener('submit',submitConsumption);
  document.addEventListener('keydown',event=>{ if (event.key==='Escape' && !$('#record-modal').hidden) closeModal(); });

  (async function init() {
    try {
      state.user = await ElectroAPI.requireRole(['household']);
      $('#welcome-title').textContent = `Welcome back, ${state.user.full_name.split(' ')[0]}`;
      const h = state.user.household || {};
      $('#household-meta').textContent = [h.barangay,h.municipality,h.province,h.meter_number ? `Meter ${h.meter_number}` : ''].filter(Boolean).join(' · ');
      const categoryPayload = await ElectroAPI.request('/api/categories');
      state.categories = categoryPayload.categories;
      $('#appliance-category').innerHTML = state.categories.map(category=>`<option value="${category.category_id}">${ElectroAPI.escapeHTML(category.category_name)}</option>`).join('');
      await loadData();
      const target = location.hash && document.querySelector(location.hash);
      if (target) target.scrollIntoView({ block:'start' });
    } catch (error) {
      if (error.status !== 401) ElectroAPI.notify(error.message,'error');
    }
  })();
})();
