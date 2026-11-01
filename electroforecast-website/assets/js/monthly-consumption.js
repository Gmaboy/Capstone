(function () {
  'use strict';

  const state = { records:[], deletedRecords:[], selectedDeleted:new Set(), billPreviewUrl:null };
  const $ = selector => document.querySelector(selector);

  ElectroShell.mount('consumption','Monthly Consumption',{dateRange:false});

  function sourceLabel(value) {
    return {
      electric_bill:'Electric bill', meter_reading:'Meter reading',
      utility_portal:'Utility portal', manual_entry:'Manual entry'
    }[value] || ElectroAPI.titleCase(value);
  }

  function renderRecords() {
    $('#month-count').textContent = state.records.length;
    const latest = state.records[0];
    $('#latest-kwh').textContent = latest ? `${Number(latest.consumption_kwh).toFixed(1)} kWh` : '—';
    $('#latest-month').textContent = latest ? ElectroAPI.formatMonth(latest.billing_month) : 'No record yet';
    $('#month-pending').textContent = state.records.filter(item=>item.verification_status==='pending').length;
    $('#monthly-body').innerHTML = state.records.length ? state.records.map(item=>`
      <tr>
        <td data-label="Billing Month"><div class="record-title"><b>${ElectroAPI.formatMonth(item.billing_month)}</b><small>Updated ${ElectroAPI.formatDate(item.updated_at)}</small></div></td>
        <td data-label="Consumption"><b>${Number(item.consumption_kwh).toLocaleString(undefined,{maximumFractionDigits:2})} kWh</b>${item.meter_reading!=null?`<div class="text-sm text-muted">Meter ${Number(item.meter_reading).toLocaleString()}</div>`:''}</td>
        <td data-label="Bill Amount">${item.bill_amount_php!=null?`₱${Number(item.bill_amount_php).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`:'—'}</td>
        <td data-label="Source">${ElectroAPI.escapeHTML(sourceLabel(item.source_of_info))}</td>
        <td data-label="Status"><div class="status-note-wrap">${ElectroAPI.statusBadge(item.verification_status)}${item.reviewer_notes?`<button type="button" class="reviewer-note-button ${Number(item.reviewer_notes_unread)?'unread':''}" data-view-monthly-reviewer-note="${item.consumption_id}" aria-label="${Number(item.reviewer_notes_unread)?'View unread':'View'} Reviewer Notes for ${ElectroAPI.formatMonth(item.billing_month)}"><i data-feather="message-square"></i><span class="reviewer-note-unread-dot"></span></button>`:''}</div></td>
        <td data-label="Actions"><div class="row-actions portal-actions"><button type="button" data-edit-monthly="${item.consumption_id}" aria-label="Edit ${ElectroAPI.formatMonth(item.billing_month)}"><i data-feather="edit-2"></i></button>${item.verification_status==='approved'?`<button type="button" class="submission-delete-locked" disabled title="Approved bills cannot be deleted" aria-label="Approved ${ElectroAPI.formatMonth(item.billing_month)} bill cannot be deleted"><i data-feather="lock"></i></button>`:`<button type="button" class="reject" data-delete-monthly="${item.consumption_id}" aria-label="Move ${ElectroAPI.formatMonth(item.billing_month)} to Recently Deleted"><i data-feather="trash-2"></i></button>`}</div></td>
      </tr>`).join('')
      : `<tr><td colspan="6"><div class="empty-table"><i data-feather="bar-chart-2"></i><b>No monthly records yet</b><span>Add the consumption shown on your electricity bill.</span></div></td></tr>`;
  }

  function renderDeletedRecords() {
    $('#recently-deleted-monthly-count').textContent = state.deletedRecords.length;
    $('#recently-deleted-monthly-list').innerHTML = state.deletedRecords.length
      ? state.deletedRecords.map(item=>`
        <article class="recently-deleted-item">
          <label class="recently-deleted-selection"><input type="checkbox" data-select-deleted-monthly="${item.consumption_id}" aria-label="Select ${ElectroAPI.formatMonth(item.billing_month)} for permanent deletion"></label>
          <span class="recently-deleted-icon"><i data-feather="archive"></i></span>
          <div class="recently-deleted-copy">
            <b>${ElectroAPI.formatMonth(item.billing_month)}</b>
            <small>${Number(item.consumption_kwh).toLocaleString(undefined,{maximumFractionDigits:2})} kWh · ${ElectroAPI.escapeHTML(sourceLabel(item.source_of_info))}</small>
            <span>Removed ${ElectroAPI.formatDate(item.deleted_at)}</span>
          </div>
          <button class="btn btn-primary btn-sm" type="button" data-restore-monthly="${item.consumption_id}"><i data-feather="rotate-ccw"></i> Restore</button>
        </article>`).join('')
      : `<div class="empty-stage"><i data-feather="archive"></i><b>No recently deleted records</b><span>Monthly records you remove will appear here.</span></div>`;
    syncDeletedSelection();
  }

  function syncDeletedSelection() {
    const available = new Set(state.deletedRecords.map(item=>String(item.consumption_id)));
    state.selectedDeleted = new Set([...state.selectedDeleted].filter(id=>available.has(String(id))));
    document.querySelectorAll('[data-select-deleted-monthly]').forEach(input=>{
      input.checked = state.selectedDeleted.has(String(input.dataset.selectDeletedMonthly));
    });
    const selectedCount = state.selectedDeleted.size;
    const allCheckbox = $('#select-all-deleted-monthly');
    allCheckbox.checked = state.deletedRecords.length > 0 && selectedCount === state.deletedRecords.length;
    allCheckbox.indeterminate = selectedCount > 0 && selectedCount < state.deletedRecords.length;
    allCheckbox.disabled = state.deletedRecords.length === 0;
    $('#selected-monthly-count').textContent = selectedCount;
    $('#delete-selected-monthly').disabled = selectedCount === 0;
  }

  function render() {
    renderRecords();
    renderDeletedRecords();
    feather.replace({'stroke-width':2});
  }

  async function load() {
    const [activePayload,deletedPayload] = await Promise.all([
      ElectroAPI.request('/api/consumption'),
      ElectroAPI.request('/api/consumption/recently-deleted')
    ]);
    state.records = activePayload.records;
    state.deletedRecords = deletedPayload.records;
    render();
  }

  function clearBillImage() {
    if (state.billPreviewUrl) URL.revokeObjectURL(state.billPreviewUrl);
    state.billPreviewUrl = null;
    $('#monthly-bill-image').value = '';
    $('#bill-preview-image').removeAttribute('src');
    $('#bill-preview-name').textContent = '';
    $('#bill-upload-preview').hidden = true;
  }

  function previewBillImage() {
    const file = $('#monthly-bill-image').files[0];
    if (!file) {
      clearBillImage();
      return;
    }
    if (state.billPreviewUrl) URL.revokeObjectURL(state.billPreviewUrl);
    state.billPreviewUrl = URL.createObjectURL(file);
    $('#bill-preview-image').src = state.billPreviewUrl;
    $('#bill-preview-name').textContent = file.name;
    $('#bill-upload-preview').hidden = false;
    feather.replace({'stroke-width':2});
  }

  function open(record) {
    $('#monthly-form').reset();
    clearBillImage();
    $('#monthly-id').value = record?.consumption_id || '';
    $('#monthly-modal-title').textContent = record ? 'Edit Monthly Record' : 'Add Monthly Record';
    $('#monthly-billing-month').max = new Date().toISOString().slice(0,7);
    $('#monthly-billing-month').value = record?.billing_month || '';
    $('#monthly-kwh').value = record?.consumption_kwh || '';
    $('#monthly-amount').value = record?.bill_amount_php ?? '';
    $('#monthly-meter').value = record?.meter_reading ?? '';
    $('#monthly-source').value = record?.source_of_info || 'electric_bill';
    $('#monthly-confirm').checked = false;
    $('#save-monthly').innerHTML = `<i data-feather="${record?'save':'send'}"></i> ${record?'Save & Resubmit':'Submit for Validation'}`;
    $('#monthly-modal').hidden = false;
    document.body.classList.add('modal-open');
    feather.replace({'stroke-width':2});
    $('#monthly-billing-month').focus();
  }

  function close() {
    clearBillImage();
    $('#monthly-modal').hidden = true;
    document.body.classList.remove('modal-open');
  }

  function openRecentlyDeleted() {
    $('#recently-deleted-monthly-modal').hidden = false;
    document.body.classList.add('modal-open');
    feather.replace({'stroke-width':2});
  }

  function closeRecentlyDeleted() {
    $('#recently-deleted-monthly-modal').hidden = true;
    document.body.classList.remove('modal-open');
  }

  async function openReviewerNotes(record) {
    if (!record?.reviewer_notes) return;
    $('#monthly-reviewer-notes-record').textContent = ElectroAPI.formatMonth(record.billing_month);
    $('#monthly-reviewer-notes-message').textContent = record.reviewer_notes;
    $('#monthly-reviewer-notes-modal').hidden = false;
    document.body.classList.add('modal-open');
    feather.replace({'stroke-width':2});
    if (Number(record.reviewer_notes_unread)) {
      try {
        const payload = await ElectroAPI.request(`/api/consumption/${record.consumption_id}/reviewer-notes/read`,{method:'POST'});
        record.reviewer_notes_unread = 0;
        record.reviewer_notes_read_at = payload.reviewer_notes_read_at;
        render();
      } catch (error) { ElectroAPI.notify(error.message,'error'); }
    }
  }

  function closeReviewerNotes() {
    $('#monthly-reviewer-notes-modal').hidden = true;
    document.body.classList.remove('modal-open');
  }

  async function save(event) {
    event.preventDefault();
    const id = $('#monthly-id').value;
    const button = $('#save-monthly');
    button.disabled = true;
    try {
      await ElectroAPI.request(id?`/api/consumption/${id}`:'/api/consumption',{method:id?'PATCH':'POST',body:new FormData(event.currentTarget)});
      close();
      await load();
      ElectroAPI.notify(`Monthly record ${id?'updated':'submitted'} successfully.`);
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
    finally { button.disabled = false; }
  }

  async function remove(id) {
    const record = state.records.find(item=>String(item.consumption_id)===String(id));
    if (record && record.verification_status === 'approved') { ElectroAPI.notify('Approved bills cannot be deleted.', 'error'); return; }
    if (!record || !(await ElectroAPI.confirm(`Move the ${ElectroAPI.formatMonth(record.billing_month)} consumption record to Recently Deleted?`, { title: 'Move to Recently Deleted?', confirmLabel: 'Move' }))) return;
    try {
      await ElectroAPI.request(`/api/consumption/${id}`,{method:'DELETE'});
      await load();
      ElectroAPI.notify('Monthly consumption record moved to Recently Deleted.');
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
  }

  async function restore(id) {
    const record = state.deletedRecords.find(item=>String(item.consumption_id)===String(id));
    if (!record) return;
    try {
      await ElectroAPI.request(`/api/consumption/${id}/restore`,{method:'POST'});
      await load();
      if (!state.deletedRecords.length) closeRecentlyDeleted();
      ElectroAPI.notify(`${ElectroAPI.formatMonth(record.billing_month)} restored to your monthly records.`);
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
  }

  async function permanentlyDeleteSelected() {
    const consumptionIds = [...state.selectedDeleted].map(Number);
    if (!consumptionIds.length || !(await ElectroAPI.confirm(`Permanently delete ${consumptionIds.length} selected monthly record${consumptionIds.length === 1 ? '' : 's'}? This cannot be undone.`, { title: 'Delete permanently?', confirmLabel: 'Delete permanently' }))) return;
    const button = $('#delete-selected-monthly');
    button.disabled = true;
    try {
      const payload = await ElectroAPI.request('/api/consumption/permanent',{method:'DELETE',body:{consumption_ids:consumptionIds}});
      state.selectedDeleted.clear();
      await load();
      ElectroAPI.notify(`${payload.deleted_count} monthly record${payload.deleted_count === 1 ? '' : 's'} permanently deleted.`);
    } catch (error) { ElectroAPI.notify(error.message,'error'); }
    finally { syncDeletedSelection(); }
  }

  document.addEventListener('click',event=>{
    const button = event.target.closest('button');
    if (!button) return;
    if (button.matches('[data-close-monthly]')) close();
    if (button.matches('[data-close-recently-deleted-monthly]')) closeRecentlyDeleted();
    if (button.matches('[data-close-monthly-reviewer-notes]')) closeReviewerNotes();
    if (button.dataset.viewMonthlyReviewerNote) openReviewerNotes(state.records.find(item=>String(item.consumption_id)===button.dataset.viewMonthlyReviewerNote));
    if (button.dataset.editMonthly) open(state.records.find(item=>String(item.consumption_id)===button.dataset.editMonthly));
    if (button.dataset.deleteMonthly) remove(button.dataset.deleteMonthly);
    if (button.dataset.restoreMonthly) restore(button.dataset.restoreMonthly);
  });
  document.addEventListener('change',event=>{
    const input = event.target.closest('[data-select-deleted-monthly]');
    if (!input) return;
    const id = String(input.dataset.selectDeletedMonthly);
    if (input.checked) state.selectedDeleted.add(id); else state.selectedDeleted.delete(id);
    syncDeletedSelection();
  });
  $('#add-monthly-record').addEventListener('click',()=>open());
  $('#add-monthly-record-secondary').addEventListener('click',()=>open());
  $('#open-recently-deleted-monthly').addEventListener('click',openRecentlyDeleted);
  $('#select-all-deleted-monthly').addEventListener('change',event=>{
    state.selectedDeleted = event.currentTarget.checked
      ? new Set(state.deletedRecords.map(item=>String(item.consumption_id)))
      : new Set();
    syncDeletedSelection();
  });
  $('#delete-selected-monthly').addEventListener('click',permanentlyDeleteSelected);
  $('#monthly-bill-image').addEventListener('change',previewBillImage);
  $('#clear-bill-image').addEventListener('click',clearBillImage);
  $('#monthly-form').addEventListener('submit',save);
  document.addEventListener('keydown',event=>{
    if (event.key !== 'Escape') return;
    if (!$('#monthly-modal').hidden) close();
    if (!$('#recently-deleted-monthly-modal').hidden) closeRecentlyDeleted();
    if (!$('#monthly-reviewer-notes-modal').hidden) closeReviewerNotes();
  });

  (async function init() {
    try {
      await ElectroAPI.requireRole(['household']);
      await load();
    } catch (error) { if (error.status!==401) ElectroAPI.notify(error.message,'error'); }
  })();
})();
