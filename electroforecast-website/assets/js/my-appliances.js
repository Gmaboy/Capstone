(function () {
  'use strict';

  const state = {
    appliances:[], deletedAppliances:[], submissions:[], categories:[], catalog:[],
    selectedCatalog:null, editingInventory:null, selectedDeleted:new Set()
  };
  const $ = selector => document.querySelector(selector);

  ElectroShell.mount('appliances', 'My Appliances', { dateRange:false });

  function sourceLabel(value) {
    return {
      nameplate_label:'Nameplate label', user_manual:'User manual',
      retailer_specs:'Retailer specifications', manual_estimate:'Manual estimate'
    }[value] || ElectroAPI.titleCase(value);
  }

  function renderSummary() {
    const daily = state.appliances.reduce((total,item)=>total + Number(item.estimated_daily_kwh),0);
    $('#my-count').textContent = state.appliances.length;
    $('#my-daily').textContent = `${daily.toFixed(2)} kWh`;
    $('#my-pending').textContent = state.submissions.filter(item=>item.verification_status==='pending').length;
  }

  // Every household appliance comes from an admin-approved rating, so each name carries a verified mark.
  const VERIFIED_ICON = '<span class="verified-icon" role="img" aria-label="Verified rating" title="Verified rating (approved by an administrator)">'
    + '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 1.5l2.4 1.8 3-.2 1 2.8 2.6 1.5-.8 2.9 1.3 2.7-2.3 1.9-.3 3-2.9.6-1.6 2.5-2.8-1L12 22.5l-2.4-1.8-3 .2-1-2.8-2.6-1.5.8-2.9L2.5 11l2.3-1.9.3-3 2.9-.6 1.6-2.5 2.8 1z"/>'
    + '<path d="M8 12.2l2.6 2.6L16.2 9.2" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>';

  function renderAppliances() {
    const body = $('#my-appliance-body');
    // Every row here is in the household inventory, so the status is shown once in the card header.
    $('#inventory-count').textContent = state.appliances.length;
    body.innerHTML = state.appliances.length ? state.appliances.map(item=>`
      <tr>
        <td data-label="Appliance"><div class="record-title"><b class="name-verified">${ElectroAPI.escapeHTML(item.appliance_name)}${VERIFIED_ICON}</b><small>${ElectroAPI.escapeHTML([item.brand,item.model,item.category_name,sourceLabel(item.source_of_info)].filter(Boolean).join(' · '))}</small></div></td>
        <td data-label="Power & Usage"><b>${Number(item.power_rating_watts).toLocaleString()} W</b><div class="text-sm text-muted">Qty ${item.quantity} · ${item.avg_daily_usage_hours} hr/day</div></td>
        <td data-label="Estimated Load"><b>${Number(item.estimated_daily_kwh).toFixed(2)} kWh/day</b><div class="text-sm text-muted">${(Number(item.estimated_daily_kwh)*30).toFixed(1)} kWh/month</div></td>
        <td data-label="Actions"><div class="row-actions portal-actions"><button type="button" data-edit-inventory="${item.inventory_id}" aria-label="Edit ${ElectroAPI.escapeHTML(item.appliance_name)} usage"><i data-feather="edit-2"></i></button><button type="button" class="reject" data-delete-inventory="${item.inventory_id}" aria-label="Remove ${ElectroAPI.escapeHTML(item.appliance_name)} from My Appliances"><i data-feather="trash-2"></i></button></div></td>
      </tr>`).join('')
      : `<tr><td colspan="4"><div class="empty-table"><i data-feather="zap"></i><b>No household appliances yet</b><span>Choose an approved rating to start calculating your estimated load.</span></div></td></tr>`;
  }

  function renderSubmissionStage() {
    const actionable = state.submissions.filter(item =>
      item.verification_status !== 'approved' ||
      (!Number(item.in_inventory) && !Number(item.recently_deleted))
    );
    $('#submission-stage-list').innerHTML = actionable.length ? actionable.map(item=>{
      const approved = item.verification_status === 'approved';
      const statusText = approved
        ? 'Approved by the administrator. Add it only if this appliance is used in your household.'
        : item.verification_status === 'pending'
          ? 'Awaiting administrator validation. It is not included in your household load.'
          : (item.reviewer_notes || 'Update the contribution before resubmitting.');
      return `<article class="submission-stage-item ${item.verification_status}">
        <span class="submission-stage-icon"><i data-feather="${approved ? 'check-circle' : item.verification_status === 'pending' ? 'clock' : 'alert-circle'}"></i></span>
        <div class="submission-stage-copy"><div class="submission-stage-title"><b>${ElectroAPI.escapeHTML(item.appliance_name)}</b>${ElectroAPI.statusBadge(item.verification_status)}</div><small>${ElectroAPI.escapeHTML([item.brand,item.model,item.category_name].filter(Boolean).join(' · '))} · ${Number(item.power_rating_watts).toLocaleString()} W</small><p>${ElectroAPI.escapeHTML(statusText)}</p></div>
        ${approved ? `<button class="btn btn-primary btn-sm" type="button" data-add-approved="${item.appliance_id}">Add to My Appliances</button>` : `<a class="btn btn-secondary btn-sm" href="my-submissions.html">${item.verification_status === 'rejected' ? 'Review Details' : 'View Submission'}</a>`}
      </article>`;
    }).join('') : `<div class="empty-stage"><i data-feather="check-circle"></i><span>No pending or ready-to-add appliance submissions.</span></div>`;
  }

  function renderRecentlyDeleted() {
    $('#recently-deleted-count').textContent = state.deletedAppliances.length;
    $('#recently-deleted-list').innerHTML = state.deletedAppliances.length
      ? state.deletedAppliances.map(item=>`
        <article class="recently-deleted-item">
          <label class="recently-deleted-selection"><input type="checkbox" data-select-deleted-inventory="${item.inventory_id}" aria-label="Select ${ElectroAPI.escapeHTML(item.appliance_name)} for permanent deletion"></label>
          <span class="recently-deleted-icon"><i data-feather="archive"></i></span>
          <div class="recently-deleted-copy">
            <b>${ElectroAPI.escapeHTML(item.appliance_name)}</b>
            <small>${ElectroAPI.escapeHTML([item.brand,item.model,item.category_name].filter(Boolean).join(' · '))}</small>
            <span>Removed ${ElectroAPI.formatDate(item.deleted_at)}</span>
          </div>
          <button class="btn btn-primary btn-sm" type="button" data-restore-inventory="${item.inventory_id}"><i data-feather="rotate-ccw"></i> Restore</button>
        </article>`).join('')
      : `<div class="empty-stage"><i data-feather="archive"></i><b>No recently deleted appliances</b><span>Appliances removed from your household list will appear here.</span></div>`;
    syncDeletedSelection();
  }

  function syncDeletedSelection() {
    const available = new Set(state.deletedAppliances.map(item=>String(item.inventory_id)));
    state.selectedDeleted = new Set([...state.selectedDeleted].filter(id=>available.has(String(id))));
    document.querySelectorAll('[data-select-deleted-inventory]').forEach(input=>{
      input.checked = state.selectedDeleted.has(String(input.dataset.selectDeletedInventory));
    });
    const selectedCount = state.selectedDeleted.size;
    const allCheckbox = $('#select-all-deleted-appliances');
    allCheckbox.checked = state.deletedAppliances.length > 0 && selectedCount === state.deletedAppliances.length;
    allCheckbox.indeterminate = selectedCount > 0 && selectedCount < state.deletedAppliances.length;
    allCheckbox.disabled = state.deletedAppliances.length === 0;
    $('#selected-appliance-count').textContent = selectedCount;
    $('#delete-selected-appliances').disabled = selectedCount === 0;
  }

  function renderAll() {
    renderAppliances();
    renderSubmissionStage();
    renderRecentlyDeleted();
    renderSummary();
    feather.replace({ 'stroke-width':2 });
  }

  function catalogMatches() {
    const term = $('#modal-catalog-search').value.trim().toLowerCase();
    return state.catalog.filter(item =>
      [item.appliance_name,item.brand,item.model,item.category_name].filter(Boolean).join(' ').toLowerCase().includes(term)
    );
  }

  function renderCatalogResults() {
    const records = catalogMatches();
    $('#modal-catalog-results').innerHTML = records.length ? records.map(item=>`
      <button class="catalog-result" type="button" data-select-catalog="${item.catalog_id}">
        <span class="catalog-result-icon"><i data-feather="zap"></i></span>
        <span class="catalog-result-copy"><b>${ElectroAPI.escapeHTML(item.appliance_name)}</b><small>${ElectroAPI.escapeHTML([item.brand,item.model,item.category_name].filter(Boolean).join(' · '))}</small></span>
        <span class="catalog-result-rating"><b>${Number(item.power_rating_watts).toLocaleString()} W</b><small>${item.contributor_count} community ${item.contributor_count === 1 ? 'match' : 'matches'}</small></span>
        <i data-feather="chevron-right"></i>
      </button>`).join('')
      : `<div class="empty-catalog compact"><i data-feather="search"></i><b>No approved matches</b><span>Enter a new appliance contribution instead.</span></div>`;
    feather.replace({ 'stroke-width':2 });
  }

  function setTechnicalLock(locked) {
    ['#manual-name','#manual-brand','#manual-model','#manual-watts'].forEach(selector=>{ $(selector).readOnly = locked; });
    $('#manual-category').disabled = locked;
    $('#manual-source').disabled = locked;
    $('#manual-lock-note').hidden = !locked;
  }

  function setMode(mode) {
    document.querySelectorAll('[data-add-mode]').forEach(button=>{
      const active = button.dataset.addMode === mode;
      button.classList.toggle('active',active);
      button.setAttribute('aria-selected',String(active));
    });
    $('#catalog-add-pane').hidden = mode !== 'catalog';
    $('#manual-appliance-form').hidden = mode !== 'manual';
    $('#library-title').textContent = mode === 'catalog' ? 'Choose an approved appliance' : 'Enter a new appliance contribution';
    if (mode === 'catalog') $('#modal-catalog-search').focus(); else $('#manual-name').focus();
  }

  function openLibrary(mode='catalog') {
    state.selectedCatalog = null;
    state.editingInventory = null;
    $('#appliance-library-modal').hidden = false;
    $('#add-mode-tabs').hidden = false;
    document.body.classList.add('modal-open');
    $('#catalog-picker').hidden = false;
    $('#catalog-customize-form').hidden = true;
    $('#modal-catalog-search').value = '';
    $('#manual-appliance-form').reset();
    $('#manual-appliance-id').value = '';
    $('#save-manual-appliance').innerHTML = '<i data-feather="send"></i> Submit for Validation';
    setTechnicalLock(false);
    $('#manual-appliance-form').classList.remove('editing');
    $('#manual-confirm-text').textContent = 'I confirm that this information is accurate to the best of my knowledge.';
    $('#library-eyebrow').textContent = 'Add appliance';
    renderCatalogResults();
    setMode(mode);
    feather.replace({ 'stroke-width':2 });
  }

  function closeLibrary() {
    $('#appliance-library-modal').hidden = true;
    document.body.classList.remove('modal-open');
  }

  function openRecentlyDeleted() {
    $('#recently-deleted-modal').hidden = false;
    document.body.classList.add('modal-open');
    feather.replace({ 'stroke-width':2 });
  }

  function closeRecentlyDeleted() {
    $('#recently-deleted-modal').hidden = true;
    document.body.classList.remove('modal-open');
  }

  function selectApprovedRecord(item) {
    state.selectedCatalog = item;
    $('#selected-catalog-id').value = item.catalog_id;
    // Same read-only summary as the edit dialog.
    $('#catalog-summary-name').innerHTML = `${ElectroAPI.escapeHTML(item.appliance_name)}${VERIFIED_ICON}`;
    $('#catalog-summary-meta').textContent = [item.brand,item.model,item.category_name].filter(Boolean).join(' · ');
    $('#catalog-summary-watts').textContent = `${Number(item.power_rating_watts).toLocaleString()} W`;
    $('#catalog-summary-source').textContent = sourceLabel(item.strongest_source || item.source_of_info);
    $('#catalog-quantity').value = Math.max(1,Math.round(Number(item.community_avg_quantity || item.quantity) || 1));
    $('#catalog-hours').value = Number(item.community_avg_hours ?? item.avg_daily_usage_hours) || '';
    $('#catalog-confirm').checked = false;
    $('#catalog-picker').hidden = true;
    $('#catalog-customize-form').hidden = false;
    updateLoadPreview();
    feather.replace({ 'stroke-width':2 });
    $('#catalog-quantity').focus();
  }

  function selectCatalog(catalogId) {
    const item = state.catalog.find(record=>String(record.catalog_id)===String(catalogId));
    if (item) selectApprovedRecord(item);
  }

  function addApprovedSubmission(submissionId) {
    const submission = state.submissions.find(item=>String(item.appliance_id)===String(submissionId));
    if (!submission || submission.verification_status !== 'approved') return;
    openLibrary('catalog');
    selectApprovedRecord({...submission,catalog_id:submission.appliance_id,strongest_source:submission.source_of_info});
  }

  function updateLoadPreview() {
    if (!state.selectedCatalog) return;
    const quantity = Number($('#catalog-quantity').value) || 0;
    const hours = Number($('#catalog-hours').value) || 0;
    $('#catalog-load-preview').textContent = `${(Number(state.selectedCatalog.power_rating_watts)*quantity*hours/1000).toFixed(2)} kWh/day`;
  }

  function openEditInventory(record) {
    openLibrary('manual');
    state.editingInventory = record;
    $('#add-mode-tabs').hidden = true;
    $('#library-eyebrow').textContent = 'Household inventory';
    $('#library-title').textContent = 'Edit quantity and usage';
    $('#manual-appliance-id').value = record.inventory_id;
    $('#manual-name').value = record.appliance_name;
    $('#manual-category').value = record.category_id;
    $('#manual-brand').value = record.brand || '';
    $('#manual-model').value = record.model || '';
    $('#manual-watts').value = record.power_rating_watts;
    $('#manual-quantity').value = record.quantity;
    $('#manual-hours').value = record.avg_daily_usage_hours;
    $('#manual-source').value = record.source_of_info;
    $('#manual-confirm').checked = false;
    $('#manual-lock-note').hidden = false;
    $('#manual-lock-note span').textContent = 'Only household quantity and average hours per day can be changed. Your original submission is not modified.';
    setTechnicalLock(true);
    // Only quantity and hours are editable, so the technical fields give way to a read-only summary.
    $('#manual-appliance-form').classList.add('editing');
    $('#edit-summary-name').innerHTML = `${ElectroAPI.escapeHTML(record.appliance_name)}${VERIFIED_ICON}`;
    $('#edit-summary-meta').textContent = [record.brand,record.model,record.category_name].filter(Boolean).join(' · ');
    $('#edit-summary-watts').textContent = `${Number(record.power_rating_watts).toLocaleString()} W`;
    $('#edit-summary-source').textContent = sourceLabel(record.source_of_info);
    $('#manual-confirm-text').textContent = 'I confirm that the quantity and usage hours match my household.';
    updateEditLoadPreview();
    $('#save-manual-appliance').innerHTML = '<i data-feather="save"></i> Save Household Usage';
    feather.replace({ 'stroke-width':2 });
    $('#manual-quantity').focus();
  }

  function updateEditLoadPreview() {
    if (!state.editingInventory) return;
    const quantity = Number($('#manual-quantity').value) || 0;
    const hours = Number($('#manual-hours').value) || 0;
    $('#edit-load-preview').textContent = `${(Number(state.editingInventory.power_rating_watts)*quantity*hours/1000).toFixed(2)} kWh/day`;
  }

  async function loadData() {
    const [inventoryPayload,deletedPayload,submissionPayload,catalogPayload] = await Promise.all([
      ElectroAPI.request('/api/my-appliances'),
      ElectroAPI.request('/api/my-appliances/recently-deleted'),
      ElectroAPI.request('/api/appliances'),
      ElectroAPI.request('/api/crowdsource/appliances')
    ]);
    state.appliances = inventoryPayload.appliances;
    state.deletedAppliances = deletedPayload.appliances;
    state.submissions = submissionPayload.appliances;
    state.catalog = catalogPayload.appliances;
    renderAll();
  }

  async function submitCatalog(event) {
    event.preventDefault();
    const button = $('#save-catalog-appliance');
    button.disabled = true;
    try {
      await ElectroAPI.request(`/api/my-appliances/from-submission/${$('#selected-catalog-id').value}`, {method:'POST',body:{quantity:$('#catalog-quantity').value,avg_daily_usage_hours:$('#catalog-hours').value}});
      closeLibrary();
      await loadData();
      ElectroAPI.notify('Appliance added to your household inventory.');
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
    finally { button.disabled = false; }
  }

  async function submitManual(event) {
    event.preventDefault();
    const button = $('#save-manual-appliance');
    button.disabled = true;
    try {
      if (state.editingInventory) {
        await ElectroAPI.request(`/api/my-appliances/${state.editingInventory.inventory_id}`, {method:'PATCH',body:{quantity:$('#manual-quantity').value,avg_daily_usage_hours:$('#manual-hours').value}});
        ElectroAPI.notify('Household quantity and usage updated.');
      } else {
        await ElectroAPI.request('/api/appliances', {method:'POST',body:Object.fromEntries(new FormData(event.currentTarget).entries())});
        ElectroAPI.notify('New appliance submitted for administrator validation.');
      }
      closeLibrary();
      await loadData();
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
    finally { button.disabled = false; }
  }

  async function deleteInventory(id) {
    const record = state.appliances.find(item=>String(item.inventory_id)===String(id));
    if (!record || !(await ElectroAPI.confirm(`Remove ${record.appliance_name} from your household inventory? Your contribution history will remain.`, { title: 'Remove appliance?', confirmLabel: 'Remove' }))) return;
    try {
      await ElectroAPI.request(`/api/my-appliances/${id}`,{method:'DELETE'});
      await loadData();
      ElectroAPI.notify('Moved to Recently Deleted. It will not return to Submitted Appliances.');
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
  }

  async function restoreInventory(id) {
    const record = state.deletedAppliances.find(item=>String(item.inventory_id)===String(id));
    if (!record) return;
    try {
      await ElectroAPI.request(`/api/my-appliances/${id}/restore`,{method:'POST'});
      await loadData();
      if (!state.deletedAppliances.length) closeRecentlyDeleted();
      ElectroAPI.notify(`${record.appliance_name} restored to your household list.`);
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
  }

  async function permanentlyDeleteSelected() {
    const inventoryIds = [...state.selectedDeleted].map(Number);
    if (!inventoryIds.length || !(await ElectroAPI.confirm(`Permanently delete ${inventoryIds.length} selected appliance${inventoryIds.length === 1 ? '' : 's'}? This cannot be undone.`, { title: 'Delete permanently?', confirmLabel: 'Delete permanently' }))) return;
    const button = $('#delete-selected-appliances');
    button.disabled = true;
    try {
      const payload = await ElectroAPI.request('/api/my-appliances/permanent',{method:'DELETE',body:{inventory_ids:inventoryIds}});
      state.selectedDeleted.clear();
      await loadData();
      ElectroAPI.notify(`${payload.deleted_count} appliance${payload.deleted_count === 1 ? '' : 's'} permanently deleted.`);
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
    finally { syncDeletedSelection(); }
  }

  document.addEventListener('click',event=>{
    const button = event.target.closest('button');
    if (!button) return;
    if (button.matches('[data-close-library]')) closeLibrary();
    if (button.matches('[data-close-recently-deleted]')) closeRecentlyDeleted();
    if (button.dataset.addMode) setMode(button.dataset.addMode);
    if (button.dataset.selectCatalog) selectCatalog(button.dataset.selectCatalog);
    if (button.dataset.addApproved) addApprovedSubmission(button.dataset.addApproved);
    if (button.dataset.editInventory) openEditInventory(state.appliances.find(item=>String(item.inventory_id)===button.dataset.editInventory));
    if (button.dataset.deleteInventory) deleteInventory(button.dataset.deleteInventory);
    if (button.dataset.restoreInventory) restoreInventory(button.dataset.restoreInventory);
  });
  document.addEventListener('change',event=>{
    const input = event.target.closest('[data-select-deleted-inventory]');
    if (!input) return;
    const id = String(input.dataset.selectDeletedInventory);
    if (input.checked) state.selectedDeleted.add(id); else state.selectedDeleted.delete(id);
    syncDeletedSelection();
  });
  $('#open-add-appliance').addEventListener('click',()=>openLibrary());
  $('#open-add-appliance-secondary').addEventListener('click',()=>openLibrary());
  $('#open-recently-deleted').addEventListener('click',openRecentlyDeleted);
  $('#select-all-deleted-appliances').addEventListener('change',event=>{
    state.selectedDeleted = event.currentTarget.checked
      ? new Set(state.deletedAppliances.map(item=>String(item.inventory_id)))
      : new Set();
    syncDeletedSelection();
  });
  $('#delete-selected-appliances').addEventListener('click',permanentlyDeleteSelected);
  $('#modal-catalog-search').addEventListener('input',renderCatalogResults);
  $('#back-to-catalog').addEventListener('click',()=>{ state.selectedCatalog=null; $('#catalog-customize-form').hidden=true; $('#catalog-picker').hidden=false; $('#modal-catalog-search').focus(); });
  $('#catalog-quantity').addEventListener('input',updateLoadPreview);
  $('#manual-quantity').addEventListener('input',updateEditLoadPreview);
  $('#manual-hours').addEventListener('input',updateEditLoadPreview);
  $('#catalog-hours').addEventListener('input',updateLoadPreview);
  $('#catalog-customize-form').addEventListener('submit',submitCatalog);
  $('#manual-appliance-form').addEventListener('submit',submitManual);
  document.addEventListener('keydown',event=>{
    if (event.key !== 'Escape') return;
    if (!$('#appliance-library-modal').hidden) closeLibrary();
    if (!$('#recently-deleted-modal').hidden) closeRecentlyDeleted();
  });

  (async function init() {
    try {
      await ElectroAPI.requireRole(['household']);
      const categories = await ElectroAPI.request('/api/categories');
      state.categories = categories.categories;
      $('#manual-category').innerHTML = state.categories.map(item=>`<option value="${item.category_id}">${ElectroAPI.escapeHTML(item.category_name)}</option>`).join('');
      await loadData();
      const params = new URLSearchParams(location.search);
      if (params.has('catalog')) { openLibrary(); selectCatalog(params.get('catalog')); }
      else if (params.has('submission')) addApprovedSubmission(params.get('submission'));
      else if (params.has('edit')) {
        const record = state.appliances.find(item=>String(item.inventory_id)===params.get('edit'));
        if (record) openEditInventory(record);
      } else if (params.has('add')) openLibrary();
    } catch (error) { if (error.status !== 401) ElectroAPI.notify(error.message,'error'); }
  })();
})();
