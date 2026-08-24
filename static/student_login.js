const $ = s => document.querySelector(s);
let currentStudents = [];

// 1. โหลดรายชื่อห้องตอนเปิดเว็บ
async function loadRooms() {
  try {
    const res = await fetch('/api/bootstrap');
    const data = await res.json();
    const select = $('#roomSelect');
    select.innerHTML = '<option value="">— เลือกห้องเรียน —</option>' + 
      data.rooms.map(room => `<option value="${room}">${room}</option>`).join('');
  } catch (err) {
    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถโหลดรายชื่อห้องได้', 'error');
  }
}

// 2. ดึงรายชื่อนักเรียนเมื่อมีการเปลี่ยนห้อง
$('#roomSelect').addEventListener('change', async (e) => {
  const room = e.target.value;
  const studentSelect = $('#studentSelect');
  
  if (!room) {
    studentSelect.innerHTML = '<option value="">— กรุณาเลือกห้องเรียนก่อน —</option>';
    studentSelect.disabled = true;
    return;
  }

  try {
    const res = await fetch(`/api/students?room=${encodeURIComponent(room)}`);
    currentStudents = await res.json();
    studentSelect.innerHTML = '<option value="">— เลือกชื่อของคุณ —</option>' + 
      currentStudents.map(s => `<option value="${s.id}">${s.number || '-'}. ${s.full_name}</option>`).join('');
    studentSelect.disabled = false;
  } catch (err) {
    Swal.fire('ข้อผิดพลาด', 'ไม่สามารถโหลดรายชื่อนักเรียนได้', 'error');
  }
});

// 3. จัดการตอนกดปุ่มเข้าสู่ระบบ
$('#studentForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  btn.disabled = true;
  btn.textContent = 'กำลังตรวจสอบ...';

  const payload = {
    student_id: $('#studentSelect').value,
    pin: $('#studentPin').value
  };

  try {
    const res = await fetch('/api/student/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (!res.ok) throw new Error(data.error || 'รหัสไม่ถูกต้อง');
    
    // ล็อกอินผ่าน ให้พาไปหน้าเช็กชื่อ (OTP + GPS)
    window.location.href = '/student/checkin';
    
  } catch (err) {
    Swal.fire('เข้าสู่ระบบไม่สำเร็จ', err.message, 'error');
    btn.disabled = false;
    btn.innerHTML = 'ยืนยันตัวตน <span>→</span>';
  }
});

loadRooms();