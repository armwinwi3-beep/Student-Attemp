const $ = selector => document.querySelector(selector);
const escapeHtml = text => String(text).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

async function api(url, options = {}) {
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'ไม่สามารถโหลดรายงานได้');
  return data;
}

function render(data) {
  const {event, rooms, totals} = data;
  $('#empty').hidden = true; $('#report').hidden = false;
  $('#eventName').textContent = event.name; $('#eventDate').textContent = `วันที่ ${event.event_date}`;
  $('#overallPercent').textContent = `${totals.percentage}%`;
  $('#total').textContent = totals.total;
  for (const status of ['present', 'late', 'absent', 'unmarked']) {
    $(`#${status}`).textContent = `${totals[`${status}_percentage`]}%`;
    $(`#${status}Count`).textContent = `${totals[status]} คน`;
  }
  $('#download').href = `/api/report.csv?event_id=${event.id}`; $('#download').classList.remove('disabled');
  $('#rooms').innerHTML = rooms.map(room => `<tr><td>${escapeHtml(room.room)}</td><td><b>${room.attended} / ${room.total}</b></td><td>${room.present} <small>(${room.present_percentage}%)</small></td><td>${room.late} <small>(${room.late_percentage}%)</small></td><td>${room.absent} <small>(${room.absent_percentage}%)</small></td><td>${room.unmarked} <small>(${room.unmarked_percentage}%)</small></td><td><div class="rate"><span>${room.percentage}%</span><span class="bar"><i style="width:${Math.min(room.percentage,100)}%"></i></span></div></td></tr>`).join('');
}

async function loadReport() {
  const id = $('#eventSelect').value;
  if (!id) { $('#report').hidden = true; $('#empty').hidden = false; return; }
  try { render(await api(`/api/admin/report?event_id=${id}`)); }
  catch (err) { $('#empty').textContent = err.message; $('#empty').hidden = false; $('#report').hidden = true; }
}

async function init() {
  const data = await api('/api/bootstrap');
  const select = $('#eventSelect');
  if (!data.events.length) { select.innerHTML = '<option>ยังไม่มีกิจกรรม</option>'; return; }
  select.innerHTML = data.events.map(e => `<option value="${e.id}">${escapeHtml(e.name)} · ${e.event_date}</option>`).join('');
  await loadReport();
}
async function loadRooms() {
  const rooms = await api('/api/admin/rooms');
  const list = $('#roomSources');
  if (!rooms.length) { list.innerHTML = '<p class="source-empty">ยังไม่ได้เชื่อมห้องเรียน — กด “เพิ่มห้องเรียน” เพื่อเริ่มต้น</p>'; return; }
  list.innerHTML = rooms.map(room => `<article class="source-card"><div><b>${escapeHtml(room.room)}</b><small>${escapeHtml(room.sheet_url)}</small><em>${room.student_count} รายชื่อ · GID ${escapeHtml(room.gid)}</em></div><div class="source-actions"><button data-action="sync" data-id="${room.id}">↻ ซิงก์</button><button class="delete" data-action="delete" data-id="${room.id}" data-room="${escapeHtml(room.room)}">ลบ</button></div></article>`).join('');
}
let eventsCache = [];
let editingEventId = null;
async function loadEventManager() {
  const data = await api('/api/bootstrap');
  eventsCache = data.events;
  const host = $('#eventList');
  if (!eventsCache.length) { host.innerHTML = '<p class="event-empty">ยังไม่มีกิจกรรม — เพิ่มกิจกรรมแรกได้เลย</p>'; return; }
  host.innerHTML = eventsCache.map(event => `<article class="event-item"><div><b>${escapeHtml(event.name)}</b><small>${event.event_date}</small></div><div class="event-actions"><button data-event-action="edit" data-id="${event.id}">แก้ไข</button><button class="event-delete" data-event-action="delete" data-id="${event.id}">ลบ</button></div></article>`).join('');
}
function eventModal(show) { $('#eventModal').classList.toggle('show', show); }
function prepareEvent(event = null) {
  editingEventId = event?.id || null;
  $('#eventModalTitle').textContent = event ? 'แก้ไขกิจกรรม' : 'เพิ่มกิจกรรม';
  $('#eventName').value = event?.name || '';
  $('#eventDate').value = event?.event_date || new Date().toISOString().slice(0, 10);
  $('#saveEvent').textContent = event ? 'บันทึกการแก้ไข →' : 'บันทึกกิจกรรม →';
  eventModal(true);
}
$('#addEvent').addEventListener('click', () => prepareEvent());
$('#closeEventModal').addEventListener('click', () => eventModal(false));
$('#eventModal').addEventListener('click', event => { if (event.target.id === 'eventModal') eventModal(false); });
$('#eventForm').addEventListener('submit', async event => {
  event.preventDefault(); const button = $('#saveEvent');
  const form = event.currentTarget;
  const payload = {name: form.elements.event_name.value.trim(), event_date: form.elements.event_date.value};
  if (!payload.name || !payload.event_date) { alert('กรุณาระบุชื่อกิจกรรมและวันที่'); return; }
  button.disabled = true;
  const body = JSON.stringify(payload);
  try {
    if (editingEventId) await api(`/api/admin/events/${editingEventId}`, {method:'PATCH', body});
    else await api('/api/events', {method:'POST', body});
    eventModal(false); await init(); await loadEventManager();
  } catch (error) { alert(error.message); } finally { button.disabled = false; }
});
$('#eventList').addEventListener('click', async event => {
  const button = event.target.closest('[data-event-action]'); if (!button) return;
  const item = eventsCache.find(entry => entry.id === Number(button.dataset.id)); if (!item) return;
  if (button.dataset.eventAction === 'edit') { prepareEvent(item); return; }
  if (!confirm(`ลบกิจกรรม “${item.name}” และประวัติการเช็กชื่อทั้งหมดของกิจกรรมนี้?`)) return;
  try { await api(`/api/admin/events/${item.id}`, {method:'DELETE'}); await init(); await loadEventManager(); }
  catch (error) { alert(error.message); }
});
function roomModal(show) { $('#roomModal').classList.toggle('show', show); }
$('#addRoom').addEventListener('click', () => roomModal(true));
$('#closeRoomModal').addEventListener('click', () => roomModal(false));
$('#roomModal').addEventListener('click', event => { if (event.target.id === 'roomModal') roomModal(false); });
$('#roomForm').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; button.textContent = 'กำลังซิงก์…';
  try {
    const result = await api('/api/admin/rooms', {method:'POST', body:JSON.stringify({sheet_url:$('#sourceUrl').value, gid:$('#sourceGid').value})});
    roomModal(false); $('#roomForm').reset(); $('#sourceGid').value = '0'; await loadRooms(); alert(`บันทึกแล้ว: ซิงก์ ${result.count} รายชื่อ`);
  } catch (error) { alert(error.message); } finally { button.disabled = false; button.textContent = 'บันทึกและซิงก์รายชื่อ →'; }
});
$('#roomSources').addEventListener('click', async event => {
  const button = event.target.closest('[data-action]'); if (!button) return;
  const id = button.dataset.id;
  if (button.dataset.action === 'delete' && !confirm(`ลบห้อง ${button.dataset.room} พร้อมรายชื่อและประวัติการเช็กชื่อทั้งหมด?`)) return;
  button.disabled = true;
  try {
    if (button.dataset.action === 'sync') { const r = await api(`/api/admin/rooms/${id}/sync`, {method:'POST'}); alert(`ซิงก์สำเร็จ ${r.count} รายชื่อ`); }
    else { await api(`/api/admin/rooms/${id}`, {method:'DELETE'}); }
    await loadRooms();
  } catch (error) { alert(error.message); button.disabled = false; }
});
$('#eventSelect').addEventListener('change', loadReport);
Promise.all([init(), loadRooms(), loadEventManager()]).catch(err => { $('#empty').textContent = err.message; });
