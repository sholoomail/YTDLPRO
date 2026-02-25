FROM python:3.8-slim

# نصب ffmpeg و ابزارهای لازم
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# کپی کردن فایل‌ها
WORKDIR /app
COPY . .

# نصب کتابخانه‌های پایتون
RUN pip install --no-cache-dir -r requirements.txt

# اجرای برنامه
# نکته: پورت باید 7860 باشد و به همه آی‌پی‌ها گوش دهد
CMD ["python", "app.py"]
