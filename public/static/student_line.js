const $ = selector => document.querySelector(selector);
const liffId = document.body.dataset.liffId;
let currentIdToken = '';
const nextPage = new URLSearchParams(window.location.search).get('next') === 'status'
  ? '/student/status' : '/student/checkin';

function showError(message) {
  $('#loader').hidden = true; $('#linkPanel').hidden = true; $('#errorPanel').hidden = false;
  $('#title').textContent = 'มีบางอย่างไม่สำเร็จ'; $('#description').textContent = 'ตรวจสอบรายละเอียดด้านล่างแล้วลองใหม่';
  $('#errorMessage').textContent = message;
}

async function authenticate(studentCode = '') {
  const response = await fetch('/api/student/line-auth', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({id_token: currentIdToken, student_code: studentCode})
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'ไม่สามารถยืนยันตัวตนได้');
  if (result.linked) { window.location.replace(nextPage); return; }
  $('#loader').hidden = true; $('#linkPanel').hidden = false;
  $('#title').textContent = 'ยืนยันรหัสนักเรียน';
  $('#description').textContent = 'ผูกครั้งเดียว แล้วครั้งถัดไป LINE จะพาเข้าให้อัตโนมัติ';
  $('#lineName').textContent = result.line_name || 'ผู้ใช้ LINE';
  if (result.picture) { $('#linePicture').src = result.picture; } else { $('#linePicture').hidden = true; }
  $('#studentCode').focus();
}

async function start() {
  if (!liffId) { showError('ผู้ดูแลยังไม่ได้ตั้งค่า LINE_LIFF_ID บน Render'); return; }
  try {
    await liff.init({liffId});
    if (!liff.isLoggedIn()) { liff.login({redirectUri: window.location.href}); return; }
    currentIdToken = liff.getIDToken();
    if (!currentIdToken) throw new Error('ไม่ได้รับข้อมูลยืนยันตัวตนจาก LINE');
    await authenticate();
  } catch (error) { showError(error.message || 'ไม่สามารถเชื่อมต่อ LINE ได้'); }
}

$('#linkForm').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; button.textContent = 'กำลังผูกบัญชี…';
  try { await authenticate($('#studentCode').value.trim()); }
  catch (error) { showError(error.message); button.disabled = false; button.innerHTML = 'ผูกบัญชีและเข้าสู่ระบบ <span>→</span>'; }
});
$('#retryButton').addEventListener('click', () => window.location.reload());
start();
