import subprocess
import sys
import asyncio
import logging
import os
import uuid
import threading
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

# تحديث تلقائي لمكتبة yt-dlp
try:
    print("🔄 جاري التحقق من تحديثات yt-dlp...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("✅ yt-dlp محدث لأحدث إصدار!")
except Exception as e:
    print(f"⚠️ فشل التحديث التلقائي: {e}")

from yt_dlp import YoutubeDL

# ================== سيرفر الصحة لإرضاء المنصة ==================
class DummyHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ZenDown_Bot is Running!")
        
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyHealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_dummy_server, daemon=True).start()

# ================== الإعدادات والتكوين ==================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("ZenDown_Bot")

# نظام تسجيل الأخطاء المخصص للمشرف
ERROR_LOGS = []
def log_custom_error(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    ERROR_LOGS.append(f"[{timestamp}] {msg}")
    if len(ERROR_LOGS) > 15:
        ERROR_LOGS.pop(0)
    logger.error(msg)

TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL = "@ZenoX_Tools"
ADMIN_ID = 6043858925

COOKIES_FILE = "/etc/secrets/cookies.txt"
COOKIES_FILE = COOKIES_FILE if os.path.exists(COOKIES_FILE) else None

MAX_CONCURRENT_DOWNLOADS = 4
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
MAX_CONCURRENT_COMPRESSIONS = 2
COMPRESS_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_COMPRESSIONS)

SEARCH_CACHE = {}
URL_CACHE = {}

# ================== نظام الإحصائيات ==================
STATS_FILE = "stats.json"

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "users": {}, "total_requests": 0, "successful_downloads": 0,
        "failed_downloads": 0, "cache_hits": 0, "sent_videos": 0,
        "request_limits": 0, "share_clicks": 0,
        "platforms": {"يوتيوب": 0, "تويتر/X": 0, "سناب شات": 0, "تيك توك": 0, "إنستغرام": 0, "بينترست": 0, "أخرى": 0}
    }

stats = load_stats()
BOT_START_TIME = datetime.now()

def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def track_user_activity(user_id):
    stats["users"][str(user_id)] = datetime.now().isoformat()
    save_stats()

def track_platform_request(url):
    stats["total_requests"] += 1
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u: stats["platforms"]["يوتيوب"] += 1
    elif "twitter.com" in u or "x.com" in u: stats["platforms"]["تويتر/X"] += 1
    elif "tiktok.com" in u: stats["platforms"]["تيك توك"] += 1
    elif "instagram.com" in u: stats["platforms"]["إنستغرام"] += 1
    elif "snapchat.com" in u: stats["platforms"]["سناب شات"] += 1
    elif "pinterest.com" in u or "pin.it" in u: stats["platforms"]["بينترست"] += 1
    else: stats["platforms"]["أخرى"] += 1
    save_stats()

def track_download_status(success: bool):
    if success: 
        stats["successful_downloads"] += 1
        stats["sent_videos"] += 1
    else: 
        stats["failed_downloads"] += 1
    save_stats()

async def check_user_subscription(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# ================== أوامر المشرف ==================
async def show_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return
    
    if not ERROR_LOGS:
        await update.message.reply_text("✅ لا توجد أخطاء مسجلة في الجلسة الحالية.")
        return
        
    text = "⚠️ <b>سجل الأخطاء الأخير (من الأقدم للأحدث):</b>\n\n" + "\n\n".join(ERROR_LOGS)
    await update.message.reply_text(text, parse_mode="HTML")

async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return
    msg = update.callback_query.message if update.callback_query else update.message
    total_users = len(stats["users"])
    
    uptime = datetime.now() - BOT_START_TIME
    days, hours, minutes = uptime.days, uptime.seconds // 3600, (uptime.seconds // 60) % 60

    stats_msg = (
        f"📊 <b>إحصائيات @ZenDown_Bot</b>\n\n"
        f"👥 المستخدمون: {total_users}\n"
        f"✅ ناجحة: {stats.get('successful_downloads', 0)} | ❌ فاشلة: {stats.get('failed_downloads', 0)}\n"
        f"⏰ وقت التشغيل: {days} يوم {hours} ساعة {minutes} دقيقة"
    )

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data="refresh_stats")]])
    if update.callback_query:
        await update.callback_query.answer("تم التحديث")
        try: await msg.edit_text(stats_msg, parse_mode="HTML", reply_markup=markup)
        except: pass
    else:
        await msg.reply_text(stats_msg, parse_mode="HTML", reply_markup=markup)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return

    text = update.message.text.replace("/broadcast", "").strip()
    if not text:
        await update.message.reply_text("اكتب الرسالة بعد الأمر.")
        return

    users = list(stats["users"].keys())
    msg = await update.message.reply_text(f"🚀 جاري الإرسال لـ {len(users)} مستخدم...")

    success, failed = 0, 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await msg.edit_text(f"✅ تمت الإذاعة!\nنجح: {success}\nفشل: {failed}")

# ================== دوال التحميل والضغط ==================
def _blocking_extract_info(url):
    opts = {
        'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'geo_bypass': True, 'nocheckcertificate': True, 'socket_timeout': 15 
    }
    with YoutubeDL(opts) as ydl: return ydl.extract_info(url, download=False)

def _blocking_download(url, opts):
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def _blocking_cobalt_download(video_url, out_path, action):
    api_url = "https://api.cobalt.tools/"
    payload = {
        "url": video_url,
        "vCodec": "h264",
        "isAudioOnly": action in ["aud", "voc"]
    }
    req = urllib.request.Request(api_url, data=json.dumps(payload).encode(), headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:200]
        raise Exception(f"HTTP {e.code} Cobalt: {body}")
        
    media_url = data.get("url")
    if not media_url and data.get("status") == "picker":
        media_url = data["picker"][0]["url"]
        
    if not media_url:
        raise Exception("Cobalt: لا يوجد رابط مباشر")
        
    dl_req = urllib.request.Request(media_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(dl_req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())
        
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    raise Exception("Cobalt: الملف الناتج فارغ")

def _blocking_tiktok_via_tikwm(url, out_path, want_audio=False):
    api_url = "https://www.tikwm.com/api/?url=" + urllib.request.quote(url, safe="")
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise Exception(f"TikWM Request Error: {e}")

    if data.get("code") != 0 or "data" not in data:
        raise Exception(f"TikWM Error: {data.get('msg', 'unknown')}")

    media_url = data["data"].get("music") if want_audio else (data["data"].get("play") or data["data"].get("hdplay"))
    if not media_url: raise Exception("TikWM: لا يوجد رابط")

    if media_url.startswith("/"): media_url = "https://www.tikwm.com" + media_url

    dl_req = urllib.request.Request(media_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(dl_req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    raise Exception("TikWM: الملف فارغ")

def _compress_video_sync(input_file, output_file):
    cmd = [
        'ffmpeg', '-y', '-i', input_file, '-c:v', 'libx264', '-preset', 'ultrafast',
        '-threads', '0', '-crf', '35', '-vf', "scale='min(480,iw)':-2",
        '-r', '24', '-c:a', 'aac', '-b:a', '64k', output_file
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=180)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0: return output_file
    except: pass 
    return input_file

# ================== استقبال الرسائل والبحث ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("اشترك في القناة 📡", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton("تحقق 🔍", callback_data="check_sub")]
        ])
        await update.message.reply_text("🚧 عذراً، يجب الاشتراك بالقناة أولاً.", reply_markup=markup)
        return

    await update.message.reply_text(f"أهلاً بك <b>{user.first_name}</b> في محرك التحميل! 🚀\nأرسل رابطاً للتحميل، أو اكتب نصاً للبحث.", parse_mode="HTML")

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await check_user_subscription(context.bot, q.from_user.id):
        await q.message.delete()
        await q.message.reply_text("✅ تم التحقق! أرسل رابطك الآن.")
    else:
        await q.answer("❌ لم تشترك بالقناة بعد!", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        await update.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً.")
        return

    text = update.message.text.strip()
    if text.startswith("/dl_"):
        real_url = f"https://www.youtube.com/watch?v={text.replace('/dl_', '')}"
        track_platform_request(real_url)
        await process_link_info(update, context, real_url)
    elif text.startswith("http"):
        track_platform_request(text)
        await process_link_info(update, context, text)
    else:
        await update.message.reply_text("🔍 البحث عبر النص قيد التطوير حالياً، يرجى إرسال روابط مباشرة.")

# ================== جلب معلومات الرابط ==================
async def process_link_info(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    msg = await update.message.reply_text("⚡️ جاري تحليل الرابط...")
    title, uploader, thumbnail = "مقطع وسائط", "الرابط المرفق", None

    try:
        info = await asyncio.to_thread(_blocking_extract_info, url)
        title, uploader = info.get('title', title), info.get('uploader', uploader)
    except: pass

    sid = str(uuid.uuid4())[:8]
    URL_CACHE[sid] = url
    caption = f"🎬 <b>{title[:60]}</b>\n👤 المصدر: {uploader}"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎥 فيديو", callback_data=f"down_vid_{sid}")],
        [InlineKeyboardButton("🎵 صوت", callback_data=f"down_aud_{sid}"),
         InlineKeyboardButton("🎙 بصمة", callback_data=f"down_voc_{sid}")]
    ])
    await msg.delete()
    await update.message.reply_text(caption, parse_mode="HTML", reply_markup=markup)

# ================== التحميل الذكي ==================
async def download_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, action, sid = q.data.split("_")
    url = URL_CACHE.get(sid)
    
    if not url:
        await q.message.reply_text("❌ انتهت صلاحية الجلسة.")
        return

    status_msg = await q.message.reply_text("⏳ أضيفت إلى طابور التحميل الذكي...")
    out_tmpl = f"zendown_{sid}.%(ext)s"
    
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if action == 'vid' else 'bestaudio/best',
        'outtmpl': out_tmpl, 'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }
    if action != 'vid':
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3' if action == 'aud' else 'vorbis'}]

    file_path = None
    success_download = False
    is_tiktok = "tiktok.com" in url.lower()
    is_youtube = "youtube.com" in url.lower() or "youtu.be" in url.lower()

    async with DOWNLOAD_SEMAPHORE:
        await status_msg.edit_text("🚀 جاري التحميل...")

        # 1. محاولة تجاوز الحظر عبر Cobalt (يوتيوب وتيك توك)
        if (is_tiktok or is_youtube) and action in ("vid", "aud", "voc"):
            try:
                ext = 'mp3' if action == 'aud' else ('ogg' if action == 'voc' else 'mp4')
                cobalt_out = f"zendown_{sid}_cobalt.{ext}"
                file_path = await asyncio.to_thread(_blocking_cobalt_download, url, cobalt_out, action)
                if file_path and os.path.exists(file_path): success_download = True
            except Exception as e:
                log_custom_error(f"Cobalt Failed ({url}): {e}")

        # 2. خطة بديلة لتيك توك عبر TikWM
        if not success_download and is_tiktok and action in ("vid", "aud"):
            try:
                tikwm_out = f"zendown_{sid}_tikwm.{'mp3' if action == 'aud' else 'mp4'}"
                file_path = await asyncio.to_thread(_blocking_tiktok_via_tikwm, url, tikwm_out, action == "aud")
                if file_path and os.path.exists(file_path): success_download = True
            except Exception as e:
                log_custom_error(f"TikWM Failed: {e}")

        # 3. التحميل الافتراضي لبقية المنصات (إنستغرام/إكس/سناب) أو عند فشل السابق
        if not success_download:
            for attempt in range(2):
                try:
                    file_path = await asyncio.to_thread(_blocking_download, url, opts)
                    if action == "aud": file_path = file_path.rsplit('.', 1)[0] + '.mp3'
                    if action == "voc": file_path = file_path.rsplit('.', 1)[0] + '.ogg'
                    if os.path.exists(file_path):
                        success_download = True
                        break
                except Exception as e:
                    log_custom_error(f"yt-dlp Attempt {attempt+1} Failed: {e}")

    try:
        if success_download and file_path and os.path.exists(file_path):
            needs_compress = action == "vid" and (os.path.getsize(file_path) / (1024*1024)) > 45
            if needs_compress:
                await status_msg.edit_text("🗜 جاري الضغط السريع للمقطع...")
                async with COMPRESS_SEMAPHORE:
                    comp_path = file_path.rsplit('.', 1)[0] + '_c.mp4'
                    file_path = await asyncio.to_thread(_compress_video_sync, file_path, comp_path)

            if os.path.getsize(file_path) / (1024 * 1024) >= 49.5:
                await status_msg.edit_text("❌ المقطع أكبر من الحد المسموح 50 ميجا.")
                return

            await status_msg.edit_text("📤 جاري الإرسال...")
            with open(file_path, 'rb') as f:
                if action == "vid": await q.message.reply_video(video=f, caption=f"🎬 تم بواسطة {CHANNEL}")
                elif action == "aud": await q.message.reply_audio(audio=f, caption=f"🎵 تم بواسطة {CHANNEL}")
                elif action == "voc": await q.message.reply_voice(voice=f, caption=f"🎙 تم بواسطة {CHANNEL}")
            
            track_download_status(True)
            await status_msg.delete()
        else:
            track_download_status(False)
            await status_msg.edit_text("❌ فشل التحميل بسبب حماية المنصة.")
    except Exception as e:
        log_custom_error(f"Send Error: {e}")
        await status_msg.edit_text("❌ حدث خطأ أثناء إرسال الملف.")
    finally:
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass

# ================== التشغيل الرئيسي ==================
def main():
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("errors", show_errors_command))  # الأمر الجديد هنا
    app.add_handler(CommandHandler("stats", show_stats_command))
    
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(show_stats_command, pattern="^refresh_stats$"))
    app.add_handler(CallbackQueryHandler(download_action_callback, pattern="^down_"))
    
    app.add_handler(MessageHandler(filters.Regex(r"^/dl_"), handle_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 تم تشغيل محرك @ZenDown_Bot بنجاح!")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
import subprocess
import sys
import asyncio
import logging
import os
import uuid
import threading
import json
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

# تحديث تلقائي لمكتبة yt-dlp
try:
    print("🔄 جاري التحقق من تحديثات yt-dlp...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("✅ yt-dlp محدث لأحدث إصدار!")
except Exception as e:
    print(f"⚠️ فشل التحديث التلقائي: {e}")

from yt_dlp import YoutubeDL

# ================== سيرفر الصحة لإرضاء المنصة ==================
class DummyHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ZenDown_Bot is Running!")
        
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyHealthCheckHandler)
    server.serve_forever()

threading.Thread(target=start_dummy_server, daemon=True).start()

# ================== الإعدادات والتكوين ==================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("ZenDown_Bot")

# نظام تسجيل الأخطاء المخصص للمشرف
ERROR_LOGS = []
def log_custom_error(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    ERROR_LOGS.append(f"[{timestamp}] {msg}")
    if len(ERROR_LOGS) > 15:
        ERROR_LOGS.pop(0)
    logger.error(msg)

TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL = "@ZenoX_Tools"
ADMIN_ID = 6043858925

COOKIES_FILE = "/etc/secrets/cookies.txt"
COOKIES_FILE = COOKIES_FILE if os.path.exists(COOKIES_FILE) else None

MAX_CONCURRENT_DOWNLOADS = 4
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
MAX_CONCURRENT_COMPRESSIONS = 2
COMPRESS_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_COMPRESSIONS)

SEARCH_CACHE = {}
URL_CACHE = {}

# ================== نظام الإحصائيات ==================
STATS_FILE = "stats.json"

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "users": {}, "total_requests": 0, "successful_downloads": 0,
        "failed_downloads": 0, "cache_hits": 0, "sent_videos": 0,
        "request_limits": 0, "share_clicks": 0,
        "platforms": {"يوتيوب": 0, "تويتر/X": 0, "سناب شات": 0, "تيك توك": 0, "إنستغرام": 0, "بينترست": 0, "أخرى": 0}
    }

stats = load_stats()
BOT_START_TIME = datetime.now()

def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def track_user_activity(user_id):
    stats["users"][str(user_id)] = datetime.now().isoformat()
    save_stats()

def track_platform_request(url):
    stats["total_requests"] += 1
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u: stats["platforms"]["يوتيوب"] += 1
    elif "twitter.com" in u or "x.com" in u: stats["platforms"]["تويتر/X"] += 1
    elif "tiktok.com" in u: stats["platforms"]["تيك توك"] += 1
    elif "instagram.com" in u: stats["platforms"]["إنستغرام"] += 1
    elif "snapchat.com" in u: stats["platforms"]["سناب شات"] += 1
    elif "pinterest.com" in u or "pin.it" in u: stats["platforms"]["بينترست"] += 1
    else: stats["platforms"]["أخرى"] += 1
    save_stats()

def track_download_status(success: bool):
    if success: 
        stats["successful_downloads"] += 1
        stats["sent_videos"] += 1
    else: 
        stats["failed_downloads"] += 1
    save_stats()

async def check_user_subscription(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# ================== أوامر المشرف ==================
async def show_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return
    
    if not ERROR_LOGS:
        await update.message.reply_text("✅ لا توجد أخطاء مسجلة في الجلسة الحالية.")
        return
        
    text = "⚠️ <b>سجل الأخطاء الأخير (من الأقدم للأحدث):</b>\n\n" + "\n\n".join(ERROR_LOGS)
    await update.message.reply_text(text, parse_mode="HTML")

async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return
    msg = update.callback_query.message if update.callback_query else update.message
    total_users = len(stats["users"])
    
    uptime = datetime.now() - BOT_START_TIME
    days, hours, minutes = uptime.days, uptime.seconds // 3600, (uptime.seconds // 60) % 60

    stats_msg = (
        f"📊 <b>إحصائيات @ZenDown_Bot</b>\n\n"
        f"👥 المستخدمون: {total_users}\n"
        f"✅ ناجحة: {stats.get('successful_downloads', 0)} | ❌ فاشلة: {stats.get('failed_downloads', 0)}\n"
        f"⏰ وقت التشغيل: {days} يوم {hours} ساعة {minutes} دقيقة"
    )

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data="refresh_stats")]])
    if update.callback_query:
        await update.callback_query.answer("تم التحديث")
        try: await msg.edit_text(stats_msg, parse_mode="HTML", reply_markup=markup)
        except: pass
    else:
        await msg.reply_text(stats_msg, parse_mode="HTML", reply_markup=markup)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return

    text = update.message.text.replace("/broadcast", "").strip()
    if not text:
        await update.message.reply_text("اكتب الرسالة بعد الأمر.")
        return

    users = list(stats["users"].keys())
    msg = await update.message.reply_text(f"🚀 جاري الإرسال لـ {len(users)} مستخدم...")

    success, failed = 0, 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            failed += 1

    await msg.edit_text(f"✅ تمت الإذاعة!\nنجح: {success}\nفشل: {failed}")

# ================== دوال التحميل والضغط ==================
def _blocking_extract_info(url):
    opts = {
        'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'geo_bypass': True, 'nocheckcertificate': True, 'socket_timeout': 15 
    }
    with YoutubeDL(opts) as ydl: return ydl.extract_info(url, download=False)

def _blocking_download(url, opts):
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def _blocking_cobalt_download(video_url, out_path, action):
    api_url = "https://api.cobalt.tools/"
    payload = {
        "url": video_url,
        "vCodec": "h264",
        "isAudioOnly": action in ["aud", "voc"]
    }
    req = urllib.request.Request(api_url, data=json.dumps(payload).encode(), headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:200]
        raise Exception(f"HTTP {e.code} Cobalt: {body}")
        
    media_url = data.get("url")
    if not media_url and data.get("status") == "picker":
        media_url = data["picker"][0]["url"]
        
    if not media_url:
        raise Exception("Cobalt: لا يوجد رابط مباشر")
        
    dl_req = urllib.request.Request(media_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(dl_req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())
        
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    raise Exception("Cobalt: الملف الناتج فارغ")

def _blocking_tiktok_via_tikwm(url, out_path, want_audio=False):
    api_url = "https://www.tikwm.com/api/?url=" + urllib.request.quote(url, safe="")
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        raise Exception(f"TikWM Request Error: {e}")

    if data.get("code") != 0 or "data" not in data:
        raise Exception(f"TikWM Error: {data.get('msg', 'unknown')}")

    media_url = data["data"].get("music") if want_audio else (data["data"].get("play") or data["data"].get("hdplay"))
    if not media_url: raise Exception("TikWM: لا يوجد رابط")

    if media_url.startswith("/"): media_url = "https://www.tikwm.com" + media_url

    dl_req = urllib.request.Request(media_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(dl_req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    raise Exception("TikWM: الملف فارغ")

def _compress_video_sync(input_file, output_file):
    cmd = [
        'ffmpeg', '-y', '-i', input_file, '-c:v', 'libx264', '-preset', 'ultrafast',
        '-threads', '0', '-crf', '35', '-vf', "scale='min(480,iw)':-2",
        '-r', '24', '-c:a', 'aac', '-b:a', '64k', output_file
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=180)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0: return output_file
    except: pass 
    return input_file

# ================== استقبال الرسائل والبحث ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("اشترك في القناة 📡", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton("تحقق 🔍", callback_data="check_sub")]
        ])
        await update.message.reply_text("🚧 عذراً، يجب الاشتراك بالقناة أولاً.", reply_markup=markup)
        return

    await update.message.reply_text(f"أهلاً بك <b>{user.first_name}</b> في محرك التحميل! 🚀\nأرسل رابطاً للتحميل، أو اكتب نصاً للبحث.", parse_mode="HTML")

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await check_user_subscription(context.bot, q.from_user.id):
        await q.message.delete()
        await q.message.reply_text("✅ تم التحقق! أرسل رابطك الآن.")
    else:
        await q.answer("❌ لم تشترك بالقناة بعد!", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        await update.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً.")
        return

    text = update.message.text.strip()
    if text.startswith("/dl_"):
        real_url = f"https://www.youtube.com/watch?v={text.replace('/dl_', '')}"
        track_platform_request(real_url)
        await process_link_info(update, context, real_url)
    elif text.startswith("http"):
        track_platform_request(text)
        await process_link_info(update, context, text)
    else:
        await update.message.reply_text("🔍 البحث عبر النص قيد التطوير حالياً، يرجى إرسال روابط مباشرة.")

# ================== جلب معلومات الرابط ==================
async def process_link_info(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    msg = await update.message.reply_text("⚡️ جاري تحليل الرابط...")
    title, uploader, thumbnail = "مقطع وسائط", "الرابط المرفق", None

    try:
        info = await asyncio.to_thread(_blocking_extract_info, url)
        title, uploader = info.get('title', title), info.get('uploader', uploader)
    except: pass

    sid = str(uuid.uuid4())[:8]
    URL_CACHE[sid] = url
    caption = f"🎬 <b>{title[:60]}</b>\n👤 المصدر: {uploader}"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎥 فيديو", callback_data=f"down_vid_{sid}")],
        [InlineKeyboardButton("🎵 صوت", callback_data=f"down_aud_{sid}"),
         InlineKeyboardButton("🎙 بصمة", callback_data=f"down_voc_{sid}")]
    ])
    await msg.delete()
    await update.message.reply_text(caption, parse_mode="HTML", reply_markup=markup)

# ================== التحميل الذكي ==================
async def download_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, action, sid = q.data.split("_")
    url = URL_CACHE.get(sid)
    
    if not url:
        await q.message.reply_text("❌ انتهت صلاحية الجلسة.")
        return

    status_msg = await q.message.reply_text("⏳ أضيفت إلى طابور التحميل الذكي...")
    out_tmpl = f"zendown_{sid}.%(ext)s"
    
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if action == 'vid' else 'bestaudio/best',
        'outtmpl': out_tmpl, 'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }
    if action != 'vid':
        opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3' if action == 'aud' else 'vorbis'}]

    file_path = None
    success_download = False
    is_tiktok = "tiktok.com" in url.lower()
    is_youtube = "youtube.com" in url.lower() or "youtu.be" in url.lower()

    async with DOWNLOAD_SEMAPHORE:
        await status_msg.edit_text("🚀 جاري التحميل...")

        # 1. محاولة تجاوز الحظر عبر Cobalt (يوتيوب وتيك توك)
        if (is_tiktok or is_youtube) and action in ("vid", "aud", "voc"):
            try:
                ext = 'mp3' if action == 'aud' else ('ogg' if action == 'voc' else 'mp4')
                cobalt_out = f"zendown_{sid}_cobalt.{ext}"
                file_path = await asyncio.to_thread(_blocking_cobalt_download, url, cobalt_out, action)
                if file_path and os.path.exists(file_path): success_download = True
            except Exception as e:
                log_custom_error(f"Cobalt Failed ({url}): {e}")

        # 2. خطة بديلة لتيك توك عبر TikWM
        if not success_download and is_tiktok and action in ("vid", "aud"):
            try:
                tikwm_out = f"zendown_{sid}_tikwm.{'mp3' if action == 'aud' else 'mp4'}"
                file_path = await asyncio.to_thread(_blocking_tiktok_via_tikwm, url, tikwm_out, action == "aud")
                if file_path and os.path.exists(file_path): success_download = True
            except Exception as e:
                log_custom_error(f"TikWM Failed: {e}")

        # 3. التحميل الافتراضي لبقية المنصات (إنستغرام/إكس/سناب) أو عند فشل السابق
        if not success_download:
            for attempt in range(2):
                try:
                    file_path = await asyncio.to_thread(_blocking_download, url, opts)
                    if action == "aud": file_path = file_path.rsplit('.', 1)[0] + '.mp3'
                    if action == "voc": file_path = file_path.rsplit('.', 1)[0] + '.ogg'
                    if os.path.exists(file_path):
                        success_download = True
                        break
                except Exception as e:
                    log_custom_error(f"yt-dlp Attempt {attempt+1} Failed: {e}")

    try:
        if success_download and file_path and os.path.exists(file_path):
            needs_compress = action == "vid" and (os.path.getsize(file_path) / (1024*1024)) > 45
            if needs_compress:
                await status_msg.edit_text("🗜 جاري الضغط السريع للمقطع...")
                async with COMPRESS_SEMAPHORE:
                    comp_path = file_path.rsplit('.', 1)[0] + '_c.mp4'
                    file_path = await asyncio.to_thread(_compress_video_sync, file_path, comp_path)

            if os.path.getsize(file_path) / (1024 * 1024) >= 49.5:
                await status_msg.edit_text("❌ المقطع أكبر من الحد المسموح 50 ميجا.")
                return

            await status_msg.edit_text("📤 جاري الإرسال...")
            with open(file_path, 'rb') as f:
                if action == "vid": await q.message.reply_video(video=f, caption=f"🎬 تم بواسطة {CHANNEL}")
                elif action == "aud": await q.message.reply_audio(audio=f, caption=f"🎵 تم بواسطة {CHANNEL}")
                elif action == "voc": await q.message.reply_voice(voice=f, caption=f"🎙 تم بواسطة {CHANNEL}")
            
            track_download_status(True)
            await status_msg.delete()
        else:
            track_download_status(False)
            await status_msg.edit_text("❌ فشل التحميل بسبب حماية المنصة.")
    except Exception as e:
        log_custom_error(f"Send Error: {e}")
        await status_msg.edit_text("❌ حدث خطأ أثناء إرسال الملف.")
    finally:
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass

# ================== التشغيل الرئيسي ==================
def main():
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("errors", show_errors_command))  # الأمر الجديد هنا
    app.add_handler(CommandHandler("stats", show_stats_command))
    
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(show_stats_command, pattern="^refresh_stats$"))
    app.add_handler(CallbackQueryHandler(download_action_callback, pattern="^down_"))
    
    app.add_handler(MessageHandler(filters.Regex(r"^/dl_"), handle_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 تم تشغيل محرك @ZenDown_Bot بنجاح!")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
















