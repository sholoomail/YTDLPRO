import os
import re
import logging
import tempfile
import shutil
from flask import Flask, request, jsonify, send_file, make_response
from flask_cors import CORS
import yt_dlp

# ========== تنظیمات اولیه و لاگینگ ==========
app = Flask(__name__)

# تنظیم CORS برای اجازه درخواست از هر دامنه‌ای (برای توسعه)
# در Production بهتر است origins را محدود کنید
CORS(app, resources={r"/api/*": {"origins": "*"}})

# تنظیم لاگینگ برای Render (لاگ‌ها در داشبورد Render نمایش داده می‌شوند)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ========== تنظیمات محیطی ==========
# دریافت پورت از متغیر محیطی Render (الزامی)
PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"  # گوش دادن به همه اینترفیس‌ها

# پوشه موقت برای دانلود (در Render فایل‌سیستم موقت است)
# از tempfile برای مدیریت خودکار استفاده می‌کنیم
TEMP_DIR = tempfile.mkdtemp(prefix="yt_downloader_")
logger.info(f"📁 پوشه موقت: {TEMP_DIR}")

# محدودیت‌ها برای جلوگیری از سوءاستفاده
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB محدودیت فایل
REQUEST_TIMEOUT = 300  # 5 دقیقه تایم‌اوت برای درخواست‌ها

# ========== توابع کمکی ==========
def clean_filename(filename):
    """حذف کاراکترهای غیرمجاز و امن‌سازی نام فایل"""
    if not filename:
        return "download"
    # حذف کاراکترهای خطرناک و محدود کردن طول نام
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', filename)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:100]  # محدود کردن طول نام فایل

def cleanup_file(filepath):
    """پاک کردن ایمن فایل"""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"🗑️ فایل پاک شد: {os.path.basename(filepath)}")
            return True
    except Exception as e:
        logger.error(f"❌ خطا در پاکسازی فایل: {e}")
    return False

def get_ytdlp_options(format_type, output_template):
    """تنظیمات yt-dlp بر اساس فرمت درخواستی"""
    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'no_check_certificate': True,  # برای جلوگیری از خطای SSL در برخی سرورها
        'socket_timeout': 30,  # تایم‌اوت سوکت
        'retries': 3,  # تعداد تلاش مجدد
        'fragment_retries': 3,
        'outtmpl': output_template,
    }
    
    if format_type == 'mp3':
        base_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'postprocessor_args': ['-codec:a', 'libmp3lame'],  # کدک بهینه برای MP3
        })
    else:  # mp4
        base_opts.update({
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
            'merge_output_format': 'mp4',
        })
    
    return base_opts

# ========== مسیرهای API ==========

@app.route('/api/health', methods=['GET'])
def health_check():
    """بررسی سلامت - برای مانیتورینگ Render"""
    return jsonify({
        'status': 'healthy',
        'service': 'youtube-downloader',
        'version': '1.0.0'
    }), 200

@app.route('/api/info', methods=['POST'])
def get_video_info():
    """دریافت اطلاعات ویدیو بدون دانلود"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url'].strip()
        logger.info(f"🔍 دریافت اطلاعات برای: {url[:50]}...")
        
        # اعتبارسنجی اولیه URL
        if not url.startswith(('http://', 'https://')):
            return jsonify({'error': 'Invalid URL format'}), 400
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 15,
            'no_check_certificate': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return jsonify({'error': 'Could not extract video info'}), 404
            
            # استخراج اطلاعات ایمن
            video_data = {
                'title': info.get('title', 'Untitled'),
                'thumbnail': info.get('thumbnail') or info.get('thumbnails', [{}])[-1].get('url', ''),
                'duration': info.get('duration', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'view_count': info.get('view_count', 0),
                'upload_date': info.get('upload_date', ''),
                'description': info.get('description', '')[:200] + '...' if info.get('description') else '',
                'id': info.get('id', ''),
                'webpage_url': info.get('webpage_url', url)
            }
            
            logger.info(f"✅ اطلاعات دریافت شد: {video_data['title'][:30]}...")
            return jsonify(video_data), 200
            
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"❌ خطای yt-dlp در info: {e}")
        if 'HTTP Error 403' in str(e) or 'Private video' in str(e):
            return jsonify({'error': 'این ویدیو قابل دسترسی نیست یا خصوصی است'}), 403
        return jsonify({'error': f'خطا در دریافت اطلاعات: {str(e)[:100]}'}), 400
        
    except Exception as e:
        logger.error(f"❌ خطای عمومی در info: {e}", exc_info=True)
        return jsonify({'error': 'خطای سرور در پردازش درخواست'}), 500


@app.route('/api/download', methods=['POST'])
def download_video():
    """دانلود و ارسال فایل به کاربر"""
    filepath = None
    
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL is required'}), 400
        
        url = data['url'].strip()
        format_type = data.get('format', 'mp4').lower()
        
        if format_type not in ['mp4', 'mp3']:
            return jsonify({'error': 'Format must be mp4 or mp3'}), 400
            
        logger.info(f"📥 درخواست دانلود: {url[:50]}... | فرمت: {format_type}")
        
        # ایجاد نام فایل ایمن
        safe_name = f"download_{format_type}"
        output_template = os.path.join(TEMP_DIR, f"{safe_name}.%(ext)s")
        
        # تنظیمات yt-dlp
        ydl_opts = get_ytdlp_options(format_type, output_template)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # استخراج و دانلود
            logger.info("🔄 شروع دانلود با yt-dlp...")
            info = ydl.extract_info(url, download=True)
            
            if not info:
                return jsonify({'error': 'Download failed'}), 500
            
            # پیدا کردن مسیر فایل نهایی
            filepath = ydl.prepare_filename(info)
            
            # اصلاح پسوند برای فایل‌های صوتی
            if format_type == 'mp3' and not filepath.endswith('.mp3'):
                filepath = os.path.splitext(filepath)[0] + '.mp3'
            
            if not os.path.exists(filepath):
                logger.error(f"❌ فایل دانلود نشد: {filepath}")
                return jsonify({'error': 'File not found after download'}), 500
            
            # بررسی حجم فایل
            file_size = os.path.getsize(filepath)
            if file_size > MAX_FILE_SIZE:
                cleanup_file(filepath)
                return jsonify({'error': f'File too large ({file_size / 1024 / 1024:.1f}MB)'}), 413
            
            logger.info(f"✅ دانلود کامل شد: {os.path.basename(filepath)} ({file_size / 1024 / 1024:.1f}MB)")
            
            # آماده‌سازی پاسخ برای ارسال فایل
            filename_for_download = clean_filename(info.get('title', 'video')) + '.' + format_type
            
            # ارسال فایل با هدرهای مناسب
            response = make_response(send_file(
                filepath,
                mimetype='audio/mpeg' if format_type == 'mp3' else 'video/mp4',
                as_attachment=True,
                download_name=filename_for_download,
                max_age=0  # جلوگیری از کش شدن
            ))
            
            # هدرهای امنیتی و کش
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
            # ⚠️ نکته مهم: در Render فایل‌سیستم موقت است
            # فایل بلافاصله بعد از ارسال پاک می‌شود تا فضا اشغال نشود
            # اما چون send_file ممکن است استریم کند، پاکسازی را با تاخیر انجام می‌دهیم
            @response.call_on_close
            def cleanup_after_send():
                cleanup_file(filepath)
                # پاکسازی پوشه موقت اگر خالی شد
                try:
                    if not os.listdir(TEMP_DIR):
                        os.rmdir(TEMP_DIR)
                except:
                    pass
            
            return response

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"❌ خطای دانلود yt-dlp: {e}")
        cleanup_file(filepath)
        if 'HTTP Error 403' in str(e) or 'blocked' in str(e).lower():
            return jsonify({'error': 'یوتیوب دسترسی از این سرور را مسدود کرده است. لطفاً از VPN یا سرور شخصی استفاده کنید.'}), 403
        if 'video is private' in str(e).lower():
            return jsonify({'error': 'این ویدیو خصوصی است و قابل دانلود نیست'}), 401
        return jsonify({'error': f'خطا در دانلود: {str(e)[:150]}'}), 400
        
    except Exception as e:
        logger.error(f"❌ خطای عمومی در دانلود: {e}", exc_info=True)
        cleanup_file(filepath)
        return jsonify({'error': 'خطای داخلی سرور. لطفاً مجدد تلاش کنید.'}), 500


@app.route('/', methods=['GET'])
def home():
    """صفحه اصلی - نمایش راهنما"""
    return jsonify({
        'service': 'YouTube Downloader API',
        'version': '1.0.0',
        'endpoints': {
            'GET /api/health': 'بررسی سلامت سرویس',
            'POST /api/info': 'دریافت اطلاعات ویدیو (body: {"url": "..."})',
            'POST /api/download': 'دانلود ویدیو (body: {"url": "...", "format": "mp4|mp3"})'
        },
        'note': 'این سرویس برای استفاده شخصی طراحی شده است.'
    }), 200


# ========== هندلرهای خطای سراسری ==========
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'error': 'Request too large'}), 413

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"❌ خطای 500: {e}")
    return jsonify({'error': 'Internal server error'}), 500


# ========== اجرای برنامه ==========
if __name__ == '__main__':
    logger.info(f"🚀 Starting YouTube Downloader on {HOST}:{PORT}")
    logger.info(f"📦 Temp directory: {TEMP_DIR}")
    
    # در Render: debug=False و threaded=True برای Production
    app.run(
        host=HOST,
        port=PORT,
        debug=False,  # ⚠️ در Production حتماً False باشد
        threaded=True  # پردازش همزمان درخواست‌ها
    )
