const $ = s => document.querySelector(s);
const state = { event: null, students: [] };
const thaiStatus = { present:'มา', late:'สาย', absent:'ขาด', unmarked:'รอเช็ก' };

async function api(url, options={}) {
  const res = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  const json = await res.json();
  if (!res.ok) throw new Error(json.error || 'เกิดข้อผิดพลาด');
  return json;
}
function toast(message) { const el=$('#toast'); el.textContent=message; el.classList.add('show'); setTimeout(()=>el.classList.remove('show'),2700); }
function modal(id, open=true){ $('#'+id).classList.toggle('show',open); }

async function bootstrap(){
  const data=await api('/api/bootstrap');
  $('#rosterCount').textContent=`${data.student_count} รายชื่อ`;
  const room=$('#roomSelect'); room.innerHTML='<option value="">ทุกห้อง</option>'+data.rooms.map(x=>`<option>${escapeHtml(x)}</option>`).join('');
  const select=$('#eventSelect');
  select.innerHTML='<option value="">— สร้างหรือเลือกกิจกรรม —</option>'+data.events.map(e=>`<option value="${e.id}">${escapeHtml(e.name)} · ${e.event_date}</option>`).join('');
  if(data.events.length){ select.value=data.events[0].id; state.event=data.events[0]; }
  await loadStudents();
}
async function loadStudents(){
  const room=$('#roomSelect').value, id=state.event?.id || '';
  state.students=await api(`/api/students?room=${encodeURIComponent(room)}&event_id=${id}`);
  render();
}
function escapeHtml(x){return String(x).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}
function render(){
  const q=$('#search').value.trim().toLowerCase();
  const entries=state.students.filter(s=>!q || `${s.full_name} ${s.number} ${s.student_code}`.toLowerCase().includes(q));
  $('#eventHint').textContent=state.event ? `${state.event.name} · ${state.event.event_date}` : 'เลือกกิจกรรมเพื่อเริ่มเช็กชื่อ';
  $('#download').classList.toggle('disabled',!state.event); $('#download').href=state.event?`/api/report.csv?event_id=${state.event.id}`:'#';
  const count = status => state.students.filter(x => (x.status||'unmarked')===status).length;
  ['present','late','absent','unmarked'].forEach(s=>document.querySelector(`.metric.${s} b`).textContent=count(s));
  const host=$('#students');
  if(!state.students.length){host.innerHTML='<div class="empty"><strong>ยังไม่มีรายชื่อนักเรียนในห้องนี้</strong><span>ผู้ดูแลสามารถเพิ่มหรือซิงก์รายชื่อได้จากหน้าแอดมิน</span></div>';return;}
  host.innerHTML=entries.map(s=>`<article class="student"><div class="number">${escapeHtml(s.number||'—')}</div><div><div class="student-name">${escapeHtml(s.full_name)}</div><div class="student-meta">${escapeHtml(s.room)} · ${escapeHtml(s.student_code)}</div></div><div class="checks">${['present','late','absent'].map(status=>`<button class="status ${status} ${s.status===status?'active':''}" data-id="${s.id}" data-status="${status}">${thaiStatus[status]}</button>`).join('')}</div></article>`).join('');
}
async function setStatus(studentId,status){
  if(!state.event){toast('สร้างหรือเลือกกิจกรรมก่อน');return;}
  try{await api('/api/attendance',{method:'POST',body:JSON.stringify({student_id:studentId,event_id:state.event.id,status})});const s=state.students.find(x=>x.id===studentId);s.status=status;render();}catch(e){toast(e.message);}
}

$('#students').addEventListener('click',e=>{const b=e.target.closest('[data-status]');if(b)setStatus(Number(b.dataset.id),b.dataset.status)});
$('#search').addEventListener('input',render); $('#roomSelect').addEventListener('change',loadStudents);
$('#eventSelect').addEventListener('change',e=>{ const opt=e.target.selectedOptions[0]; state.event=opt.value?{id:+opt.value,name:opt.textContent.split(' · ')[0],event_date:opt.textContent.split(' · ')[1]}:null;loadStudents(); });
document.querySelectorAll('[data-close]').forEach(x=>x.onclick=()=>modal(x.dataset.close,false));
document.querySelectorAll('.modal-backdrop').forEach(x=>x.addEventListener('click',e=>{if(e.target===x)modal(x.id,false)}));
$('#markAll').onclick=async()=>{if(!state.event){toast('สร้างหรือเลือกกิจกรรมก่อน');return}const pending=state.students.filter(s=>!s.status);if(!pending.length){toast('เช็กชื่อครบแล้ว');return}if(!confirm(`ทำเครื่องหมาย “มา” ให้ ${pending.length} คน?`))return;try{await Promise.all(pending.map(s=>api('/api/attendance',{method:'POST',body:JSON.stringify({student_id:s.id,event_id:state.event.id,status:'present'})})));pending.forEach(s=>s.status='present');render();toast('บันทึกว่ามาครบแล้ว');}catch(e){toast(e.message)}};
bootstrap().catch(e=>toast(e.message));
