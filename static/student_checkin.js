const $ = s => document.querySelector(s);
let currentLat = null;
let currentLng = null;

$('#getLocationBtn').addEventListener('click', () => {
  const btn = $('#getLocationBtn');
  btn.textContent = 'กำลังค้นหาพิกัด...';
  
  if (!navigator.geolocation) {
    Swal.fire('ข้อผิดพลาด', 'เบราว์เซอร์ของคุณไม่รองรับ GPS', 'error');
    btn.textContent = '📍 กดเพื่อแชร์ตำแหน่งปัจจุบัน';
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (position) => {
      currentLat = position.coords.latitude;
      currentLng = position.coords.longitude;
      btn.style.display = 'none';
      $('#locationStatus').style.display = 'block';
    },
    (error) => {
      Swal.fire('แชร์พิกัดล้มเหลว', 'กรุณากด "อนุญาต (Allow)" ให้เว็บไซต์เข้าถึงตำแหน่งที่ตั้ง (Location) ของคุณก่อน', 'error');
      btn.textContent = '📍 กดเพื่อแชร์ตำแหน่งปัจจุบัน';
    },
    { enableHighAccuracy: true }
  );
});

$('#checkinForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  
  if (currentLat === null || currentLng === null) {
    Swal.fire('แจ้งเตือน', 'กรุณากดปุ่ม "แชร์ตำแหน่งปัจจุบัน" ก่อนกดบันทึก', 'warning');
    return;
  }

  const btn = $('#submitBtn');
  btn.disabled = true;
  btn.textContent = 'กำลังตรวจสอบ...';

  const payload = {
    otp: $('#otpCode').value,
    lat: currentLat,
    lng: currentLng
  };

  try {
    const res = await fetch('/api/student/submit_checkin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (!res.ok) throw new Error(data.error || 'เกิดข้อผิดพลาด');
    
    await Swal.fire('สำเร็จ!', 'บันทึกเวลาเข้าร่วมกิจกรรมเรียบร้อยแล้ว', 'success');
    window.location.href = '/student'; // กลับไปหน้าแรก
    
  } catch (err) {
    Swal.fire('เช็กชื่อไม่สำเร็จ', err.message, 'error');
    btn.disabled = false;
    btn.innerHTML = 'บันทึกเวลาเข้าร่วม <span>→</span>';
  }
});