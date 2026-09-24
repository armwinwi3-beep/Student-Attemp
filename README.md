# Checkin Club — เว็บเช็กชื่อนักเรียน

เว็บ Flask สำหรับเช็กชื่อนักเรียนเข้ากิจกรรม แยกตามห้อง ใช้ได้ทั้งคอมพิวเตอร์และมือถือ

## เริ่มใช้ในเครื่อง

```bash
pip install -r requirements.txt
set DATABASE_URL=postgresql://user:password@host/database
python app.py
```

จากนั้นเปิด `http://localhost:5000`

## รูปแบบ Google Sheet

แถวแรกเป็นหัวตาราง และควรมีคอลัมน์ดังนี้ (ชื่อคอลัมน์ภาษาอังกฤษก็ใช้ได้):

| ห้อง | เลขที่ | รหัสนักเรียน | ชื่อ-นามสกุล |
|---|---:|---|---|
| ม.4/1 | 1 | 65001 | สมชาย ใจดี |

ตั้งค่าสิทธิ์ไฟล์เป็น **Anyone with the link / Viewer** แล้วกด “ซิงก์รายชื่อ” ในเว็บและวางลิงก์ Google Sheet ได้ทันที

## Deploy บน Render

1. อัปโหลดโฟลเดอร์นี้ไปยัง GitHub repository
2. ใน Render เลือก **New → Blueprint** แล้วเลือก repository หรือสร้าง Web Service ด้วย `render.yaml`
3. เชื่อม Render PostgreSQL แล้วกำหนด `DATABASE_URL`
4. ตั้งค่า `ADMIN_PIN`, `SECRET_KEY` และค่า LINE ตามหัวข้อด้านล่าง

## LINE Login สำหรับนักเรียน

ระบบนักเรียนที่ `/student` ใช้ LIFF จาก LINE Login channel นักเรียนจะกรอกรหัสประจำตัวเพียงครั้งแรกเพื่อผูกบัญชี LINE จากนั้นระบบจะเข้าให้อัตโนมัติ

ตั้งค่าบน Render:

- `LINE_LIFF_ID` — LIFF ID จาก LINE Developers Console
- `LINE_LOGIN_CHANNEL_ID` — Channel ID ของ LINE Login channel เดียวกับ LIFF
- `SECRET_KEY` — ข้อความสุ่มยาวสำหรับเซสชัน (Blueprint จะสร้างให้ได้)

ใน LINE Developers Console ให้สร้าง LIFF app โดยใช้ Endpoint URL เป็น `https://student-attemp.onrender.com/student` และเปิด scope `openid` กับ `profile` จากนั้นนำ LIFF URL ไปใส่ใน Rich Menu ของ LINE Official Account
