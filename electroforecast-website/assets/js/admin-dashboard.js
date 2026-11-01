(function () {
  'use strict';

  const state = { user:null, type:'appliance', status:'pending', submissions:[], pending:[], users:[], selected:null };
  const TYPE_LABEL = { appliance:'appliance', consumption:'monthly consumption' };
  const $ = selector => document.querySelector(selector);

  ElectroShell.mount('admin-dashboard', 'Administration', { dateRange:false });

  function renderStats(stats) {
    $('#admin-pending').textContent = stats.pending;
    $('#admin-approved').textContent = stats.approved;
    $('#admin-households').textContent = stats.households;
    $('#admin-readiness').textContent = `${stats.data_readiness_pct}%`;
  }

  function typeIcon(type) {
    return type === 'appliance' ? 'zap' : 'bar-chart-2';
  }

  // Pending counts per type on the type switch; the Pending tab shows the selected type's count.
  function renderPendingCounts() {
    const count = type => state.pending.filter(item=>item.submission_type===type).length;
    $('#pending-appliance-count').textContent = count('appliance');
    $('#pending-consumption-count').textContent = count('consumption');
    $('#pending-filter-count').textContent = count(state.type);
  }

  function renderSubmissions() {
    const body = $('#admin-submission-body');
    const rows = state.submissions.filter(item=>item.submission_type===state.type);
    renderPendingCounts();
    if (!rows.length) {
      const status = state.status === 'all' ? '' : `${state.status} `;
      body.innerHTML = `<tr><td colspan="6"><div class="empty-table"><i data-feather="check-circle"></i><b>No ${ElectroAPI.escapeHTML(status + TYPE_LABEL[state.type])} submissions</b><span>The queue is clear for this filter.</span></div></td></tr>`;
      feather.replace({ 'stroke-width':2 });
      return;
    }
    body.innerHTML = rows.map(item=>`
      <tr>
        <td data-label="Submission"><div class="submission-title"><span class="source-icon ${item.submission_type==='appliance'?'pending':'neutral'}"><i data-feather="${typeIcon(item.submission_type)}"></i></span><span><b>${ElectroAPI.escapeHTML(item.title)}</b><small>${ElectroAPI.titleCase(item.submission_type)} · ${ElectroAPI.escapeHTML(item.category_name)}</small></span></div></td>
        <td data-label="Contributor"><div class="record-title"><b>${ElectroAPI.escapeHTML(item.contributor)}</b><small>${ElectroAPI.escapeHTML([item.barangay,item.municipality].filter(Boolean).join(', '))}</small></div></td>
        <td data-label="Details"><b>${ElectroAPI.escapeHTML(item.details)}</b><div class="text-sm text-muted">${ElectroAPI.titleCase(item.source_of_info)}${item.submission_type==='consumption' ? ` · ${item.has_bill_image ? 'Bill picture attached' : 'No bill picture'}` : ''}</div></td>
        <td data-label="Updated">${ElectroAPI.formatDate(item.updated_at)}</td>
        <td data-label="Status">${ElectroAPI.statusBadge(item.verification_status)}</td>
        <td data-label="Actions"><button type="button" class="btn btn-outline btn-sm" data-review="${item.submission_type}:${item.submission_id}">${state.user.role==='admin' ? 'Review' : 'View'}</button></td>
      </tr>`).join('');
    feather.replace({ 'stroke-width':2 });
  }

  function renderAudit(entries) {
    $('#audit-list').innerHTML = entries.length ? entries.map(item=>`
      <div class="audit-item"><span class="audit-dot"></span><div><b>${ElectroAPI.escapeHTML(item.actor)} ${ElectroAPI.escapeHTML(item.action)} ${ElectroAPI.escapeHTML(item.entity_type.replaceAll('_',' '))}</b><small>${ElectroAPI.formatDate(item.created_at,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}</small></div></div>`).join('')
      : '<div class="empty-mini">No audit activity yet.</div>';
  }

  function renderUsers() {
    $('#admin-user-body').innerHTML = state.users.map(user=>{
      const location = [user.barangay,user.municipality].filter(Boolean).join(', ') || '—';
      const action = state.user.role === 'admin' && user.user_id !== state.user.user_id
        ? `<button type="button" class="btn btn-outline btn-sm" data-user-status="${user.user_id}:${user.status==='active'?'inactive':'active'}">${user.status==='active'?'Deactivate':'Activate'}</button>`
        : '—';
      return `<tr>
        <td data-label="User"><div class="cell-user"><span class="mini-avatar">${user.full_name.split(/\s+/).slice(0,2).map(part=>part[0]).join('')}</span><span><b>${ElectroAPI.escapeHTML(user.full_name)}</b><small>${ElectroAPI.escapeHTML(user.email)}</small></span></div></td>
        <td data-label="Role">${ElectroAPI.titleCase(user.role)}</td>
        <td data-label="Location">${ElectroAPI.escapeHTML(location)}</td>
        <td data-label="Contributions">${user.appliance_count} appliances · ${user.consumption_count} months</td>
        <td data-label="Status">${ElectroAPI.statusBadge(user.status)}</td>
        <td data-label="Actions">${action}</td>
      </tr>`;
    }).join('');
  }

  async function loadStats() {
    const payload = await ElectroAPI.request('/api/admin/stats');
    renderStats(payload.stats);
    renderAudit(payload.audit);
  }

  async function loadSubmissions() {
    const [payload, pending] = await Promise.all([
      ElectroAPI.request(`/api/admin/submissions?status=${state.status}`),
      state.status === 'pending' ? null : ElectroAPI.request('/api/admin/submissions?status=pending')
    ]);
    state.submissions = payload.submissions;
    state.pending = pending ? pending.submissions : payload.submissions;
    renderSubmissions();
  }

  async function loadUsers() {
    const payload = await ElectroAPI.request('/api/admin/users');
    state.users = payload.users;
    renderUsers();
  }

  async function loadAll() {
    await Promise.all([loadStats(),loadSubmissions(),loadUsers()]);
  }

  function openReview(item) {
    state.selected = item;
    $('#review-type').textContent = `${ElectroAPI.titleCase(item.submission_type)} validation`;
    $('#review-title').textContent = item.title;
    $('#review-notes').value = item.reviewer_notes || '';
    $('#review-summary').innerHTML = `
      <div><small>Contributor</small><b>${ElectroAPI.escapeHTML(item.contributor)}</b></div>
      <div><small>Category</small><b>${ElectroAPI.escapeHTML(item.category_name)}</b></div>
      <div><small>Submitted Value</small><b>${ElectroAPI.escapeHTML(item.details)}</b></div>
      <div><small>Information Source</small><b>${ElectroAPI.titleCase(item.source_of_info)}</b></div>
      <div><small>Current Status</small>${ElectroAPI.statusBadge(item.verification_status)}</div>
      ${item.submission_type === 'consumption' ? `<div><small>Bill Evidence</small>${item.has_bill_image ? `<a class="btn btn-outline btn-sm" href="/api/consumption/${item.submission_id}/bill-image" target="_blank" rel="noopener"><i data-feather="image"></i> View Bill Picture</a>` : '<b>Not attached</b>'}</div>` : ''}`;
    const canReview = state.user.role === 'admin';
    $('#approve-submission').hidden = !canReview;
    $('#reject-submission').hidden = !canReview;
    $('#review-notes').disabled = !canReview;
    $('#review-modal').hidden = false;
    document.body.classList.add('modal-open');
    feather.replace({ 'stroke-width':2 });
  }

  function closeReview() {
    $('#review-modal').hidden = true;
    document.body.classList.remove('modal-open');
    state.selected = null;
  }

  async function review(status) {
    if (!state.selected) return;
    const notes = $('#review-notes').value.trim();
    if (status === 'rejected' && !notes) {
      ElectroAPI.notify('Enter a clear rejection reason.','error');
      $('#review-notes').focus();
      return;
    }
    const button = status === 'approved' ? $('#approve-submission') : $('#reject-submission');
    button.disabled = true;
    try {
      await ElectroAPI.request(`/api/admin/submissions/${state.selected.submission_type}/${state.selected.submission_id}`, {
        method:'PATCH', body:{ status, reviewer_notes:notes }
      });
      closeReview();
      await loadAll();
      ElectroAPI.notify(`Submission ${status}.`);
    } catch (error) {
      ElectroAPI.notify(error.message,'error');
    } finally {
      button.disabled = false;
    }
  }

  async function updateUser(userId,status) {
    try {
      await ElectroAPI.request(`/api/admin/users/${userId}`,{ method:'PATCH',body:{status} });
      await loadUsers();
      ElectroAPI.notify(`User ${status}.`);
    } catch (error) {
      ElectroAPI.notify(error.message,'error');
    }
  }

  document.addEventListener('click',event=>{
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.typeFilter) {
      state.type = button.dataset.typeFilter;
      document.querySelectorAll('[data-type-filter]').forEach(item=>{
        const active = item === button;
        item.classList.toggle('active',active);
        item.setAttribute('aria-selected',String(active));
      });
      renderSubmissions();
    }
    if (button.dataset.statusFilter) {
      state.status = button.dataset.statusFilter;
      document.querySelectorAll('[data-status-filter]').forEach(item=>{
        const active = item === button;
        item.classList.toggle('active',active);
        item.setAttribute('aria-selected',String(active));
      });
      loadSubmissions().catch(error=>ElectroAPI.notify(error.message,'error'));
    }
    if (button.dataset.review) {
      const [type,id] = button.dataset.review.split(':');
      openReview(state.submissions.find(item=>item.submission_type===type && String(item.submission_id)===id));
    }
    if (button.matches('[data-close-review]')) closeReview();
    if (button.dataset.userStatus) {
      const [id,status] = button.dataset.userStatus.split(':');
      updateUser(id,status);
    }
  });
  $('#refresh-admin').addEventListener('click',()=>loadAll().then(()=>ElectroAPI.notify('Dashboard refreshed.')).catch(error=>ElectroAPI.notify(error.message,'error')));
  $('#approve-submission').addEventListener('click',()=>review('approved'));
  $('#reject-submission').addEventListener('click',()=>review('rejected'));
  document.addEventListener('keydown',event=>{ if(event.key==='Escape' && !$('#review-modal').hidden) closeReview(); });

  (async function init(){
    try {
      state.user = await ElectroAPI.requireRole(['admin','guimelco','researcher']);
      await loadAll();
      const target = location.hash && document.querySelector(location.hash);
      if (target) target.scrollIntoView({block:'start'});
    } catch (error) {
      if (error.status !== 401) ElectroAPI.notify(error.message,'error');
    }
  })();
})();
