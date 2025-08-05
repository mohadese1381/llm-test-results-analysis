# 1) اجرای تست و ذخیره خروجی
python -m unittest discover > result.txt 2>&1

# 2) ارسال همه چیز با curl.exe (نه alias پاورشل)
curl.exe -X POST http://localhost:5000/analyze_test_output `
  -F "language=python" `
  -F "test_output=@result.txt;type=text/plain;charset=utf-8" `
  -F "test_code=@test_math_utils.py;type=text/plain;charset=utf-8" `
  -F "source_code=@math_utils.py;type=text/plain;charset=utf-8" `
  -o report.html

# 3) باز کردن گزارش
Start-Process report.html
