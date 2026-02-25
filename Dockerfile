FROM python:3.8-slim

# نصب ffmpeg و وابستگی‌های سیستمی
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ایجاد کاربر غیر-root برای امنیت بیشتر (اختیاری اما توصیه شده)
RUN useradd -m -u 1000 appuser

WORKDIR /app

# کپی فایل‌ها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# تغییر مالکیت فایل‌ها به کاربر appuser
RUN chown -R appuser:appuser /app
USER appuser

# پورت پیش‌فرض
EXPOSE 10000

# دستور اجرا
CMD ["python", "app.py"]
