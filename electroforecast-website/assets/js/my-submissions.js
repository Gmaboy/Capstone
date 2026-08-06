(function(){
  'use strict';
  const state={submissions:[],categories:[]};
  const $=selector=>document.querySelector(selector);
  ElectroShell.mount('submissions','My Submissions',{dateRange:false});

  function sourceLabel(value){return {nameplate_label:'Nameplate label',user_manual:'User manual',retailer_specs:'Retailer specifications',manual_estimate:'Manual estimate'}[value]||ElectroAPI.titleCase(value);}
  function render(){
    $('#submission-total').textContent=state.submissions.length;
    $('#submission-pending').textContent=state.submissions.filter(item=>item.verification_status==='pending').length;
    $('#submission-approved').textContent=state.submissions.filter(item=>item.verification_status==='approved').length;
    $('#submission-inventory').textContent=state.submissions.filter(item=>Number(item.in_inventory)).length;
    $('#submission-body').innerHTML=state.submissions.length?state.submissions.map(item=>`
      <tr class="submission-row ${ElectroAPI.escapeHTML(item.verification_status)}">
        <td data-label="Submission"><div class="record-title"><b>${ElectroAPI.escapeHTML(item.appliance_name)}</b><small>${ElectroAPI.escapeHTML([item.brand,item.model,item.category_name].filter(Boolean).join(' · '))}</small></div></td>
        <td data-label="Power Rating"><div class="submission-power"><b>${Number(item.power_rating_watts).toLocaleString()} W</b><span>Qty ${item.quantity} · ${item.avg_daily_usage_hours} hr/day</span></div></td>
        <td data-label="Source">${ElectroAPI.escapeHTML(sourceLabel(item.source_of_info))}</td>
        <td data-label="Status"><div class="status-note-wrap">${ElectroAPI.statusBadge(item.verification_status)}${item.reviewer_notes&&!item.copied_from_appliance_id?`<button type="button" class="reviewer-note-button ${Number(item.reviewer_notes_unread)?'unread':''}" data-view-reviewer-note="${item.appliance_id}" aria-label="${Number(item.reviewer_notes_unread)?'View unread':'View'} Reviewer Notes for ${ElectroAPI.escapeHTML(item.appliance_name)}"><i data-feather="message-square"></i><span class="reviewer-note-unread-dot"></span></button>`:''}</div></td>
        <td data-label="Household Inventory">${Number(item.in_inventory)?'<span class="badge verified"><span class="badge-dot"></span>Added</span>':Number(item.recently_deleted)?'<span class="badge neutral"><span class="badge-dot"></span>Recently Deleted</span>':item.verification_status==='approved'?`<a class="btn btn-primary btn-sm" href="my-appliances.html?submission=${item.appliance_id}">Add to My Appliances</a>`:'<span class="text-sm text-muted">Not eligible yet</span>'}</td>
        <td data-label="Actions"><div class="row-actions portal-actions"><button type="button" data-edit-submission="${item.appliance_id}" aria-label="Edit ${ElectroAPI.escapeHTML(item.appliance_name)}"><i data-feather="edit-2"></i></button>${item.verification_status==='approved'?`<button type="button" class="submission-delete-locked" disabled title="Approved submissions cannot be deleted" aria-label="Approved submission ${ElectroAPI.escapeHTML(item.appliance_name)} cannot be deleted"><i data-feather="lock"></i></button>`:`<button type="button" class="reject" data-delete-submission="${item.appliance_id}" aria-label="Delete ${ElectroAPI.escapeHTML(item.appliance_name)}"><i data-feather="trash-2"></i></button>`}</div></td>
      </tr>`).join(''):`<tr><td colspan="6"><div class="empty-table"><i data-feather="database"></i><b>No appliance submissions yet</b><span>Your household inventory is managed separately in My Appliances.</span></div></td></tr>`;
    feather.replace({'stroke-width':2});
  }
  async function load(){const payload=await ElectroAPI.request('/api/appliances');state.submissions=payload.appliances;render();}
  function open(record){
    $('#submission-form').reset();$('#submission-id').value=record?.appliance_id||'';
    $('#submission-modal-title').textContent=record?'Edit Appliance Submission':'Submit New Appliance';
    $('#submission-name').value=record?.appliance_name||'';$('#submission-category').value=record?.category_id||state.categories[0]?.category_id||'';
    $('#submission-brand').value=record?.brand||'';$('#submission-model').value=record?.model||'';$('#submission-watts').value=record?.power_rating_watts||'';
    $('#submission-quantity').value=record?.quantity||1;$('#submission-hours').value=record?.avg_daily_usage_hours??'';$('#submission-source').value=record?.source_of_info||'nameplate_label';
    $('#submission-confirm').checked=false;$('#save-submission').innerHTML=`<i data-feather="${record?'save':'send'}"></i> ${record?'Save & Resubmit':'Submit for Validation'}`;
    $('#submission-modal').hidden=false;document.body.classList.add('modal-open');feather.replace({'stroke-width':2});$('#submission-name').focus();
  }
  function close(){ $('#submission-modal').hidden=true;document.body.classList.remove('modal-open'); }
  async function openReviewerNotes(record){
    if(!record?.reviewer_notes)return;
    $('#reviewer-notes-appliance').textContent=record.appliance_name;
    $('#reviewer-notes-message').textContent=record.reviewer_notes;
    $('#reviewer-notes-modal').hidden=false;document.body.classList.add('modal-open');feather.replace({'stroke-width':2});
    if(Number(record.reviewer_notes_unread)){
      try{
        const payload=await ElectroAPI.request(`/api/appliances/${record.appliance_id}/reviewer-notes/read`,{method:'POST'});
        record.reviewer_notes_unread=0;record.reviewer_notes_read_at=payload.reviewer_notes_read_at;render();
      }catch(error){ElectroAPI.notify(error.message,'error');}
    }
  }
  function closeReviewerNotes(){ $('#reviewer-notes-modal').hidden=true;document.body.classList.remove('modal-open'); }
  async function save(event){event.preventDefault();const id=$('#submission-id').value;const button=$('#save-submission');button.disabled=true;try{await ElectroAPI.request(id?`/api/appliances/${id}`:'/api/appliances',{method:id?'PATCH':'POST',body:Object.fromEntries(new FormData(event.currentTarget).entries())});close();await load();ElectroAPI.notify(id?'Submission updated and returned to review.':'Appliance submitted for validation.');}catch(error){ElectroAPI.notify(error.message,'error');}finally{button.disabled=false;}}
  async function remove(id){const record=state.submissions.find(item=>String(item.appliance_id)===String(id));if(!record)return;if(record.verification_status==='approved'){ElectroAPI.notify('Approved appliance submissions cannot be deleted.','error');return;}if(!window.confirm(`Delete ${record.appliance_name} from My Submissions? Any copy in My Appliances will remain.`))return;try{await ElectroAPI.request(`/api/appliances/${id}`,{method:'DELETE'});await load();ElectroAPI.notify('Submission deleted; household inventory was not changed.');}catch(error){ElectroAPI.notify(error.message,'error');}}
  document.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;if(button.matches('[data-close-submission]'))close();if(button.matches('[data-close-reviewer-notes]'))closeReviewerNotes();if(button.dataset.viewReviewerNote)openReviewerNotes(state.submissions.find(item=>String(item.appliance_id)===button.dataset.viewReviewerNote));if(button.dataset.editSubmission)open(state.submissions.find(item=>String(item.appliance_id)===button.dataset.editSubmission));if(button.dataset.deleteSubmission)remove(button.dataset.deleteSubmission);});
  $('#new-submission').addEventListener('click',()=>open());$('#submission-form').addEventListener('submit',save);document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if(!$('#submission-modal').hidden)close();if(!$('#reviewer-notes-modal').hidden)closeReviewerNotes();});
  (async function(){try{await ElectroAPI.requireRole(['household']);const categories=await ElectroAPI.request('/api/categories');state.categories=categories.categories;$('#submission-category').innerHTML=state.categories.map(item=>`<option value="${item.category_id}">${ElectroAPI.escapeHTML(item.category_name)}</option>`).join('');await load();}catch(error){if(error.status!==401)ElectroAPI.notify(error.message,'error');}})();
})();
