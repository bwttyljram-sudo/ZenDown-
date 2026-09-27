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
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

# تحديث تلقائي لمكتبة yt-dlp مع curl_cffi (انتحال بصمة المتصفح - ضروري لتيك توك)
try:
    print("🔄 جاري التحقق من تحديثات yt-dlp...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default,curl-cffi]"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("✅ yt-dlp محدث لأحدث إصدار!")
    else:
        print("❌ فشل تثبيت yt-dlp[default,curl-cffi] فعلياً! الخطأ الحقيقي:")
        print(result.stderr[-3000:])
except Exception as e:
    print(f"⚠️ فشل التحديث التلقائي: {e}")

from yt_dlp import YoutubeDL

try:
    import importlib.metadata as _im
    print(f"📦 نسخة yt-dlp: {_im.version('yt-dlp')}")
except Exception as e:
    print(f"⚠️ تعذر قراءة نسخة yt-dlp: {e}")
try:
    print(f"📦 نسخة curl_cffi: {_im.version('curl_cffi')} - (انتحال بصمة المتصفح لتيك توك)")
except Exception as e:
    print(f"❌ curl_cffi غير مثبتة! السبب: {e}")

# تثبيت/تحديث Deno تلقائياً - تيك توك يطلب حل تحدي جافاسكريبت (JS challenge)
try:
    deno_check = subprocess.run(["deno", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if deno_check.returncode != 0:
        raise FileNotFoundError
    print("✅ Deno متوفر بالفعل.")
except Exception:
    try:
        print("🔄 Deno غير موجود، جاري تثبيته...")
        subprocess.run(
            "curl -fsSL https://deno.land/install.sh | sh -s -- -y",
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
        )
        deno_bin = os.path.expanduser("~/.deno/bin")
        os.environ["PATH"] = deno_bin + os.pathsep + os.environ.get("PATH", "")
        print("✅ تم تثبيت Deno.")
    except Exception as e:
        print(f"⚠️ تعذر تثبيت Deno تلقائياً: {e}")

# ================== سيرفر الصحة لإرضاء المنصة (Render) ==================
class DummyHealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Vdy_Bot is Running!")

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
logger = logging.getLogger("Vdy_Bot")

from collections import deque
RECENT_ERRORS = deque(maxlen=40)

class _ErrorCaptureHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            try:
                msg = self.format(record)
                RECENT_ERRORS.append(f"{datetime.now().strftime('%H:%M:%S')} - {msg[:800]}")
            except Exception:
                pass

_error_handler = _ErrorCaptureHandler()
_error_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_error_handler)

TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL = "@ZenoX_Tools"
ADMIN_ID = 6043858925

COOKIES_FILE = "/etc/secrets/cookies.txt"
COOKIES_FILE = COOKIES_FILE if os.path.exists(COOKIES_FILE) else None

PROXY_URL = os.environ.get("PROXY_URL")
if PROXY_URL:
    print("🌐 تم العثور على إعدادات بروكسي، سيتم توجيه الطلبات عبره.")
else:
    print("ℹ️ لا يوجد بروكسي مُعرّف حالياً (اختياري).")

# ================== ضبط التزامن - عشان البوت ما يعلق ولا يتجاوز الذاكرة ==================
MAX_CONCURRENT_DOWNLOADS = 1
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
UPLOAD_SEMAPHORE = asyncio.Semaphore(1)

MAX_QUEUE_SIZE = 6
_pending_downloads = 0
_pending_lock = asyncio.Lock()

import concurrent.futures
BLOCKING_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="vdy-worker")

async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(BLOCKING_EXECUTOR, func, *args)

# ================== نظام الإحصائيات ==================
STATS_FILE = "stats.json"

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("users", {})
            data.setdefault("total_requests", 0)
            data.setdefault("successful_downloads", 0)
            data.setdefault("failed_downloads", 0)
            data.setdefault("rejected_non_tiktok", 0)
            data.setdefault("success_via_tikwm", 0)
            data.setdefault("success_via_heavy_path", 0)
            data.setdefault("heavy_path_attempts", 0)
            return data
        except Exception:
            pass
    return {
        "users": {},
        "total_requests": 0,
        "successful_downloads": 0,
        "failed_downloads": 0,
        "rejected_non_tiktok": 0,
        "success_via_tikwm": 0,
        "success_via_heavy_path": 0,
        "heavy_path_attempts": 0
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

def track_request():
    stats["total_requests"] += 1
    save_stats()

def track_result(success: bool):
    if success:
        stats["successful_downloads"] += 1
    else:
        stats["failed_downloads"] += 1
    save_stats()

def track_rejected():
    stats["rejected_non_tiktok"] += 1
    save_stats()

def track_tikwm_success():
    """يسجل نجاح عن طريق TikWM (المسار الخفيف السريع)."""
    stats["success_via_tikwm"] += 1
    save_stats()

def track_heavy_path_attempt():
    """يسجل كل مرة نضطر نلجأ فيها للمسار الثقيل (yt-dlp + curl_cffi + Deno) بعد فشل TikWM."""
    stats["heavy_path_attempts"] += 1
    save_stats()

def track_heavy_path_success():
    """يسجل نجاح فعلي عن طريق المسار الثقيل تحديداً - عشان نعرف هل يستاهل نضحي بالاستقرار عشانه."""
    stats["success_via_heavy_path"] += 1
    save_stats()

# ================== إدارة الاشتراك الإجباري (نفس منطق ZenDown) ==================
async def check_user_subscription(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("اشترك في القناة 📡", url=f"https://t.me/{CHANNEL.lstrip('@')}", style="primary")],
            [InlineKeyboardButton("تحقق 🔍", callback_data="check_sub", style="success")]
        ])
        await update.message.reply_text("🚧 عذراً، يجب الاشتراك بالقناة أولاً لاستخدام البوت.", reply_markup=markup)
        return

    await update.message.reply_text(
        f"أهلاً بك <b>{user.first_name}</b> في @Vdy_bot! 🎵\n"
        "أرسل رابط فيديو تيك توك وبيوصلك فوراً بدون أي خطوات إضافية.",
        parse_mode="HTML"
    )

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await check_user_subscription(context.bot, q.from_user.id):
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.reply_text("✅ تم التحقق! أرسل رابط فيديو تيك توك الآن.")
    else:
        await q.answer("❌ لم تشترك بالقناة بعد!", show_alert=True)

# ================== لوحة الأخطاء (للأدمن) ==================
async def show_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    if not RECENT_ERRORS:
        await update.message.reply_text("✅ ما فيه أي أخطاء مسجلة منذ آخر تشغيل للبوت.")
        return
    text = "🛑 <b>آخر الأخطاء المسجلة</b>\n━━━━━━━\n\n"
    for i, err in enumerate(reversed(RECENT_ERRORS), 1):
        safe_err = err.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text += f"{i}. <code>{safe_err}</code>\n\n"
        if len(text) > 3500:
            text += "... (يوجد المزيد)"
            break
    await update.message.reply_text(text, parse_mode="HTML")

# ================== لوحة الإحصائيات (للأدمن) ==================
async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return

    msg = update.callback_query.message if update.callback_query else update.message
    now = datetime.now()

    total_users = len(stats["users"])
    active_today = active_7d = active_30d = 0
    for uid, last_str in stats["users"].items():
        try:
            diff = now - datetime.fromisoformat(last_str)
            if diff <= timedelta(days=1): active_today += 1
            if diff <= timedelta(days=7): active_7d += 1
            if diff <= timedelta(days=30): active_30d += 1
        except Exception:
            pass

    total_req = stats.get("total_requests", 0)
    success = stats.get("successful_downloads", 0)
    failed = stats.get("failed_downloads", 0)
    rejected = stats.get("rejected_non_tiktok", 0)
    tikwm_ok = stats.get("success_via_tikwm", 0)
    heavy_attempts = stats.get("heavy_path_attempts", 0)
    heavy_ok = stats.get("success_via_heavy_path", 0)
    total_dl = success + failed
    rate = (success / total_dl * 100) if total_dl > 0 else 0.0
    tikwm_share = (tikwm_ok / success * 100) if success > 0 else 0.0

    uptime = now - BOT_START_TIME
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds // 60) % 60

    stats_msg = (
        "📊 <b>لوحة إحصائيات @Vdy_bot (تيك توك)</b>\n"
        "━━━━━━━\n\n"
        "👥 <b>المستخدمون</b>\n"
        "───────────────\n"
        f"📌 الإجمالي       : {total_users}\n"
        f"🟢 نشطون (اليوم)  : {active_today}\n"
        f"📅 نشطون (7 أيام) : {active_7d}\n"
        f"🗓 نشطون (30 يوم) : {active_30d}\n"
        "───────────────\n\n"
        "🎵 <b>تحميلات تيك توك</b>\n"
        "───────────────\n"
        f"🔢 إجمالي الطلبات : {total_req}\n"
        f"✅ ناجحة         : {success}\n"
        f"❌ فاشلة         : {failed}\n"
        f"✅ معدل النجاح    : {rate:.1f}%\n"
        f"🚫 روابط مرفوضة (غير تيك توك) : {rejected}\n"
        "───────────────\n\n"
        "⚖️ <b>TikWM مقابل المسار الثقيل</b>\n"
        "───────────────\n"
        f"⚡️ نجاح عبر TikWM (الخفيف) : {tikwm_ok} ({tikwm_share:.1f}% من كل النجاح)\n"
        f"🐢 محاولات لجأت للمسار الثقيل : {heavy_attempts}\n"
        f"✅ نجاح فعلي بالمسار الثقيل : {heavy_ok}\n"
        "───────────────\n\n"
        f"⏰ <b>وقت التشغيل:</b> {days} يوم {hours} ساعة {minutes} دقيقة"
    )

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data="refresh_stats", style="primary")]])
    if update.callback_query:
        await update.callback_query.answer("تم التحديث 🔄")
        try:
            await msg.edit_text(stats_msg, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
    else:
        await msg.reply_text(stats_msg, parse_mode="HTML", reply_markup=markup)

# ================== الإذاعة (للأدمن) ==================
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    text = update.message.text.replace("/broadcast", "").strip()
    if not text:
        await update.message.reply_text("الرجاء كتابة الرسالة بعد الأمر، مثال:\n/broadcast مرحباً بالجميع!")
        return
    users = list(stats["users"].keys())
    if not users:
        await update.message.reply_text("❌ لا يوجد مستخدمين مسجلين.")
        return
    msg = await update.message.reply_text(f"🚀 جاري الإرسال إلى {len(users)} مستخدم...")
    success = failed = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1
    await msg.edit_text(f"✅ تمت الإذاعة!\n\n- نجح: {success}\n- فشل: {failed}")

# ================== منطق التحميل من تيك توك ==================
def _get_urllib_opener():
    if PROXY_URL:
        proxy_handler = urllib.request.ProxyHandler({'http': PROXY_URL, 'https': PROXY_URL})
        return urllib.request.build_opener(proxy_handler)
    return urllib.request.build_opener()

def _blocking_tiktok_via_tikwm(url, out_path):
    """مسار سريع: يجيب رابط التحميل المباشر من خدمة TikWM الوسيطة، أسرع من yt-dlp غالباً."""
    opener = _get_urllib_opener()
    api_url = "https://www.tikwm.com/api/?url=" + urllib.request.quote(url, safe="")
    req = urllib.request.Request(api_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://www.tikwm.com/',
        'Accept': 'application/json, text/plain, */*'
    })
    try:
        with opener.open(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP {e.code} من TikWM")

    if data.get("code") != 0 or "data" not in data:
        raise Exception(f"TikWM API error: {data.get('msg', 'unknown')}")

    media_url = data["data"].get("play") or data["data"].get("hdplay")
    if not media_url:
        raise Exception("TikWM: لا يوجد رابط فيديو بالرد")
    if media_url.startswith("/"):
        media_url = "https://www.tikwm.com" + media_url

    dl_req = urllib.request.Request(media_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://www.tikwm.com/'
    })
    with urllib.request.urlopen(dl_req, timeout=60) as resp, open(out_path, "wb") as f:
        f.write(resp.read())

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    raise Exception("TikWM: الملف الناتج فارغ")

def _blocking_download_yt_dlp(url, out_path):
    """المسار الاحتياطي: yt-dlp + curl_cffi (انتحال بصمة) + Deno (حل تحدي جافاسكريبت)."""
    opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': out_path,
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIES_FILE,
        'proxy': PROXY_URL,
        'extractor_args': {'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}},
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'geo_bypass': True,
        'nocheckcertificate': True,
        'socket_timeout': 20,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def _blocking_upload_to_external_host(file_path):
    """لو الفيديو أكبر من حد تليجرام (50 ميجا) - يرفعه لرابط تحميل مباشر بدل ما يفشل."""
    import mimetypes
    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    with open(file_path, 'rb') as f:
        file_bytes = f.read()
    boundary = uuid.uuid4().hex

    def _body(fields, file_field_name):
        parts = []
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field_name}"; filename="{filename}"\r\n'
            f'Content-Type: {mime_type}\r\n\r\n'.encode() + file_bytes + b'\r\n'
        )
        parts.append(f'--{boundary}--\r\n'.encode())
        return b''.join(parts)

    try:
        body = _body({'reqtype': 'fileupload'}, 'fileToUpload')
        req = urllib.request.Request("https://catbox.moe/user/api.php", data=body,
                                      headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            result_url = resp.read().decode().strip()
            if result_url.startswith('http'):
                return result_url
    except Exception as e:
        logger.error(f"External host (catbox) failed: {e}")

    try:
        body = _body({}, 'file')
        req = urllib.request.Request("https://0x0.st", data=body, headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            result_url = resp.read().decode().strip()
            if result_url.startswith('http'):
                return result_url
    except Exception as e:
        logger.error(f"External host (0x0.st) failed: {e}")

    raise Exception("فشلت كل خدمات الاستضافة الاحتياطية")

def _is_tiktok_url(url: str) -> bool:
    return "tiktok.com" in url.lower()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        await update.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً.")
        return

    text = update.message.text.strip()

    if not text.startswith("http"):
        await update.message.reply_text("أرسل رابط فيديو تيك توك بس 🙏")
        return

    # فحص سريع فوري (بدون أي اتصال إنترنت) - قبل أي معالجة ثقيلة
    if not _is_tiktok_url(text):
        track_rejected()
        await update.message.reply_text("عذراً أرسل رابط فيديو تيك توك.. لتحميل هذا الفيديو استخدم بوت @ZenDown_Bot")
        return

    track_request()

    # فحص الزحمة - لو الطابور ممتلئ، رفض فوري بدل انتظار بلا نهاية
    global _pending_downloads
    async with _pending_lock:
        if _pending_downloads >= MAX_QUEUE_SIZE:
            await update.message.reply_text("🚧 البوت مزدحم جداً حالياً.\nحاول مرة ثانية بعد كم دقيقة 🙏")
            return
        _pending_downloads += 1

    status_msg = await update.message.reply_text("⏳ جاري التحميل...")
    sid = uuid.uuid4().hex[:8]
    file_path = None
    success = False

    try:
        async with DOWNLOAD_SEMAPHORE:
            # المسار الأول: TikWM (أسرع، خفيف على الذاكرة)
            try:
                tikwm_out = f"vdy_{sid}_tikwm.mp4"
                file_path = await asyncio.wait_for(run_blocking(_blocking_tiktok_via_tikwm, text, tikwm_out), timeout=60)
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    success = True
                    track_tikwm_success()
            except asyncio.TimeoutError:
                logger.error("TikWM timed out after 60s")
                file_path = None
            except Exception as e:
                logger.error(f"TikWM failed: {e}")
                file_path = None

            # المسار الاحتياطي: yt-dlp + curl_cffi + Deno
            if not success:
                track_heavy_path_attempt()
                for attempt in range(3):
                    try:
                        yt_out = f"vdy_{sid}.%(ext)s"
                        file_path = await asyncio.wait_for(run_blocking(_blocking_download_yt_dlp, text, yt_out), timeout=90)
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                            success = True
                            track_heavy_path_success()
                            break
                    except asyncio.TimeoutError:
                        logger.error(f"Attempt {attempt + 1} timed out after 90s")
                    except Exception as e:
                        logger.error(f"Attempt {attempt + 1} failed: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2)

        if success and file_path and os.path.exists(file_path):
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if size_mb >= 49.5:
                await status_msg.edit_text("📦 المقطع كبير، جاري رفعه لرابط تحميل مباشر...")
                try:
                    async with UPLOAD_SEMAPHORE:
                        external_url = await run_blocking(_blocking_upload_to_external_host, file_path)
                    await update.message.reply_text(f"✅ المقطع كبير ({size_mb:.1f} ميجا)، حمّله من هنا:\n{external_url}")
                    track_result(True)
                    await status_msg.delete()
                except Exception as e:
                    logger.error(f"External upload failed: {e}")
                    await status_msg.edit_text("❌ تعذر رفع المقطع الكبير حالياً، حاول لاحقاً.")
                    track_result(False)
            else:
                await status_msg.edit_text("📤 جاري الإرسال...")
                with open(file_path, 'rb') as f:
                    await update.message.reply_video(video=f, caption="🎬 تم بواسطة @Vdy_bot", supports_streaming=True)
                track_result(True)
                await status_msg.delete()
        else:
            track_result(False)
            await status_msg.edit_text("❌ تعذر تحميل هذا المقطع، جرب رابط ثاني أو حاول لاحقاً.")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        track_result(False)
        try:
            await status_msg.edit_text("❌ حدث خطأ غير متوقع.")
        except Exception:
            pass
    finally:
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except Exception: pass
        async with _pending_lock:
            _pending_downloads -= 1

# ================== معالج الأخطاء العام ==================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    import traceback
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(f"استثناء غير متوقع (Unhandled): {context.error}\n{tb_string[-1500:]}")

# ================== حارس الذاكرة ==================
async def _memory_watchdog():
    THRESHOLD_MB = 400
    while True:
        await asyncio.sleep(15)
        try:
            with open('/proc/self/status') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        rss_mb = int(line.split()[1]) / 1024
                        if rss_mb >= THRESHOLD_MB:
                            logger.error(f"Memory watchdog: {rss_mb:.0f}MB تجاوزت الحد - إعادة تشغيل منظمة.")
                            os._exit(0)
                        break
        except Exception as e:
            logger.error(f"Memory watchdog check failed: {e}")

async def _post_init(application):
    asyncio.create_task(_memory_watchdog())

# ================== التشغيل الرئيسي ==================
def main():
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).post_init(_post_init).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("stats", show_stats_command))
    app.add_handler(CommandHandler("errors", show_errors_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(احصائيات|إحصائيات)$"), show_stats_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(اخطاء|أخطاء)$"), show_errors_command))
    app.add_handler(CallbackQueryHandler(show_stats_command, pattern="^refresh_stats$"))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 تم تشغيل محرك @Vdy_bot بنجاح! مخصص لتيك توك فقط.")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()


