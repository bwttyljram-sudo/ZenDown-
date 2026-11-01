import subprocess
import sys
import asyncio
import logging
import os
import uuid
import threading
import json
import re
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, ApplicationHandlerStop, filters
)

# تحديث تلقائي لمكتبة yt-dlp + تثبيت أداة bgutil (تجربة حل يوتيوب - تولّد "رمز إثبات أصل"
# PO Token تلقائياً بدون الحاجة لكوكيز، باستخدام محرك Deno بدل حساب مستخدم حقيقي)
try:
    print("🔄 جاري التحقق من تحديثات yt-dlp...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default,curl-cffi]", "bgutil-ytdlp-pot-provider"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print("✅ yt-dlp و bgutil-ytdlp-pot-provider محدثة!")
    else:
        print("❌ فشل تثبيت الحزم! الخطأ الحقيقي:")
        print(result.stderr[-3000:])
except Exception as e:
    print(f"⚠️ فشل التحديث التلقائي: {e}")

from yt_dlp import YoutubeDL

try:
    import importlib.metadata as _im
    print(f"📦 نسخة yt-dlp المثبتة فعلياً: {_im.version('yt-dlp')}")
except Exception as e:
    print(f"⚠️ تعذر قراءة نسخة yt-dlp: {e}")
try:
    print(f"📦 نسخة bgutil-ytdlp-pot-provider: {_im.version('bgutil-ytdlp-pot-provider')}")
except Exception as e:
    print(f"❌ bgutil-ytdlp-pot-provider غير مثبتة! السبب: {e}")

# تثبيت Deno - محرك bgutil يحتاجه عشان يولّد رمز PO Token تلقائياً لكل فيديو يوتيوب
try:
    deno_check = subprocess.run(["deno", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if deno_check.returncode != 0:
        raise FileNotFoundError
    print("✅ Deno متوفر بالفعل.")
except Exception:
    try:
        print("🔄 Deno غير موجود، جاري تثبيته (مطلوب لحل يوتيوب)...")
        subprocess.run(
            "curl -fsSL https://deno.land/install.sh | sh -s -- -y",
            shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
        )
        deno_bin = os.path.expanduser("~/.deno/bin")
        os.environ["PATH"] = deno_bin + os.pathsep + os.environ.get("PATH", "")
        print("✅ تم تثبيت Deno.")
    except Exception as e:
        print(f"⚠️ تعذر تثبيت Deno تلقائياً: {e}")

# تحميل سكربتات bgutil (المكون اللي فعلياً يولّد الرمز - مكتبة pip بس تربطه بـ yt-dlp،
# والسكربت نفسه لازم يكون موجود محلياً). ننزّله مرة وحدة بالمسار الافتراضي اللي yt-dlp يدوّر عليه.
_BGUTIL_HOME = os.path.expanduser("~/bgutil-ytdlp-pot-provider")
if not os.path.exists(_BGUTIL_HOME):
    try:
        print("🔄 جاري تحميل سكربتات bgutil (مطلوبة لتوليد رمز يوتيوب)...")
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git", _BGUTIL_HOME],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60
        )
        if os.path.exists(_BGUTIL_HOME):
            print("✅ تم تحميل سكربتات bgutil.")
        else:
            print("⚠️ فشل تحميل سكربتات bgutil - يوتيوب ممكن يستمر يفشل.")
    except Exception as e:
        print(f"⚠️ تعذر تحميل سكربتات bgutil: {e}")
else:
    print("✅ سكربتات bgutil موجودة بالفعل.")


# ================== سيرفر الصحة لإرضاء المنصة (Render/UptimeRobot) ==================
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

# ذاكرة تخزن آخر الأخطاء - عشان الأدمن يشوفها من داخل تيليجرام بدون الدخول لـ Render
# فيه قائمتين: وحدة لكل الأخطاء، ووحدة "منقّاة" بدون ضجيج تيك توك/يوتيوب المتكرر
# عشان أخطاء إنستقرام/سناب شات/فيسبوك/بينترست ما تنطمر وتضيع بسرعة
from collections import deque
RECENT_ERRORS = deque(maxlen=40)
RECENT_ERRORS_OTHER = deque(maxlen=40)
_NOISY_PLATFORMS_KEYWORDS = ("tiktok", "youtube", "tikwm")

class _ErrorCaptureHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            try:
                msg = self.format(record)
                entry = f"{datetime.now().strftime('%H:%M:%S')} - {msg[:1200]}"
                RECENT_ERRORS.append(entry)
                if not any(kw in msg.lower() for kw in _NOISY_PLATFORMS_KEYWORDS):
                    RECENT_ERRORS_OTHER.append(entry)
            except Exception:
                pass

_error_handler = _ErrorCaptureHandler()
_error_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_error_handler)  # يلتقط من كل اللوقرز، مو بس بتاعنا

TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL = "@ZenoX_Tools"
ADMIN_ID = 6043858925

# ملف كوكيز اختياري - لو رفعته كـ Secret File بـ Render باسم cookies.txt
# بيُستخدم تلقائياً لتجاوز حظر تيك توك، بدون أي تعديل إضافي بالكود
COOKIES_SECRET_PATH = "/etc/secrets/cookies.txt"
COOKIES_FILE = None
# ملفات Render السرية للقراءة فقط، بينما yt-dlp يحاول يكتب على ملف الكوكيز عند الإغلاق
# (فيطلع خطأ Read-only file system). الحل: ننسخ الملف لمكان قابل للكتابة ونستخدم النسخة.
if os.path.exists(COOKIES_SECRET_PATH):
    try:
        import shutil
        shutil.copyfile(COOKIES_SECRET_PATH, "/tmp/cookies.txt")
        COOKIES_FILE = "/tmp/cookies.txt"
    except Exception as _e:
        print(f"⚠️ تعذر نسخ ملف الكوكيز: {_e}")
if COOKIES_FILE:
    print("🍪 تم العثور على ملف كوكيز، سيتم استخدامه لتحسين التحميل من تيك توك.")
else:
    print("ℹ️ لا يوجد ملف كوكيز حالياً (اختياري).")

# بروكسي اختياري - لو أضفته كمتغير بيئة PROXY_URL بـ Render
# الصيغة: http://username:password@host:port  (تجيك من Webshare.io مثلاً)
# يُستخدم تلقائياً لتغيير عنوان IP اللي يطلع منه البوت لكل الطلبات
PROXY_URL = os.environ.get("PROXY_URL")
if PROXY_URL:
    print("🌐 تم العثور على إعدادات بروكسي، سيتم توجيه الطلبات عبره.")
else:
    print("ℹ️ لا يوجد بروكسي مُعرّف حالياً (اختياري).")

# أقصى عدد تحميلات متزامنة لحماية الموارد (تحميل فقط - لا يشمل الضغط)
MAX_CONCURRENT_DOWNLOADS = 1
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# عداد الطلبات المنتظرة بالطابور - بدون سقف، أي عدد طلبات ممكن ينتظر بلا حد، وكل طلب منتظر
# ياخذ ذاكرة وهو واقف بالدور. وقت الزحمة الكبيرة (آلاف المستخدمين)، الطابور يكبر بلا توقف
# ويصير هو نفسه سبب انفجار الذاكرة (حلقة مفرغة). بحد أقصى للطابور، أي طلب زايد يترفض فوراً
# برسالة واضحة بدل ما يتراكم للأبد.
MAX_QUEUE_SIZE = 6
_pending_downloads = 0
_pending_lock = asyncio.Lock()

# سيمافور مستقل للبحث - يمنع انفجار الذاكرة لو كثير مستخدمين بحثوا بنفس اللحظة


# سيمافور لتحليل الروابط (استخراج المعلومات فقط، قبل التحميل) - كان بدون أي حد أقصى إطلاقاً
# قبل هذا التعديل، أي عدد من المستخدمين ممكن يشغلوا عدد غير محدود من الثريدات بنفس اللحظة
# لتحليل روابطهم، وكل ثريد ياخذ ذاكرة (stack) وما يترحرر بسرعة - وهذا مرشح قوي لتسرب الذاكرة
# التراكمي مع الوقت تحت الحمل الحقيقي (300+ مستخدم).

# سيمافور مخصص لرفع الملفات الكبيرة لخدمة استضافة خارجية (بديل الملفات فوق 50 ميجا).
# هالعملية تحمّل الملف كامل بالذاكرة (RAM) مرتين تقريباً وقت الرفع - لو صار أكثر من رفعة
# كبيرة بنفس اللحظة، الذاكرة تقفز فجأة بشكل حاد بدل تسرب تدريجي، وده كان على الأرجح سبب
# التوقف المفاجئ (بدل إعادة التشغيل التدريجية المعتادة). بتحديد رفعة وحدة بالوقت، نمنع القفزة.

# منفذ ثريدات محدود صراحة بدل الاعتماد على asyncio.to_thread (اللي يستخدم منفذ افتراضي
# غير محدود عملياً تحت الحمل). كل عملية حاجزة بالبوت (تحميل/ضغط/بحث/تحليل رابط) تمر من هنا،
# فمهما زاد عدد المستخدمين بنفس اللحظة، عدد الثريدات الفعلي المفتوح ما يتعدى هالسقف أبداً -
# وهذا يمنع تراكم ذاكرة الـ stack بتاع الثريدات اللي كان على الأرجح السبب الرئيسي للتسرب.
import concurrent.futures
BLOCKING_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="zendown-worker")

async def run_blocking(func, *args):
    """يشغّل دالة حاجزة على المنفذ المحدود بدل asyncio.to_thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(BLOCKING_EXECUTOR, func, *args)

# ذاكرة مؤقتة
from collections import OrderedDict

class BoundedCache(OrderedDict):
    """كاش بحد أقصى للحجم - أقدم عنصر ينحذف تلقائياً لما يمتلئ، عشان الذاكرة ما تكبر للأبد."""
    def __init__(self, max_size=500):
        super().__init__()
        self.max_size = max_size

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        if len(self) > self.max_size:
            self.popitem(last=False)

URL_CACHE = BoundedCache(max_size=500)

# ================== نظام الإحصائيات ==================
STATS_FILE = "stats.json"

PLATFORM_NAMES = ["يوتيوب", "تويتر/X", "سناب شات", "تيك توك", "إنستغرام", "بينترست", "فيسبوك", "أخرى"]

def _empty_platform_stats():
    return {p: {"total": 0, "success": 0, "failed": 0} for p in PLATFORM_NAMES}

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = None
        if data is not None:
            # ترحيل الهيكل القديم (قبل إضافة تتبع نجاح/فشل لكل منصة) للهيكل الجديد
            old_platforms = data.get("platforms")
            needs_migration = (
                "platform_stats" not in data
                or not isinstance(data.get("platform_stats"), dict)
                or "فيسبوك" not in data.get("platform_stats", {})
            )
            if needs_migration:
                new_ps = _empty_platform_stats()
                if isinstance(old_platforms, dict):
                    for p, count in old_platforms.items():
                        if p in new_ps:
                            new_ps[p]["total"] = count
                            # ما عندنا تفصيل قديم لنجاح/فشل لكل منصة، فنقسمها تقريبياً
                            # حسب النسبة العامة القديمة عشان ما تضيع البيانات كلياً
                data["platform_stats"] = new_ps
            data.setdefault("users", {})
            data.setdefault("total_requests", 0)
            data.setdefault("successful_downloads", 0)
            data.setdefault("failed_downloads", 0)
            data.setdefault("cache_hits", 0)
            data.setdefault("sent_videos", 0)
            data.setdefault("request_limits", 0)
            data.setdefault("share_clicks", 0)
            return data
    return {
        "users": {},
        "total_requests": 0,
        "successful_downloads": 0,
        "failed_downloads": 0,
        "cache_hits": 0,
        "sent_videos": 0,
        "request_limits": 0,
        "share_clicks": 0,
        "platform_stats": _empty_platform_stats()
    }

stats = load_stats()
BOT_START_TIME = datetime.now()

def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ================== الحفظ الدائم عبر Turso (اختياري) ==================
# الملف المحلي (stats.json) ينمسح مع كل إعادة تشغيل لأن قرص Render المجاني مؤقت.
# لو عُرّفت بيانات Turso، نحمّل آخر نسخة محفوظة عند الإقلاع، ونحفظ نسخة جديدة كل دقيقة
# بالخلفية - بدون ما نغيّر طريقة عمل stats.json المحلي (يضل يشتغل زي ما هو، نسخة احتياطية سريعة).
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
# نحول الرابط من بروتوكول WebSocket (libsql://) لبروتوكول HTTP عادي (https://) - نفس قاعدة
# البيانات بالضبط، بس HTTP أكثر توافقاً مع بيئة ريندر (WebSocket كان يفشل بخطأ 400 كل مرة).
TURSO_HTTP_URL = TURSO_DATABASE_URL.replace("libsql://", "https://", 1) if TURSO_DATABASE_URL else None
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

try:
    import libsql_client
    _LIBSQL_AVAILABLE = True
except Exception:
    _LIBSQL_AVAILABLE = False

TURSO_ENABLED = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN and _LIBSQL_AVAILABLE)
if TURSO_ENABLED:
    print("🗄️ تم العثور على إعدادات Turso - الإحصائيات والمستخدمين بيتحفظوا بشكل دائم عبر إعادة التشغيل.")
    # سطر تشخيصي: يوري بالضبط أي بروتوكول يستخدم فعلياً وقت التشغيل (بدون كشف التوكن) -
    # عشان نتأكد بدقة إنه http وليس wss بدون ما نخمن من رسائل الخطأ بس
    print(f"🔎 Turso protocol check: TURSO_HTTP_URL starts with = {TURSO_HTTP_URL[:12]}...")
elif TURSO_DATABASE_URL or TURSO_AUTH_TOKEN:
    print("⚠️ فيه إعداد Turso ناقص (الرابط أو التوكن مفقود) - رجعنا للوضع المحلي المؤقت.")
else:
    print("ℹ️ لا يوجد اتصال Turso - البيانات بتنمسح مع كل إعادة تشغيل (الوضع الافتراضي).")

async def turso_load_on_startup():
    """يحمّل آخر نسخة محفوظة من البيانات عند إقلاع البوت، لو موجودة."""
    if not TURSO_ENABLED:
        return
    global stats
    try:
        async with libsql_client.create_client(url=TURSO_HTTP_URL, auth_token=TURSO_AUTH_TOKEN) as client:
            await client.execute(
                "CREATE TABLE IF NOT EXISTS bot_state (id INTEGER PRIMARY KEY, data TEXT, updated_at TEXT)"
            )
            rs = await client.execute("SELECT data FROM bot_state WHERE id = 1")
            if rs.rows:
                saved = json.loads(rs.rows[0][0])
                stats.update(saved)
                stats.setdefault("platform_stats", _empty_platform_stats())
                logger.info(f"✅ Turso: تم تحميل البيانات المحفوظة ({len(stats.get('users', {}))} مستخدم).")
            else:
                logger.info("ℹ️ Turso: ما فيه بيانات محفوظة سابقاً، بدء من الصفر.")
    except Exception as e:
        logger.error(f"Turso load failed: {e}")

async def turso_push_now():
    """يحفظ نسخة من البيانات الحالية بـ Turso فوراً (بدون انتظار الدورة التالية)."""
    if not TURSO_ENABLED:
        return
    try:
        async with libsql_client.create_client(url=TURSO_HTTP_URL, auth_token=TURSO_AUTH_TOKEN) as client:
            payload = json.dumps(stats, ensure_ascii=False)
            await client.execute(
                "INSERT INTO bot_state (id, data, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                [payload, datetime.now().isoformat()]
            )
    except Exception as e:
        logger.error(f"Turso sync failed: {e}")

async def turso_sync_loop():
    """
    يحفظ نسخة من البيانات كل 20 ثانية (بدل دقيقة كاملة) - عشان نقلل فجوة الوقت اللي ممكن
    تضيع فيها بيانات لو صارت إعادة تشغيل (خصوصاً من حارس الذاكرة) قبل أول حفظ دوري.
    """
    if not TURSO_ENABLED:
        return
    while True:
        await asyncio.sleep(20)
        await turso_push_now()

def track_user_activity(user_id):
    uid = str(user_id)
    stats["users"][uid] = datetime.now().isoformat()
    # أول مرة نشوف هالمستخدم - نسجل تاريخ الانضمام مرة وحدة بس (ما نكتبه فوق نفسه بعدين)
    stats.setdefault("user_profiles", {})
    if uid not in stats["user_profiles"]:
        stats["user_profiles"][uid] = {
            "joined": datetime.now().isoformat(),
            "total_downloads": 0,
            "platforms": {}
        }
    save_stats()

def track_user_download(user_id, platform):
    """يسجل تحميل ناجح لمستخدم معين - يُستخدم بس لعرض لوحة 'إحصائياتي' الشخصية."""
    uid = str(user_id)
    stats.setdefault("user_profiles", {})
    profile = stats["user_profiles"].setdefault(uid, {"joined": datetime.now().isoformat(), "total_downloads": 0, "platforms": {}})
    profile["total_downloads"] = profile.get("total_downloads", 0) + 1
    if platform:
        profile.setdefault("platforms", {})
        profile["platforms"][platform] = profile["platforms"].get(platform, 0) + 1
    save_stats()

def detect_platform(url: str) -> str:
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u: return "يوتيوب"
    if "twitter.com" in u or "x.com" in u: return "تويتر/X"
    if "tiktok.com" in u: return "تيك توك"
    if "instagram.com" in u: return "إنستغرام"
    if "snapchat.com" in u: return "سناب شات"
    if "pinterest.com" in u or "pin.it" in u: return "بينترست"
    if "facebook.com" in u or "fb.watch" in u: return "فيسبوك"
    return "أخرى"

def track_platform_request(url: str) -> str:
    """يرصد الطلب حسب المنصة، ويرجّع اسم المنصة عشان نستخدمه لاحقاً عند تسجيل النجاح/الفشل."""
    stats["total_requests"] += 1
    platform = detect_platform(url)
    stats.setdefault("platform_stats", _empty_platform_stats())
    if platform not in stats["platform_stats"]:
        stats["platform_stats"][platform] = {"total": 0, "success": 0, "failed": 0}
    stats["platform_stats"][platform]["total"] += 1
    save_stats()
    return platform

def track_download_status(success: bool, platform: str = None):
    if success:
        stats["successful_downloads"] += 1
        stats["sent_videos"] += 1
    else:
        stats["failed_downloads"] += 1

    if platform:
        stats.setdefault("platform_stats", _empty_platform_stats())
        if platform not in stats["platform_stats"]:
            stats["platform_stats"][platform] = {"total": 0, "success": 0, "failed": 0}
        if success:
            stats["platform_stats"][platform]["success"] += 1
        else:
            stats["platform_stats"][platform]["failed"] += 1
    save_stats()

# ================== إدارة الاشتراك والتحقق ==================
async def check_user_subscription(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# ================== عرض آخر الأخطاء (للأدمن فقط) ==================
def _format_errors_list(title, errors_deque):
    if not errors_deque:
        return f"✅ {title}\n\nما فيه أي أخطاء مسجلة منذ آخر تشغيل للبوت."
    text = f"🛑 <b>{title}</b>\n━━━━━━━\n\n"
    for i, err in enumerate(reversed(errors_deque), 1):
        # هروب من رموز HTML عشان ما يكسر تنسيق الرسالة
        safe_err = err.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text += f"{i}. <code>{safe_err}</code>\n\n"
        if len(text) > 3500:  # حد أقصى تقريبي لرسالة تيليجرام
            text += "... (يوجد المزيد، هذا آخر جزء ظاهر)"
            break
    return text

async def cookies_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """للأدمن فقط: يفحص ملف الكوكيز (بدون إظهار أي قيمة سرية)."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    path = "/etc/secrets/cookies.txt"
    if not os.path.exists(path):
        await update.effective_message.reply_text("❌ ملف الكوكيز غير موجود في السيرفر (المسار: /etc/secrets/cookies.txt).\nتأكد من اسم الملف في Secret Files.")
        return
    try:
        raw = open(path, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        await update.effective_message.reply_text(f"❌ تعذر قراءة الملف: {e}")
        return
    lines = [l for l in raw.splitlines() if l.strip() and not l.startswith("#")]
    good = [l.split("\t") for l in lines if len(l.split("\t")) == 7]
    bad = len(lines) - len(good)
    names = sorted({r[5] for r in good if "youtube.com" in r[0] or "google.com" in r[0]})
    first = raw.splitlines()[0][:40] if raw.strip() else "(فارغ)"
    await update.effective_message.reply_text(
        f"🍪 <b>فحص الكوكيز</b>\n"
        f"الملف موجود ✅ ({len(raw)} حرف)\n"
        f"السطر الأول: <code>{first}</code>\n"
        f"أسطر صحيحة (7 حقول): {len(good)}\n"
        f"أسطر خاطئة: {bad}\n"
        f"كوكيز يوتيوب/قوقل: {', '.join(names) if names else 'لا يوجد'}\n"
        f"البوت يستخدم الملف: {'نعم ✅' if COOKIES_FILE else 'لا ❌ (أعد تشغيل البوت)'}",
        parse_mode="HTML")

async def show_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض أخطاء المنصات الأخرى فقط (بدون تيك توك ويوتيوب) عشان ما تنطمر بضجيج تيك توك المتكرر."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    text = _format_errors_list("آخر أخطاء المنصات الأخرى (بدون تيك توك/يوتيوب)", RECENT_ERRORS_OTHER)
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def show_all_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض كل الأخطاء المسجلة شامل تيك توك ويوتيوب."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    text = _format_errors_list("كل الأخطاء المسجلة (شامل تيك توك ويوتيوب)", RECENT_ERRORS)
    await update.effective_message.reply_text(text, parse_mode="HTML")

# ================== لوحة إحصائياتي (شخصية لكل مستخدم) ==================
PLATFORM_ICONS = {
    "يوتيوب": "▶️", "تويتر/X": "𝕏", "سناب شات": "👻", "تيك توك": "🎵",
    "إنستغرام": "📸", "بينترست": "📌", "فيسبوك": "📘", "أخرى": "🌐"
}

async def show_my_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    uid = str(user.id)
    profile = stats.get("user_profiles", {}).get(uid)

    if not profile or profile.get("total_downloads", 0) == 0:
        await update.message.reply_text(
            "📊 <b>إحصائياتك</b>\n━━━━━━━\n\nما سويت أي تحميل لسا! أرسل رابط فيديو وابدأ 🚀",
            parse_mode="HTML"
        )
        return

    try:
        joined_date = datetime.fromisoformat(profile["joined"]).strftime("%Y-%m-%d")
    except Exception:
        joined_date = "غير معروف"

    total = profile.get("total_downloads", 0)
    platforms = profile.get("platforms", {})
    sorted_platforms = sorted(platforms.items(), key=lambda x: x[1], reverse=True)

    platform_lines = []
    for p_name, count in sorted_platforms:
        icon = PLATFORM_ICONS.get(p_name, "▫️")
        pct = (count / total * 100) if total > 0 else 0
        platform_lines.append(f"{icon} {p_name}  —  {count} ({pct:.0f}%)")
    platforms_str = "\n".join(platform_lines) if platform_lines else "لا يوجد بعد"

    top_platform = sorted_platforms[0][0] if sorted_platforms else "—"
    top_icon = PLATFORM_ICONS.get(top_platform, "▫️")

    name = user.first_name or "صديقنا"
    _pu = premium_until(user.id)
    pro_line = f"👑 <b>Pro</b> فعّال حتى {_pu.strftime('%Y-%m-%d')}\n" if _pu else ""
    msg = (
        f"📊 <b>إحصائياتك يا {name}</b>\n"
        "━━━━━━━\n\n"
        f"{pro_line}"
        f"📅 عضو معنا منذ: <b>{joined_date}</b>\n"
        f"🎬 إجمالي التحميلات: <b>{total}</b>\n"
        f"⭐ منصتك المفضلة: {top_icon} <b>{top_platform}</b>\n"
        "───────────────\n"
        "🌎 <b>حسب المنصة</b>\n"
        "───────────────\n"
        f"{platforms_str}\n"
        "───────────────\n\n"
        "شكراً لاستخدامك @ZenDown_Bot 💙"
    )
    await update.message.reply_text(msg, parse_mode="HTML")

# ================== لوحة الإحصائيات ==================
async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return

    msg = update.callback_query.message if update.callback_query else update.message
    now = datetime.now()
    
    total_users = len(stats["users"])
    active_now = 0
    active_today = 0
    active_7d = 0
    active_30d = 0

    for uid, last_str in stats["users"].items():
        try:
            last_time = datetime.fromisoformat(last_str)
            diff = now - last_time
            if diff <= timedelta(minutes=5): active_now += 1
            if diff <= timedelta(days=1): active_today += 1
            if diff <= timedelta(days=7): active_7d += 1
            if diff <= timedelta(days=30): active_30d += 1
        except Exception:
            pass

    total_req = stats.get("total_requests", 0)
    success_dl = stats.get("successful_downloads", 0)
    failed_dl = stats.get("failed_downloads", 0)
    cache_hits = stats.get("cache_hits", 0)
    sent_vids = stats.get("sent_videos", 0)
    req_limits = stats.get("request_limits", 0)
    share_clicks = stats.get("share_clicks", 0)
    star_donations = stats.get("star_donations", 0)

    qr_u, qr_n = feat_counts("qr")
    eo_u, _ = feat_counts("edit_open")
    ed_u, ed_n = feat_counts("edit_done")
    oc_u, oc_n = feat_counts("ocr")
    oc_f = stats.get("ocr_fail", 0)
    trials_used = sum(p.get("free_edits", 0) for p in stats.get("user_profiles", {}).values())

    total_dl = success_dl + failed_dl
    rate = (success_dl / total_dl * 100) if total_dl > 0 else 0.0

    uptime = datetime.now() - BOT_START_TIME
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds // 60) % 60

    platform_icons = {
        "يوتيوب": "▶️",
        "تويتر/X": "𝕏",
        "سناب شات": "👻",
        "تيك توك": "🎵",
        "إنستغرام": "📸",
        "بينترست": "📌",
        "فيسبوك": "📘",
        "أخرى": "🌐"
    }

    platform_stats = stats.get("platform_stats", _empty_platform_stats())
    sorted_platforms = sorted(platform_stats.items(), key=lambda x: x[1].get("total", 0), reverse=True)

    platform_lines = []
    for idx, (p_name, pdata) in enumerate(sorted_platforms, 1):
        if pdata.get("total", 0) == 0:
            continue
        icon = platform_icons.get(p_name, "▫️")
        platform_lines.append(
            f"{idx}. {icon} <b>{p_name}</b>\n"
            f"   الإجمالي: {pdata.get('total', 0)} | ✅ ناجحة: {pdata.get('success', 0)} | ❌ فاشلة: {pdata.get('failed', 0)}"
        )

    platforms_str = "\n".join(platform_lines) if platform_lines else "لا يوجد طلبات مسجلة بعد."

    stats_msg = (
        "📊 <b>لوحة إحصائيات @ZenDown_Bot</b>\n"
        "━━━━━━━\n\n"
        "👥 <b>المستخدمون</b>\n"
        "───────────────\n"
        f"📌 الإجمالي       : {total_users}\n"
        f"🟢 تفاعلوا آخر 5 د : {active_now}\n"
        f"☀️ نشطون (اليوم)  : {active_today}\n"
        f"📅 نشطون (7 أيام) : {active_7d}\n"
        f"🗓 نشطون (30 يوم) : {active_30d}\n"
        "───────────────\n\n"
        "📫 <b>التحميلات</b>\n"
        "───────────────\n"
        f"🔢 إجمالي الطلبات  : {total_req}\n"
        f"✅ ناجحة         : {success_dl}\n"
        f"❌ فاشلة         : {failed_dl}\n"
        f"🎬 فيديوهات أُرسلت : {sent_vids}\n"
        "───────────────\n\n"
        "🌎 <b>المنصات الأكثر طلباً</b>\n"
        "───────────────\n"
        f"{platforms_str}\n"
        "───────────────\n\n"
        "⚡️ <b>الأداء</b>\n"
        "───────────────\n"
        f"✅ معدل النجاح     : {rate:.1f}%\n"
        "───────────────\n\n"
        "📱 <b>ميزة QR</b>\n"
        "───────────────\n"
        f"🔢 رموز مولّدة     : {qr_n}\n"
        f"👥 المستخدمون      : {qr_u}\n"
        "───────────────\n\n"
        "🎬 <b>الفلاتر والقص</b>\n"
        "───────────────\n"
        f"👀 فتحوا القائمة   : {eo_u} مستخدم\n"
        f"✅ طبّقوا فعلاً     : {ed_u} مستخدم ({ed_n} عملية)\n"
        f"🎁 تجارب مجانية مستهلكة : {trials_used}\n"
        "───────────────\n\n"
        "🔤 <b>استخراج النص</b>\n"
        "───────────────\n"
        f"✅ ناجحة           : {oc_n}\n"
        f"❌ بدون نتيجة/فاشلة : {oc_f}\n"
        f"👥 المستخدمون      : {oc_u}\n"
        "───────────────\n\n"
        "👑 <b>Pro والمدفوعات</b>\n"
        "───────────────\n"
        f"👑 مشتركون الآن    : {sum(1 for _u in stats.get('premium', {}) if premium_until(_u))}\n"
        f"🧾 اشتراكات مباعة  : {stats.get('plan_sales', 0)}\n"
        f"⭐ النجوم المستلمة  : {stats.get('stars_received', 0)}\n"
        f"🌟 تبرعات بالنجوم  : {star_donations}\n"
        "───────────────\n\n"
        f"⏰ <b>وقت التشغيل:</b> {days} يوم {hours} ساعة {minutes} دقيقة\n"
        "🔄 <b>تحديث الإحصائيات:</b> كل 100 حدث أو عند الإيقاف"
    )

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data="refresh_stats", style="primary")]])
    if update.callback_query and update.callback_query.data == "refresh_stats":
        await update.callback_query.answer("تم التحديث 🔄")
        try:
            await msg.edit_text(stats_msg, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
    else:
        await msg.reply_text(stats_msg, parse_mode="HTML", reply_markup=markup)

# ================== الإذاعة (شريط تقدم + إلغاء + حذف من عند الجميع) ==================
BROADCAST_MODE = {"on": False}
BC = {"running": False, "cancel": False}
ALBUMS = {}            # media_group_id -> {"ids": [...], "fwd": bool, "chat": id}
ADMIN_PENDING = {"mode": None}   # grant / revoke
_BG_TASKS = set()

def _bg(coro):
    t = asyncio.create_task(coro)
    _BG_TASKS.add(t)
    t.add_done_callback(_BG_TASKS.discard)
    return t

def _bar(done, total, width=12):
    p = (done / total) if total else 1
    n = int(p * width)
    return "▰" * n + "▱" * (width - n) + f"  {int(p * 100)}%"

def _bc_cancel_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⛔ إلغاء الإذاعة", callback_data="bc_stop", style="danger")]])

def _bc_delete_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🗑 حذف الإذاعة من عند الجميع", callback_data="bc_del")]])

def _make_sender(bot, src_chat, ids, forwarded):
    async def sender(uid):
        if len(ids) == 1:
            if forwarded:
                m = await bot.forward_message(chat_id=uid, from_chat_id=src_chat, message_id=ids[0])
            else:
                m = await bot.copy_message(chat_id=uid, from_chat_id=src_chat, message_id=ids[0])
            return [m.message_id]
        if forwarded:
            res = await bot.forward_messages(chat_id=uid, from_chat_id=src_chat, message_ids=ids)
        else:
            res = await bot.copy_messages(chat_id=uid, from_chat_id=src_chat, message_ids=ids)
        return [x.message_id for x in res]
    return sender

def _make_text_sender(bot, text):
    async def sender(uid):
        m = await bot.send_message(chat_id=uid, text=text)
        return [m.message_id]
    return sender

async def _bc_send_one(sender, uid):
    from telegram.error import RetryAfter, Forbidden, BadRequest, TimedOut, NetworkError
    for _ in range(4):
        try:
            return "ok", await sender(int(uid))
        except RetryAfter as e:
            # تيليجرام طلب تبطئة - ننتظر ونعيد نفس المستخدم (ما نحسبه فاشل)
            await asyncio.sleep(float(getattr(e, "retry_after", 5)) + 1)
        except (TimedOut, NetworkError):
            await asyncio.sleep(2)
        except Forbidden:
            return "blocked", None
        except BadRequest as e:
            low = str(e).lower()
            if "chat not found" in low or "deactivated" in low:
                return "blocked", None
            return "other", str(e)[:60]
        except Exception as e:
            return "other", str(e)[:60]
    return "other", "فشل بعد 4 محاولات"

async def _run_broadcast(bot, sender):
    if BC["running"]:
        await bot.send_message(chat_id=ADMIN_ID, text="⚠️ فيه عملية إذاعة/حذف جارية حالياً، انتظر تخلص.")
        return
    BC["running"] = True
    BC["cancel"] = False
    try:
        users = list(stats["users"].keys())
        total = len(users)
        rec = {"time": datetime.now().isoformat(), "msgs": {}}
        stats["last_broadcast"] = rec
        status = await bot.send_message(
            chat_id=ADMIN_ID, text=f"📢 <b>جاري الإذاعة</b>\n\n{_bar(0, total)}\n0 / {total}",
            parse_mode="HTML", reply_markup=_bc_cancel_markup())
        ok = blocked = other = done = 0
        errs = {}
        last_edit = time.time()
        for uid in users:
            if BC["cancel"]:
                break
            r, info = await _bc_send_one(sender, uid)
            if r == "ok":
                ok += 1
                rec["msgs"][uid] = info or []
            elif r == "blocked":
                blocked += 1
            else:
                other += 1
                errs[info] = errs.get(info, 0) + 1
            done += 1
            if time.time() - last_edit >= 3:
                last_edit = time.time()
                try:
                    await status.edit_text(
                        f"📢 <b>جاري الإذاعة</b>\n\n{_bar(done, total)}\n{done} / {total}\n\n"
                        f"✅ وصلت: {ok}   🚫 حاظرين: {blocked}   ⚠️ أخطاء: {other}",
                        parse_mode="HTML", reply_markup=_bc_cancel_markup())
                except Exception:
                    pass
            await asyncio.sleep(0.06)
        cancelled = BC["cancel"]
        save_stats()
        detail = "".join(f"\n  • {k}: {v}" for k, v in list(errs.items())[:5])
        title = "⛔ <b>أُلغيت الإذاعة</b>" if cancelled else "✅ <b>تمت الإذاعة</b>"
        try:
            await status.edit_text(
                f"{title}\n\n{_bar(done, total)}\n{done} / {total}\n\n"
                f"✅ وصلت فعلاً: {ok}\n🚫 حاظرين البوت: {blocked}\n⚠️ أخطاء أخرى: {other}{detail}",
                parse_mode="HTML", reply_markup=_bc_delete_markup() if ok else None)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Broadcast crashed: {e}")
    finally:
        BC["running"] = False

async def _run_bc_delete(bot):
    rec = stats.get("last_broadcast") or {}
    msgs = rec.get("msgs") or {}
    if not msgs:
        await bot.send_message(chat_id=ADMIN_ID, text="ℹ️ ما فيه إذاعة محفوظة لحذفها.")
        return
    if BC["running"]:
        await bot.send_message(chat_id=ADMIN_ID, text="⚠️ فيه عملية إذاعة/حذف جارية حالياً، انتظر تخلص.")
        return
    from telegram.error import RetryAfter
    BC["running"] = True
    try:
        total = sum(len(v) for v in msgs.values())
        status = await bot.send_message(chat_id=ADMIN_ID, text=f"🗑 <b>جاري حذف الإذاعة</b>\n\n{_bar(0, total)}", parse_mode="HTML")
        ok = fail = done = 0
        last_edit = time.time()
        for uid, ids in list(msgs.items()):
            for mid in ids:
                for _ in range(2):
                    try:
                        await bot.delete_message(chat_id=int(uid), message_id=mid)
                        ok += 1
                        break
                    except RetryAfter as e:
                        await asyncio.sleep(float(getattr(e, "retry_after", 5)) + 1)
                    except Exception:
                        fail += 1
                        break
                done += 1
                await asyncio.sleep(0.05)
            if time.time() - last_edit >= 3:
                last_edit = time.time()
                try:
                    await status.edit_text(f"🗑 <b>جاري حذف الإذاعة</b>\n\n{_bar(done, total)}\n{done} / {total}", parse_mode="HTML")
                except Exception:
                    pass
        rec["msgs"] = {}
        rec["deleted"] = True
        save_stats()
        try:
            await status.edit_text(
                f"✅ <b>تم حذف الإذاعة</b>\n\n🗑 حُذفت: {ok}\n⚠️ تعذر حذفها: {fail}\n"
                "<i>(تيليجرام يسمح بحذف رسائل البوت خلال 48 ساعة من إرسالها)</i>", parse_mode="HTML")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Broadcast delete crashed: {e}")
    finally:
        BC["running"] = False

async def _album_broadcast(bot, gid):
    await asyncio.sleep(2)   # نجمع باقي صور الألبوم
    g = ALBUMS.pop(gid, None)
    if not g:
        return
    ids = sorted(g["ids"])
    await _run_broadcast(bot, _make_sender(bot, g["chat"], ids, g["fwd"]))

async def broadcast_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يلتقط رسائل الأدمن: إدخال لوحة التحكم (منح/إلغاء اشتراك) أو رسالة الإذاعة (تُرسل كما هي تماماً)."""
    user = update.effective_user
    m = update.effective_message
    if not user or user.id != ADMIN_ID or not m or update.effective_chat.type != "private":
        return

    # إدخال نصي مطلوب من لوحة الأدمن
    if ADMIN_PENDING["mode"] and m.text and not m.text.startswith("/"):
        mode = ADMIN_PENDING["mode"]
        ADMIN_PENDING["mode"] = None
        nums = re.findall(r"\d+", m.text.translate(_AR_DIGITS))
        if mode == "grant":
            if len(nums) < 2:
                await m.reply_text("⚠️ الصيغة: <code>ID عدد_الأيام</code> مثال: <code>123456789 30</code>", parse_mode="HTML")
            else:
                tid, days = nums[0], int(nums[1])
                base = premium_until(tid) or datetime.now()
                exp = base + timedelta(days=days)
                stats.setdefault("premium", {})[tid] = exp.isoformat()
                save_stats()
                await m.reply_text(f"✅ تم منح Pro للمستخدم {tid} لمدة {days} يوم (حتى {exp.strftime('%Y-%m-%d')}).")
                try:
                    await context.bot.send_message(chat_id=int(tid), text=f"🎁 تم منحك اشتراك <b>Pro</b> لمدة {days} يوم! استمتع 👑", parse_mode="HTML")
                except Exception:
                    pass
        elif mode == "revoke":
            if not nums:
                await m.reply_text("⚠️ أرسل ID المستخدم فقط.")
            elif stats.get("premium", {}).pop(nums[0], None):
                save_stats()
                await m.reply_text(f"✅ تم إلغاء اشتراك المستخدم {nums[0]}.")
            else:
                await m.reply_text("ℹ️ هذا المستخدم ما عنده اشتراك.")
        raise ApplicationHandlerStop

    # بقية صور ألبوم قيد الجمع
    if m.media_group_id and m.media_group_id in ALBUMS:
        ALBUMS[m.media_group_id]["ids"].append(m.message_id)
        raise ApplicationHandlerStop

    if not BROADCAST_MODE["on"]:
        return
    BROADCAST_MODE["on"] = False
    fwd = bool(m.forward_origin)
    if m.media_group_id:
        ALBUMS[m.media_group_id] = {"ids": [m.message_id], "fwd": fwd, "chat": m.chat_id}
        _bg(_album_broadcast(context.bot, m.media_group_id))
    else:
        _bg(_run_broadcast(context.bot, _make_sender(context.bot, m.chat_id, [m.message_id], fwd)))
    raise ApplicationHandlerStop

async def broadcast_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    BROADCAST_MODE["on"] = False
    await q.answer("تم إلغاء الإذاعة")
    try:
        await q.message.edit_text("❌ تم إلغاء تفعيل الإذاعة.")
    except Exception:
        pass

async def bc_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    BC["cancel"] = True
    await q.answer("⛔ جاري إيقاف الإذاعة...")

async def bc_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    await q.answer()
    if q.data == "bc_del":
        await q.message.reply_text(
            "⚠️ <b>تأكيد:</b> حذف آخر إذاعة من عند جميع المستخدمين؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ نعم، احذف", callback_data="bc_delyes", style="danger"),
                InlineKeyboardButton("↩️ لا", callback_data="bc_delno")]]))
    elif q.data == "bc_delyes":
        try: await q.message.delete()
        except Exception: pass
        _bg(_run_bc_delete(context.bot))
    else:
        try: await q.message.delete()
        except Exception: pass

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    msg = update.effective_message
    text = (msg.text or "").replace("/broadcast", "", 1).strip()
    if not text:
        BROADCAST_MODE["on"] = True
        await msg.reply_text(
            "📢 تم تفعيل الإذاعة.\nأرسل الآن أي رسالة (نص/صورة/ألبوم/ملف/محولة من قناة...) وتنرسل للجميع كما هي تماماً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء الإذاعة", callback_data="bc_cancel")]]))
        return
    if not stats["users"]:
        await msg.reply_text("❌ لا يوجد مستخدمين مسجلين في قاعدة البيانات.")
        return
    _bg(_run_broadcast(context.bot, _make_text_sender(context.bot, text)))

# ================== لوحة تحكم الأدمن ==================
def _admin_home_text():
    n_pro = sum(1 for u in stats.get("premium", {}) if premium_until(u))
    return (
        "⚙️ <b>لوحة تحكم الأدمن</b>\n━━━━━━━\n"
        f"👥 المستخدمون: <b>{len(stats.get('users', {}))}</b>   👑 Pro: <b>{n_pro}</b>\n"
        f"🔧 الصيانة: <b>{'🔴 مفعّلة' if get_setting('maint') else '🟢 متوقفة'}</b>\n"
        f"🚧 حد الطابور: <b>{get_setting('queue')}</b>\n\n"
        "اختر ما تبي تتحكم فيه 👇"
    )

def _admin_home_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="adm_stats"), InlineKeyboardButton("📢 إذاعة", callback_data="adm_bc")],
        [InlineKeyboardButton("🛑 كل الأخطاء", callback_data="adm_err"), InlineKeyboardButton("⚠️ أخطاء المنصات", callback_data="adm_err2")],
        [InlineKeyboardButton("🍪 فحص الكوكيز", callback_data="adm_cookies"), InlineKeyboardButton("🗑 حذف آخر إذاعة", callback_data="adm_bcdel")],
        [InlineKeyboardButton("👑 إدارة Pro", callback_data="adm_pro"), InlineKeyboardButton("⚙️ الإعدادات", callback_data="adm_set")],
    ])

def _adm_stepper(label, key, tag):
    return [InlineKeyboardButton("➖", callback_data=f"adm_n_{tag}_d"),
            InlineKeyboardButton(f"{label}: {get_setting(key)}", callback_data="adm_noop"),
            InlineKeyboardButton("➕", callback_data=f"adm_n_{tag}_u")]

def _settings_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎨 الأزرار الرئيسية: {BTN_STYLE_LABELS[get_setting('btn_main')]}", callback_data="adm_s_btn_main")],
        [InlineKeyboardButton(f"🎨 الأزرار الثانوية: {BTN_STYLE_LABELS[get_setting('btn_sec')]}", callback_data="adm_s_btn_sec")],
        _adm_stepper("🚧 الطابور", "queue", "queue"),
        _adm_stepper("✂️ أقصى قص (ث)", "trim_max", "trim"),
        _adm_stepper("🎬 أقصى فلتر (ث)", "filter_max", "filt"),
        _adm_stepper("🎁 التجارب المجانية", "free_trials", "trial"),
        [InlineKeyboardButton(f"🔧 وضع الصيانة: {'🔴 مفعّل' if get_setting('maint') else '🟢 متوقف'}", callback_data="adm_s_maint")],
        [InlineKeyboardButton("💰 أسعار الباقات", callback_data="adm_price")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="adm_home")],
    ])

def _price_markup():
    rows = []
    for k in ("daily", "weekly", "monthly"):
        rows.append([InlineKeyboardButton("➖", callback_data=f"adm_pr_{k}_d"),
                     InlineKeyboardButton(f"{PLANS[k]['label']}: {PLANS[k]['stars']} ⭐", callback_data="adm_noop"),
                     InlineKeyboardButton("➕", callback_data=f"adm_pr_{k}_u")])
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="adm_set")])
    return InlineKeyboardMarkup(rows)

def _pro_admin_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ منح اشتراك", callback_data="adm_grant"), InlineKeyboardButton("➖ إلغاء اشتراك", callback_data="adm_revoke")],
        [InlineKeyboardButton("📋 المشتركون الحاليون", callback_data="adm_prolist")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="adm_home")],
    ])

async def _adm_edit(q, text, markup):
    try:
        await q.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        pass

async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    await update.effective_message.reply_text(_admin_home_text(), parse_mode="HTML", reply_markup=_admin_home_markup())

SET_TEXT = "⚙️ <b>الإعدادات</b>\nكل تغيير يُطبَّق فوراً ويُحفظ تلقائياً."

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    d = q.data
    parts = d.split("_")
    await q.answer()

    if d == "adm_noop":
        return
    if d == "adm_home":
        await _adm_edit(q, _admin_home_text(), _admin_home_markup())
    elif d == "adm_stats":
        await show_stats_command(update, context)
    elif d == "adm_err":
        await show_all_errors_command(update, context)
    elif d == "adm_err2":
        await show_errors_command(update, context)
    elif d == "adm_cookies":
        await cookies_check_command(update, context)
    elif d == "adm_bc":
        BROADCAST_MODE["on"] = True
        await q.message.reply_text(
            "📢 تم تفعيل الإذاعة.\nأرسل الآن أي رسالة (نص/صورة/ألبوم/ملف/محولة من قناة...) وتنرسل للجميع كما هي تماماً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء الإذاعة", callback_data="bc_cancel")]]))
    elif d == "adm_bcdel":
        await q.message.reply_text(
            "⚠️ <b>تأكيد:</b> حذف آخر إذاعة من عند جميع المستخدمين؟", parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ نعم، احذف", callback_data="bc_delyes", style="danger"),
                InlineKeyboardButton("↩️ لا", callback_data="bc_delno")]]))
    elif d == "adm_set":
        await _adm_edit(q, SET_TEXT, _settings_markup())
    elif d in ("adm_s_btn_main", "adm_s_btn_sec"):
        key = "btn_main" if d.endswith("main") else "btn_sec"
        cur = get_setting(key)
        nxt = BTN_STYLES[(BTN_STYLES.index(cur) + 1) % len(BTN_STYLES)] if cur in BTN_STYLES else BTN_STYLES[0]
        set_setting(key, nxt)
        await _adm_edit(q, SET_TEXT, _settings_markup())
    elif d == "adm_s_maint":
        set_setting("maint", not get_setting("maint"))
        await _adm_edit(q, SET_TEXT, _settings_markup())
    elif d.startswith("adm_n_"):
        tag, direction = parts[2], parts[3]
        cfg = {"queue": ("queue", 1, 1, 30), "trim": ("trim_max", 10, 10, 300), "filt": ("filter_max", 5, 5, 120), "trial": ("free_trials", 1, 0, 20)}.get(tag)
        if cfg:
            key, step, lo, hi = cfg
            val = int(get_setting(key)) + (step if direction == "u" else -step)
            set_setting(key, max(lo, min(hi, val)))
        await _adm_edit(q, SET_TEXT, _settings_markup())
    elif d == "adm_price":
        await _adm_edit(q, "💰 <b>أسعار الباقات</b> (بالنجوم)\nتتحدث البطاقة وفواتير الدفع فوراً.", _price_markup())
    elif d.startswith("adm_pr_"):
        plan, direction = parts[2], parts[3]
        if plan in PLANS:
            val = int(get_setting(f"price_{plan}")) + (1 if direction == "u" else -1)
            set_setting(f"price_{plan}", max(1, min(1000, val)))
        await _adm_edit(q, "💰 <b>أسعار الباقات</b> (بالنجوم)\nتتحدث البطاقة وفواتير الدفع فوراً.", _price_markup())
    elif d == "adm_pro":
        await _adm_edit(q, "👑 <b>إدارة Pro</b>", _pro_admin_markup())
    elif d == "adm_grant":
        ADMIN_PENDING["mode"] = "grant"
        await q.message.reply_text("➕ أرسل: <code>ID عدد_الأيام</code>\nمثال: <code>123456789 30</code>", parse_mode="HTML")
    elif d == "adm_revoke":
        ADMIN_PENDING["mode"] = "revoke"
        await q.message.reply_text("➖ أرسل ID المستخدم لإلغاء اشتراكه.")
    elif d == "adm_prolist":
        rows = []
        for uid in stats.get("premium", {}):
            u = premium_until(uid)
            if u:
                rows.append(f"• <code>{uid}</code> — حتى {u.strftime('%Y-%m-%d')}")
        await q.message.reply_text("📋 <b>المشتركون الحاليون</b>\n\n" + ("\n".join(rows[:60]) if rows else "لا يوجد مشتركون حالياً."), parse_mode="HTML")

# ================== المعالجة والتحميل ==================
def _blocking_get_thumbnail(url):
    """يجيب رابط الصورة المصغرة بس (بدون تحميل الفيديو) - خفيف جداً."""
    opts = {
        'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE, 'proxy': PROXY_URL,
        'skip_download': True, 'socket_timeout': 15,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get('thumbnail')

def _blocking_get_caption(url):
    """يجيب وصف المنشور فقط (بدون تحميل) - خفيف."""
    opts = {
        'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE, 'proxy': PROXY_URL,
        'skip_download': True, 'socket_timeout': 15,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'extractor_args': {'twitter': {'api': ['syndication', 'graphql', 'legacy']},
                'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}},
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get('entries'):
            info = next((e for e in info['entries'] if e), info)
        return (info.get('description') or info.get('title') or '').strip()

# ===== تشغيل yt-dlp بعملية منفصلة (معزولة) - لتيك توك فقط =====
# لو yt-dlp علّق أو انفجر بالرام، تنقتل العملية المنفصلة وحدها والبوت يظل شغال.
_ISOLATED_WORKER = r"""
import sys, json
from yt_dlp import YoutubeDL
req = json.loads(sys.stdin.read())
with YoutubeDL(req["opts"]) as ydl:
    info = ydl.extract_info(req["url"], download=(req["mode"] == "download"))
    if req["mode"] == "download":
        out = {"file": ydl.prepare_filename(info)}
    else:
        if info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        out = {"thumbnail": info.get("thumbnail"), "description": (info.get("description") or info.get("title") or "").strip()}
print("__RESULT__" + json.dumps(out))
"""
TIKTOK_INFO_SEM = asyncio.Semaphore(1)
ISOLATED_TIMEOUT = 45
ISOLATED_MEM_BYTES = 1500 * 1024 * 1024

def _is_tiktok(url):
    return "tiktok.com" in (url or "").lower()

async def run_isolated(mode, url, opts):
    import resource, signal
    def _limits():
        os.setsid()
        try: resource.setrlimit(resource.RLIMIT_AS, (ISOLATED_MEM_BYTES, ISOLATED_MEM_BYTES))
        except Exception: pass
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", _ISOLATED_WORKER,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        preexec_fn=_limits)
    try:
        payload = json.dumps({"mode": mode, "url": url, "opts": opts}).encode()
        out, err = await asyncio.wait_for(proc.communicate(payload), timeout=ISOLATED_TIMEOUT)
    except asyncio.TimeoutError:
        try: os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try: proc.kill()
            except Exception: pass
        try: await proc.wait()
        except Exception: pass
        raise asyncio.TimeoutError()
    finally:
        if proc.returncode is None:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except Exception: pass
    text = (out or b"").decode(errors="ignore")
    for line in reversed(text.splitlines()):
        if line.startswith("__RESULT__"):
            return json.loads(line[len("__RESULT__"):])
    raise Exception("isolated worker failed: " + (err or b"").decode(errors="ignore")[-400:])

def _tt_info_opts():
    return {
        'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE, 'proxy': PROXY_URL,
        'skip_download': True, 'socket_timeout': 15,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'extractor_args': {'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}},
    }

def _blocking_fetch_bytes(url):
    opener = _get_urllib_opener()
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with opener.open(req, timeout=15) as resp:
        return resp.read()

def _blocking_download(url, opts):
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def _get_urllib_opener():
    """يبني opener يستخدم البروكسي لو معرّف (PROXY_URL)، وإلا opener عادي."""
    if PROXY_URL:
        proxy_handler = urllib.request.ProxyHandler({'http': PROXY_URL, 'https': PROXY_URL})
        return urllib.request.build_opener(proxy_handler)
    return urllib.request.build_opener()

# ================== استقبال الرسائل والبدء ==================
def _start_markup():
    return InlineKeyboardMarkup([
        [_btn("📱 إنشاء QR", "mode_qr", "sec"), _btn("🔤 استخراج النص من الصور", "mode_ocr", "sec")],
        [_btn("📥 تحميل شامل", "mode_dl", "main")],
    ])

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

    # رابط دخول مباشر (Deep Link): https://t.me/ZenDown_Bot?start=mystats
    if context.args and context.args[0] == "mystats":
        await show_my_stats_command(update, context)
        return

    import html as _html
    await update.message.reply_text(
        f"أهلاً بك <b>{_html.escape(user.first_name or 'صديقنا')}</b> في @ZenDown_Bot 🚀\n\n"
        "📥 أرسل رابط أي مقطع وسأحمّله لك مباشرة.\n"
        "أو اختر خدمة إضافية من الأزرار 👇",
        parse_mode="HTML", reply_markup=_start_markup())

async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أزرار رسالة الترحيب: QR / استخراج النص / التحميل الشامل."""
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()
    track_user_activity(uid)
    if not await check_user_subscription(context.bot, uid):
        await q.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً ثم أرسل /start")
        return
    QR_MODE_USERS.discard(uid)
    OCR_MODE_USERS.discard(uid)
    TRIM_PENDING.pop(uid, None)
    if q.data == "mode_qr":
        QR_MODE_USERS.add(uid)
        await q.message.reply_text(
            "تم تفعيل خدمة QR 📱\nأرسل أي رابط أو نص لتحويله إلى صورة QR.",
            reply_markup=_qr_cancel_markup())
    elif q.data == "mode_ocr":
        OCR_MODE_USERS.add(uid)
        await q.message.reply_text(
            "🔤 <b>تم تفعيل استخراج النص من الصور</b>\n\n"
            "أرسل أي صورة وسأستخرج النص منها.\n"
            "<i>تقدر كذلك تستمر بإرسال الروابط للتحميل كالمعتاد.</i>",
            parse_mode="HTML", reply_markup=_ocr_cancel_markup())
    else:
        await q.message.reply_text(
            "📥 <b>التحميل الشامل</b>\n\nأرسل رابط مقطع من أي منصة وسيتم التحميل ⬇️",
            parse_mode="HTML")

def _ocr_cancel_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("إلغاء تفعيل استخراج النص ❌", callback_data="ocr_cancel", style="danger")]])

async def ocr_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("تم إلغاء تفعيل استخراج النص")
    OCR_MODE_USERS.discard(q.from_user.id)
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

def _blocking_ocr(img_bytes):
    """يرسل الصورة لخدمة OCR.space (خارجية، خفيفة على سيرفرنا). المفتاح من متغير البيئة OCR_SPACE_API_KEY."""
    import base64
    import urllib.parse
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(img_bytes)).convert("RGB")
    im.thumbnail((1800, 1800))
    quality = 85
    while True:
        buf = BytesIO()
        im.save(buf, "JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= 900 * 1024 or quality <= 40:
            break
        quality -= 15
    b64 = "data:image/jpeg;base64," + base64.b64encode(data).decode()
    key = os.environ.get("OCR_SPACE_API_KEY", "helloworld")
    last_err = None
    for engine, lang in (("2", "auto"), ("1", "ara"), ("1", "eng")):
        try:
            body = urllib.parse.urlencode({
                "apikey": key, "base64Image": b64, "language": lang, "OCREngine": engine,
                "scale": "true", "detectOrientation": "true", "isOverlayRequired": "false",
            }).encode()
            req = urllib.request.Request("https://api.ocr.space/parse/image", data=body)
            with urllib.request.urlopen(req, timeout=30) as resp:
                res = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if res.get("IsErroredOnProcessing"):
                last_err = str(res.get("ErrorMessage"))[:200]
                continue
            parsed = res.get("ParsedResults") or []
            text = (parsed[0].get("ParsedText") or "").strip() if parsed else ""
            if text:
                return text
        except Exception as e:
            last_err = str(e)[:200]
    if last_err:
        raise Exception(last_err)
    return ""

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    m = update.effective_message
    if not user or not m:
        return
    track_user_activity(user.id)
    if not await check_user_subscription(context.bot, user.id):
        await m.reply_text("🚧 يرجى الاشتراك في القناة أولاً.")
        return
    if get_setting("maint") and user.id != ADMIN_ID:
        await m.reply_text("🔧 البوت تحت الصيانة حالياً، نعود قريباً بإذن الله.")
        return
    if user.id not in OCR_MODE_USERS:
        await m.reply_text(
            "📷 استلمت صورة! لاستخراج النص منها فعّل الميزة أولاً 👇",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔤 تفعيل استخراج النص", callback_data="mode_ocr")]]))
        return
    wait = await m.reply_text("🔍 جاري تحليل الصورة...")
    try:
        f = await (m.photo[-1] if m.photo else m.document).get_file()
        if f.file_size and f.file_size > 10 * 1024 * 1024:
            await wait.edit_text("❌ الصورة كبيرة جداً (الحد 10 ميجا).")
            return
        data = bytes(await f.download_as_bytearray())
        text = await asyncio.wait_for(run_blocking(_blocking_ocr, data), timeout=110)
        if not text:
            stats["ocr_fail"] = stats.get("ocr_fail", 0) + 1
            save_stats()
            await wait.edit_text("ℹ️ ما لقيت نصاً واضحاً في الصورة. جرّب صورة أوضح.", reply_markup=_ocr_cancel_markup())
            return
        track_feature("ocr", user.id)
        import html as _html
        await wait.edit_text(
            f"✅ <b>النص المستخرج</b> <i>(اضغط على النص للنسخ)</i>\n\n<code>{_html.escape(text[:3700])}</code>",
            parse_mode="HTML", reply_markup=_ocr_cancel_markup())
    except Exception as e:
        stats["ocr_fail"] = stats.get("ocr_fail", 0) + 1
        logger.error(f"OCR failed: {e}")
        try:
            await wait.edit_text("❌ تعذر تحليل الصورة حالياً، حاول لاحقاً.", reply_markup=_ocr_cancel_markup())
        except Exception:
            pass

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if await check_user_subscription(context.bot, q.from_user.id):
        try:
            await q.message.delete()
        except Exception:
            pass  # الرسالة ممكن تكون انحذفت قبل (ضغط مزدوج) - ما يهم، نكمل عادي
        await q.message.reply_text("✅ تم التحقق! أرسل رابطك أو كلمة البحث الآن.")
    else:
        await q.answer("❌ لم تشترك بالقناة بعد!", show_alert=True)

# وضع QR: تخزين مؤقت بالذاكرة (مو بقاعدة بيانات) - مجرد "وضع" مؤقت للجلسة، يرجع تلقائياً
# معطل لو انعاد تشغيل البوت، وهذا مقبول تماماً لأنه مو بيانات نحتاج نحافظ عليها.
QR_MODE_USERS = set()
OCR_MODE_USERS = set()

def _qr_cancel_markup(cancel_text="إلغاء ❌", cancel_data="qr_cancel"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(cancel_text, callback_data=cancel_data, style="danger")]])

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        await update.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً.")
        return

    text = update.message.text.strip()

    if get_setting("maint") and user.id != ADMIN_ID:
        await update.message.reply_text("🔧 البوت تحت الصيانة حالياً، نعود قريباً بإذن الله.")
        return

    if text.strip().lower() == "qr":
        OCR_MODE_USERS.discard(user.id)
        QR_MODE_USERS.add(user.id)
        await update.message.reply_text(
            "تم تفعيل خدمة QR 📱\nأرسل أي رابط لتحويله إلى صورة QR.",
            reply_markup=_qr_cancel_markup()
        )
        return

    # وضع QR مفعّل لهالمستخدم - أي رسالة يرسلها (رابط أو نص) تتحول QR، بدل التدفق العادي
    if user.id in QR_MODE_USERS:
        await generate_qr(update, text)
        return

    # وضع القص: إدخال سهل خطوة بخطوة (بداية ثم نهاية) أو الاثنين بنفس الرسالة
    if user.id in TRIM_PENDING and not text.startswith("http"):
        pend = TRIM_PENDING[user.id]
        sid = pend["sid"]
        toks = _time_tokens(text)
        if not toks:
            await update.message.reply_text("ما فهمت 😅 أرسل رقم بسيط مثل <code>10</code> أو <code>1:05</code>", parse_mode="HTML")
            return
        if pend["start"] is None and len(toks) == 1:
            pend["start"] = toks[0]
            await update.message.reply_text(f"✅ البداية: <b>{_fmt(toks[0])}</b>\nالحين أرسل <b>وقت النهاية</b> (مثال: <code>{toks[0] + 30}</code>)", parse_mode="HTML")
            return
        s_t, e_t = (toks[0], toks[1]) if (pend["start"] is None) else (pend["start"], toks[0])
        if e_t <= s_t:
            pend["start"] = None if len(toks) >= 2 else pend["start"]
            await update.message.reply_text(f"⚠️ النهاية لازم تكون بعد البداية ({_fmt(s_t)}). أرسل وقت النهاية من جديد.")
            return
        if e_t - s_t > TRIM_MAX_SECONDS:
            await update.message.reply_text(f"⚠️ أقصى مدة للقص {TRIM_MAX_SECONDS} ثانية، وأنت اخترت {e_t - s_t}. أرسل وقت النهاية من جديد.")
            return
        _edit_get(user.id, sid)["c"] = (s_t, e_t)
        TRIM_PENDING.pop(user.id, None)
        await _send_edit_menu(update.message, user.id, sid)
        return
    TRIM_PENDING.pop(user.id, None)

    if text.startswith("http"):
        platform = track_platform_request(text)
        # فحص سريع (بدون أي تحليل أو اتصال بالإنترنت) قبل أي معالجة ثقيلة، عشان ما نضيع
        # وقت ولا موارد على روابط منصات مو مدعومة بهذا البوت
        if platform == "يوتيوب":
            await update.message.reply_text("للتحميل من YouTube إستخدم هذا البوت @Gozilla_bot")
        else:
            await process_link_info(update, context, text)
    else:
        await update.message.reply_text("ميزة البحث قيد التطوير...")

async def qr_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("تم إلغاء تفعيل QR")
    QR_MODE_USERS.discard(q.from_user.id)
    try:
        await q.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

def _blocking_make_qr(content: str):
    import qrcode
    from io import BytesIO
    img = qrcode.make(content)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

async def generate_qr(update: Update, content: str):
    if not content:
        await update.message.reply_text("أرسل رابط أو نص لتحويله لصورة QR.", reply_markup=_qr_cancel_markup())
        return
    try:
        img_bytes = await asyncio.wait_for(run_blocking(_blocking_make_qr, content), timeout=10)
        await update.message.reply_photo(
            photo=img_bytes,
            caption="✅ تم بنجاح — أرسل رابط ثاني لو تبي، أو اضغط تحت لإيقاف الميزة.",
            reply_markup=_qr_cancel_markup("إلغاء تفعيل Qr", "qr_cancel")
        )
        track_feature("qr", update.effective_user.id)
    except Exception as e:
        logger.error(f"QR generation failed: {e}")
        await update.message.reply_text("❌ تعذر توليد الرمز، حاول مرة ثانية.", reply_markup=_qr_cancel_markup())

# ================== جلب معلومات الرابط ==================
async def process_link_info(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    # بدون أي تحليل أو استخراج معلومات - نعرض الأزرار فوراً، عشان البوت يكون أسرع وأخف
    # ما يمكن (بدون عنوان الفيديو ولا صورة مصغرة - الثمن مقابل السرعة).
    sid = str(uuid.uuid4())[:8]
    URL_CACHE[sid] = url

    caption = "🎬 <b>رابط جاهز للتحميل</b>"
    markup = InlineKeyboardMarkup([
        [_btn("🎥 فيديو MP4", f"down_vid_{sid}", "main")],
        [_btn("🎵 صوت MP3", f"down_aud_{sid}", "sec"),
         _btn("🖼 صورة", f"down_img_{sid}", "sec")],
        [_btn("📝 نسخ الوصف", f"down_cap_{sid}", "sec")],
        [_btn("تعديل المقطع 🎬", f"ed_menu_{sid}", "main")]
    ])

    await update.message.reply_text(caption, parse_mode="HTML", reply_markup=markup)

# ================== التحميل الذكي المحسّن والجدار الأمني ==================
# ================== زر التبرع بنجمة (Telegram Stars) ==================
# ================== الإعدادات القابلة للتحكم من لوحة الأدمن ==================
PLANS = {
    "daily":   {"stars": 5,  "days": 1,  "label": "يومي"},
    "weekly":  {"stars": 15, "days": 7,  "label": "أسبوعي"},
    "monthly": {"stars": 30, "days": 30, "label": "شهري"},
}
DEFAULT_SETTINGS = {
    "btn_main": "primary", "btn_sec": "success",
    "queue": 6, "trim_max": 60, "filter_max": 30, "free_trials": 2,
    "maint": False,
    "price_daily": 5, "price_weekly": 15, "price_monthly": 30,
}
BTN_STYLES = ["primary", "success", "danger", "default"]
BTN_STYLE_LABELS = {"primary": "🔵 أزرق", "success": "🟢 أخضر", "danger": "🔴 أحمر", "default": "⚪ افتراضي"}
TRIM_MAX_SECONDS = 60
FILTER_MAX_SECONDS = 30

def get_setting(key):
    return stats.get("settings", {}).get(key, DEFAULT_SETTINGS[key])

def apply_settings():
    """يطبّق الإعدادات المحفوظة على المتغيرات العامة (يُستدعى عند الإقلاع وعند كل تغيير)."""
    global MAX_QUEUE_SIZE, TRIM_MAX_SECONDS, FILTER_MAX_SECONDS
    try:
        MAX_QUEUE_SIZE = int(get_setting("queue"))
        TRIM_MAX_SECONDS = int(get_setting("trim_max"))
        FILTER_MAX_SECONDS = int(get_setting("filter_max"))
        for k in PLANS:
            PLANS[k]["stars"] = int(get_setting(f"price_{k}"))
    except Exception as e:
        logger.error(f"apply_settings failed: {e}")

def set_setting(key, value):
    stats.setdefault("settings", {})[key] = value
    apply_settings()
    save_stats()

def _btn(text, data, kind=None):
    """زر بلون حسب إعدادات الأدمن: kind=main (رئيسي) أو sec (ثانوي)."""
    if kind in ("main", "sec"):
        st = get_setting("btn_main" if kind == "main" else "btn_sec")
        if st and st != "default":
            return InlineKeyboardButton(text, callback_data=data, style=st)
    return InlineKeyboardButton(text, callback_data=data)

# ================== اشتراك Pro (باقات بالنجوم) ==================
FILTERS = {
    "bw":      ("⚫ أبيض وأسود", "hue=s=0"),
    "sepia":   ("🟤 سيبيا", "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131:0"),
    "warm":    ("🔥 دافئ", "colorbalance=rs=.18:gs=.04:bs=-.18,eq=saturation=1.15"),
    "cool":    ("❄️ بارد", "colorbalance=rs=-.18:bs=.2,eq=saturation=1.05"),
    "vivid":   ("🌈 حيوي", "eq=brightness=0.05:contrast=1.12:saturation=1.5"),
    "drama":   ("🎭 درامي", "eq=contrast=1.35:saturation=0.85:brightness=-0.03,vignette=PI/5"),
    "vintage": ("📼 قديم", "curves=preset=vintage"),
    "mirror":  ("🪞 انعكاس", "hflip"),
}
EDIT_STATE = {}     # f"{user_id}:{sid}" -> {"f": مفتاح الفلتر أو None, "c": (بداية, نهاية) أو None}
TRIM_PENDING = {}   # user_id -> {"sid": ..., "start": None أو ثواني}
THUMB_CACHE = BoundedCache(max_size=60)   # sid -> bytes (صورة المعاينة)

def track_feature(name, user_id, n=1):
    f = stats.setdefault("feat", {}).setdefault(name, {})
    uid = str(user_id)
    f[uid] = f.get(uid, 0) + n

def feat_counts(name):
    f = stats.get("feat", {}).get(name, {})
    return len(f), sum(f.values())

def free_trials_left(user_id) -> int:
    used = stats.get("user_profiles", {}).get(str(user_id), {}).get("free_edits", 0)
    return max(0, int(get_setting("free_trials")) - used)

def use_free_trial(user_id):
    p = stats.setdefault("user_profiles", {}).setdefault(str(user_id), {"joined": datetime.now().isoformat(), "total_downloads": 0, "platforms": {}})
    p["free_edits"] = p.get("free_edits", 0) + 1
    save_stats()

def _trial_line(user_id) -> str:
    if is_premium(user_id):
        return "👑 <b>Pro</b> — التطبيق والإرسال متاحان لك"
    total = int(get_setting("free_trials"))
    left = free_trials_left(user_id)
    if left > 0:
        return f"🎁 لديك <b>{left}</b> من {total} تجارب مجانية للتطبيق والإرسال"
    return "🔒 انتهت تجاربك المجانية — التطبيق والإرسال لمشتركي Pro"

def is_premium(user_id) -> bool:
    try:
        if int(user_id) == ADMIN_ID:   # الأدمن يتمتع بكل مزايا Pro مجاناً
            return True
        exp = stats.get("premium", {}).get(str(user_id))
        return bool(exp) and datetime.fromisoformat(exp) > datetime.now()
    except Exception:
        return False

def premium_until(user_id):
    try:
        exp = stats.get("premium", {}).get(str(user_id))
        if exp and datetime.fromisoformat(exp) > datetime.now():
            return datetime.fromisoformat(exp)
    except Exception:
        pass
    return None

def _plans_text(user_id) -> str:
    until = premium_until(user_id)
    status = f"✅ اشتراكك فعّال حتى <b>{until.strftime('%Y-%m-%d %H:%M')}</b>\n\n" if until else ""
    return (
        "👑 <b>ZenDown Pro</b>\n"
        "━━━━━━━\n\n"
        f"{status}"
        "البوت يبقى <b>مجاني بالكامل</b> كما هو، وPro إضافة اختيارية لمن يبي مزايا أكثر:\n\n"
        "🚀 <b>تخطي الطابور</b> — ما يُرفض طلبك وقت الازدحام\n"
        f"🎬 <b>تعديل المقطع</b> — فلاتر + قص في ملف واحد (قص حتى {TRIM_MAX_SECONDS} ثانية)\n"
        "👑 <b>شارة Pro</b> في إحصائياتك\n\n"
        "───────────────\n"
        "⭐ <b>الباقات</b>\n"
        "───────────────\n"
        f"▫️ يومي — {PLANS['daily']['stars']} ⭐\n"
        f"▫️ أسبوعي — {PLANS['weekly']['stars']} ⭐\n"
        f"▫️ شهري — {PLANS['monthly']['stars']} ⭐  🔥 الأوفر\n\n"
        "اختر باقتك من الأزرار 👇"
    )

def _plans_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔥 شهري — {PLANS['monthly']['stars']} ⭐", callback_data="buy_monthly", style="primary")],
        [InlineKeyboardButton(f"أسبوعي — {PLANS['weekly']['stars']} ⭐", callback_data="buy_weekly"),
         InlineKeyboardButton(f"يومي — {PLANS['daily']['stars']} ⭐", callback_data="buy_daily")],
    ])

async def pro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    track_user_activity(user.id)
    await update.message.reply_text(_plans_text(user.id), parse_mode="HTML", reply_markup=_plans_markup())

async def pro_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text(_plans_text(q.from_user.id), parse_mode="HTML", reply_markup=_plans_markup())

async def buy_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("buy_", "")
    plan = PLANS.get(key)
    if not plan:
        return
    try:
        await context.bot.send_invoice(
            chat_id=q.message.chat_id,
            title=f"ZenDown Pro — {plan['label']}",
            description=f"اشتراك Pro لمدة {plan['days']} يوم: تخطي الطابور + تعديل المقطع (فلاتر وقص).",
            payload=f"plan_{key}",
            currency="XTR",
            prices=[LabeledPrice(f"Pro {plan['label']}", plan["stars"])],
        )
    except Exception as e:
        logger.error(f"Failed to send plan invoice: {e}")
        await q.message.reply_text("❌ تعذر فتح نافذة الدفع حالياً، حاول لاحقاً.")

async def paysupport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💬 <b>دعم المدفوعات</b>\n\nإذا دفعت ولم يتفعّل اشتراكك، أو عندك أي مشكلة بالدفع، "
        "تواصل معنا عبر قناتنا @ZenoX_Tools مع ذكر وقت الدفع، وراح نساعدك.",
        parse_mode="HTML")

async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    track_user_activity(user.id)
    if not await check_user_subscription(context.bot, user.id):
        await update.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً.")
        return
    if context.args:
        await generate_qr(update, " ".join(context.args))
        return
    OCR_MODE_USERS.discard(user.id)
    QR_MODE_USERS.add(user.id)
    await update.message.reply_text(
        "تم تفعيل خدمة QR 📱\nأرسل أي رابط أو نص لتحويله إلى صورة QR.",
        reply_markup=_qr_cancel_markup())

# ---------- أدوات الوقت (إدخال سهل: 10 أو 1:05 أو بالأرقام العربية) ----------
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

def _parse_time(t: str):
    sec = 0
    for p in t.strip().split(":"):
        sec = sec * 60 + int(p)
    return sec

def _time_tokens(text: str):
    """يستخرج كل الأوقات من النص: '10 40' أو '0:10-0:40' أو 'من 10 الى 40' ..."""
    text = text.translate(_AR_DIGITS)
    out = []
    for tok in re.findall(r"\d+(?::\d+){1,2}|\d+", text):
        try:
            out.append(_parse_time(tok))
        except Exception:
            pass
    return out

def _fmt(sec: int) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"

# ---------- حالة تعديل المقطع ----------
def _edit_get(uid, sid):
    k = f"{uid}:{sid}"
    if k not in EDIT_STATE:
        if len(EDIT_STATE) > 400:
            EDIT_STATE.pop(next(iter(EDIT_STATE)))
        EDIT_STATE[k] = {"f": None, "c": None}
    return EDIT_STATE[k]

def _edit_menu_text(uid, sid):
    st = _edit_get(uid, sid)
    flt = FILTERS[st["f"]][0] if st["f"] else "بدون"
    c = st["c"]
    cut = f"{_fmt(c[0])} ← {_fmt(c[1])} ({c[1] - c[0]} ث)" if c else "بدون"
    note = f"\n<i>مع الفلتر يكون الناتج حتى {FILTER_MAX_SECONDS} ثانية</i>" if st["f"] else ""
    return (
        "🎬 <b>تعديل المقطع</b>\n━━━━━━━\n"
        f"🎨 الفلتر: <b>{flt}</b>\n"
        f"✂️ القص: <b>{cut}</b>{note}\n\n"
        f"{_trial_line(uid)}\n\n"
        "اختر ما تبيه، ثم اضغط <b>تطبيق وإرسال</b> 👇"
    )

def _edit_menu_markup(uid, sid):
    st = _edit_get(uid, sid)
    rows = [
        [_btn("🎨 إضافة فلتر" if not st["f"] else "🎨 تغيير الفلتر", f"ed_fl_{sid}", "main")],
        [_btn("✂️ قص الفيديو" if not st["c"] else "✂️ تغيير القص", f"ed_cut_{sid}", "main")],
    ]
    if st["f"] or st["c"]:
        rows.append([InlineKeyboardButton("✅ تطبيق وإرسال", callback_data=f"ed_go_{sid}", style="success")])
        rows.append([InlineKeyboardButton("🗑 مسح التعديلات", callback_data=f"ed_clr_{sid}")])
    return InlineKeyboardMarkup(rows)

async def _send_edit_menu(message, uid, sid):
    await message.reply_text(_edit_menu_text(uid, sid), parse_mode="HTML", reply_markup=_edit_menu_markup(uid, sid))

def _filters_markup(sid):
    keys = list(FILTERS.keys())
    rows = []
    for i in range(0, len(keys), 2):
        rows.append([InlineKeyboardButton(FILTERS[k][0], callback_data=f"ed_p_{k}_{sid}") for k in keys[i:i + 2]])
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"ed_menu_{sid}")])
    return InlineKeyboardMarkup(rows)

async def _pro_upsell_apply(q):
    """يظهر لغير المشترك بعد انتهاء التجارب المجانية: مختصر + الباقات."""
    total = int(get_setting("free_trials"))
    head = (f"🔒 <b>انتهت تجاربك المجانية</b> ({total} من {total})" if total > 0
            else "👑 <b>استلام الفيديو المعدّل متاح لمشتركي Pro</b>")
    await q.message.reply_text(
        f"{head}\n\n"
        "مع Pro تحصل على:\n"
        "🎬 فلاتر + قص في ملف واحد\n"
        "🚀 تخطي الطابور\n"
        "👑 شارة Pro\n\n"
        "اختر باقتك 👇",
        parse_mode="HTML", reply_markup=_plans_markup())

# ---------- أدوات ffmpeg ----------
async def _ffmpeg_exec(args, timeout):
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try: proc.kill()
        except Exception: pass
        raise
    return proc.returncode == 0

async def _ffmpeg_edit(src, dst, cut, vf):
    """يطبّق القص و/أو الفلتر في خطوة واحدة. القص وحده سريع (بدون إعادة ترميز)،
    ومع الفلتر نعيد الترميز بإعدادات خفيفة (ultrafast، حد أقصى 720p، مدة محدودة)."""
    start = cut[0] if cut else 0
    dur = (cut[1] - cut[0]) if cut else None
    if not vf:
        args = ["-ss", str(start), "-i", src] + (["-t", str(dur)] if dur else []) + \
               ["-c", "copy", "-avoid_negative_ts", "make_zero", dst]
        ok = await _ffmpeg_exec(args, timeout=60)
    else:
        d = min(dur, FILTER_MAX_SECONDS) if dur else FILTER_MAX_SECONDS
        ok = await _ffmpeg_exec([
            "-ss", str(start), "-t", str(d), "-i", src,
            "-vf", f"{vf},scale=-2:'min(720,trunc(ih/2)*2)'",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-threads", "1",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst], timeout=150)
    return ok and os.path.exists(dst) and os.path.getsize(dst) > 0

async def _filter_preview_image(img_bytes, vf, tag):
    src, dst = f"prev_in_{tag}.jpg", f"prev_out_{tag}.jpg"
    try:
        with open(src, "wb") as f:
            f.write(img_bytes)
        ok = await _ffmpeg_exec(["-i", src, "-vf", vf, "-frames:v", "1", "-q:v", "3", dst], timeout=20)
        if ok and os.path.exists(dst):
            with open(dst, "rb") as f:
                return f.read()
        return None
    finally:
        for p in (src, dst):
            try: os.remove(p)
            except Exception: pass

# ---------- معالج أزرار تعديل المقطع ----------
async def edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if get_setting("maint") and uid != ADMIN_ID:
        await q.answer("🔧 البوت تحت الصيانة حالياً", show_alert=True)
        return
    parts = q.data.split("_")          # ed_<action>[_<arg>]_<sid>
    action, sid = parts[1], parts[-1]
    arg = parts[2] if len(parts) == 4 else None
    url = URL_CACHE.get(sid)
    if not url:
        await q.answer("انتهت صلاحية الجلسة، أعد إرسال الرابط", show_alert=True)
        return

    if action == "menu":
        await q.answer()
        track_feature("edit_open", uid)
        TRIM_PENDING.pop(uid, None)
        await _send_edit_menu(q.message, uid, sid)
        return

    if action == "clr":
        await q.answer("تم المسح")
        EDIT_STATE[f"{uid}:{sid}"] = {"f": None, "c": None}
        try:
            await q.message.edit_text(_edit_menu_text(uid, sid), parse_mode="HTML", reply_markup=_edit_menu_markup(uid, sid))
        except Exception:
            pass
        return

    if action == "fl":
        await q.answer()
        await q.message.reply_text(
            "🎨 <b>الفلاتر</b>\nاضغط على فلتر لمعاينته على صورة من المقطع 👇",
            parse_mode="HTML", reply_markup=_filters_markup(sid))
        return

    if action == "pick" and arg in FILTERS:
        _edit_get(uid, sid)["f"] = arg
        await q.answer("✅ تم اختيار الفلتر")
        await _send_edit_menu(q.message, uid, sid)
        return

    if action == "p" and arg in FILTERS:
        await q.answer("⏳ جاري تجهيز المعاينة...")
        try:
            img = THUMB_CACHE.get(sid)
            if not img:
                if _is_tiktok(url):
                    async with TIKTOK_INFO_SEM:
                        thumb_url = (await run_isolated("info", url, _tt_info_opts())).get("thumbnail")
                else:
                    thumb_url = await asyncio.wait_for(run_blocking(_blocking_get_thumbnail, url), timeout=30)
                if not thumb_url:
                    raise Exception("no thumbnail")
                img = await asyncio.wait_for(run_blocking(_blocking_fetch_bytes, thumb_url), timeout=20)
                THUMB_CACHE[sid] = img
            label, vf = FILTERS[arg]
            out = await _filter_preview_image(img, vf, f"{uid}_{sid}_{arg}")
            if not out:
                raise Exception("preview failed")
            await q.message.reply_photo(
                photo=out,
                caption=f"🎨 معاينة: <b>{label}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ اختيار هذا الفلتر", callback_data=f"ed_pick_{arg}_{sid}", style="success")],
                    [InlineKeyboardButton("🎨 فلاتر أخرى", callback_data=f"ed_fl_{sid}")],
                ]))
        except Exception as e:
            logger.error(f"Filter preview failed: {e}")
            await q.message.reply_text("❌ تعذرت معاينة الفلتر لهذا الرابط.")
        return

    if action == "cut":
        await q.answer()
        TRIM_PENDING[uid] = {"sid": sid, "start": None}
        quick = [InlineKeyboardButton(f"⏱ أول {n} ث", callback_data=f"ed_q_{n}_{sid}") for n in (15, 30, 60) if n <= TRIM_MAX_SECONDS]
        rows = [quick] if quick else []
        rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"ed_menu_{sid}")])
        await q.message.reply_text(
            "✂️ <b>قص الفيديو</b>\n\n"
            "اختر قصاً سريعاً من الأزرار، أو أرسل <b>وقت البداية</b> برقم بسيط (مثال: <code>10</code> أو <code>1:05</code>)، "
            "وبعدها أرسل <b>وقت النهاية</b>.\n"
            f"<i>أقصى مدة للقص: {TRIM_MAX_SECONDS} ثانية.</i>",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "q" and arg and arg.isdigit():
        n = min(int(arg), TRIM_MAX_SECONDS)
        _edit_get(uid, sid)["c"] = (0, n)
        TRIM_PENDING.pop(uid, None)
        await q.answer("✅ تم تحديد القص")
        await _send_edit_menu(q.message, uid, sid)
        return

    await q.answer()

apply_settings()

async def donate_star_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        await context.bot.send_invoice(
            chat_id=q.message.chat_id,
            title="دعم بوت ZenDown",
            description="تبرع بنجمة واحدة لدعم استمرار وتطوير البوت 💙",
            payload="zendown_star_donation",
            currency="XTR",
            prices=[LabeledPrice("نجمة دعم", 1)],
        )
    except Exception as e:
        logger.error(f"Failed to send star invoice: {e}")
        await q.message.reply_text("❌ تعذر فتح نافذة التبرع حالياً، حاول لاحقاً.")

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    payload = sp.invoice_payload or ""
    stats["stars_received"] = stats.get("stars_received", 0) + int(sp.total_amount or 0)
    if payload.startswith("plan_") and payload[5:] in PLANS:
        plan = PLANS[payload[5:]]
        uid = str(update.effective_user.id)
        stats.setdefault("premium", {})
        # لو اشتراكه فعّال نمدّد من تاريخ الانتهاء، وإلا من الآن
        base = premium_until(uid) or datetime.now()
        new_exp = base + timedelta(days=plan["days"])
        stats["premium"][uid] = new_exp.isoformat()
        stats["plan_sales"] = stats.get("plan_sales", 0) + 1
        save_stats()
        await update.message.reply_text(
            f"🎉 <b>أهلاً بك في ZenDown Pro!</b>\n\n"
            f"✅ تم تفعيل الباقة <b>{plan['label']}</b>\n"
            f"📅 تنتهي في: <b>{new_exp.strftime('%Y-%m-%d %H:%M')}</b>\n\n"
            "مزاياك الآن:\n🚀 تخطي الطابور\n🎬 تعديل المقطع (فلاتر + قص) من زر «تعديل المقطع» تحت أي رابط\n\nشكراً لدعمك 💙",
            parse_mode="HTML")
        return
    stats["star_donations"] = stats.get("star_donations", 0) + 1
    save_stats()
    await update.message.reply_text("🌟 شكراً جزيلاً على دعمك! هذا يساعدنا نستمر ونطوّر البوت. 💙")

async def download_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    parts = q.data.split("_")
    if parts[0] == "ed":          # ed_go_<sid> : تطبيق التعديلات (فلتر + قص)
        action, sid = "edt", parts[-1]
    else:
        _, action, sid = parts
    url = URL_CACHE.get(sid)

    if get_setting("maint") and q.from_user.id != ADMIN_ID:
        await q.message.reply_text("🔧 البوت تحت الصيانة حالياً، نعود قريباً بإذن الله.")
        return

    if not url:
        await q.message.reply_text("❌ انتهت صلاحية هذه الجلسة، أعد إرسال الرابط.")
        return

    if action == "cap":
        wait = await q.message.reply_text("📝 جاري جلب الوصف...")
        try:
            if _is_tiktok(url):
                async with TIKTOK_INFO_SEM:
                    cap = (await run_isolated("info", url, _tt_info_opts())).get("description", "")
            else:
                cap = await asyncio.wait_for(run_blocking(_blocking_get_caption, url), timeout=30)
            if not cap:
                await wait.edit_text("ℹ️ لا يوجد وصف لهذا المنشور.")
            else:
                import html as _html
                await wait.edit_text(
                    f"📝 <b>الوصف</b> <i>(اضغط على النص للنسخ)</i>\n\n<code>{_html.escape(cap[:3800])}</code>",
                    parse_mode="HTML")
        except Exception as e:
            logger.error(f"Caption fetch failed: {e}")
            await wait.edit_text("❌ تعذر جلب الوصف لهذا الرابط.")
        return

    uid_now = q.from_user.id
    premium = is_premium(uid_now)

    edit_st = None
    if action == "edt":
        if not premium and free_trials_left(uid_now) <= 0:
            await _pro_upsell_apply(q)
            return
        edit_st = _edit_get(uid_now, sid)
        if not edit_st["f"] and not edit_st["c"]:
            await q.message.reply_text("اختر فلتراً أو قصاً أولاً من قائمة 🎬 تعديل المقطع.")
            return

    # فحص الزحمة: لو عدد الطلبات المنتظرة وصل للحد الأقصى، نرفض فوراً برسالة واضحة
    # بدل ما نضيف الطلب لطابور بلا سقف يتراكم ويصير هو نفسه سبب انفجار الذاكرة.
    global _pending_downloads
    async with _pending_lock:
        if _pending_downloads >= MAX_QUEUE_SIZE and not premium:
            await q.message.reply_text(
                "🚧 البوت مزدحم حالياً (عدد كبير من الطلبات بالطابور).\n\n"
                "تقدر تنتظر شوي وتحاول مرة ثانية، أو تتخطى الطابور بالاشتراك في Pro 👑\n"
                "<i>البوت يبقى مجاني، وPro اختياري.</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👑 تخطي الطابور (Pro)", callback_data="pro_menu", style="primary")]])
            )
            return
        _pending_downloads += 1

    platform = detect_platform(url)
    status_msg = await q.message.reply_text("⏳ أضيفت إلى طابور التحميل الذكي...")
    out_tmpl = f"zendown_{sid}.%(ext)s"

    if action == "img":
        try:
            async with DOWNLOAD_SEMAPHORE:
                await status_msg.edit_text("🖼 جاري جلب الصورة...")
                if _is_tiktok(url):
                    thumb_url = (await run_isolated("info", url, _tt_info_opts())).get("thumbnail")
                else:
                    thumb_url = await asyncio.wait_for(run_blocking(_blocking_get_thumbnail, url), timeout=30)
            if not thumb_url:
                raise Exception("لا يوجد صورة مصغرة لهذا الرابط")
            img_bytes = await asyncio.wait_for(run_blocking(_blocking_fetch_bytes, thumb_url), timeout=20)
            await q.message.reply_photo(photo=img_bytes, caption="🖼 تم بواسطة @ZenDown_Bot")
            track_download_status(True, platform)
            track_user_download(update.effective_user.id, platform)
            await status_msg.delete()
        except Exception as e:
            logger.error(f"Image fetch failed: {e}")
            track_download_status(False, platform)
            await status_msg.edit_text("❌ تعذر جلب صورة لهذا الرابط.")
        finally:
            async with _pending_lock:
                _pending_downloads -= 1
        return

    if action in ("vid", "edt"):
        opts = {
            # تخفيف شرط الصيغة: بعض المنصات (بينترست مثلاً) ترجع ملف واحد مدمج (فيديو+صوت) مو
            # مسارين منفصلين، وكان شرط bestvideo+bestaudio الصارم يفشّل هالحالات بدون داعٍ.
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best/bv*+ba/bv*',
            'outtmpl': out_tmpl,
            'quiet': True,
            'no_warnings': True,
            'cookiefile': COOKIES_FILE,
        'proxy': PROXY_URL,
            'geo_bypass': True,
            'nocheckcertificate': True,
            'socket_timeout': 20,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'extractor_args': {
                # android/ios/mweb تشتغل مع رمز bgutil التلقائي بدون أي حاجة لكوكيز (حسب دليل
                # yt-dlp الرسمي). شلنا tv لأنها تحتاج كوكيز لأي صيغة غير محمية DRM أصلاً.
                'youtube': {'player_client': ['android', 'ios', 'mweb', 'web']},
                'twitter': {'api': ['syndication', 'graphql', 'legacy']},
                'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}
            }
        }
    elif action == "aud":
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_tmpl,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'quiet': True,
            'no_warnings': True,
            'cookiefile': COOKIES_FILE,
        'proxy': PROXY_URL,
            'geo_bypass': True,
            'nocheckcertificate': True,
            'socket_timeout': 20,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'extractor_args': {
                'youtube': {'player_client': ['android', 'ios', 'mweb', 'web']},
                'twitter': {'api': ['syndication', 'graphql', 'legacy']},
                'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}
            }
        }
    else:
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_tmpl,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'vorbis'}],
            'quiet': True,
            'no_warnings': True,
            'cookiefile': COOKIES_FILE,
        'proxy': PROXY_URL,
            'geo_bypass': True,
            'nocheckcertificate': True,
            'socket_timeout': 20,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'extractor_args': {
                'youtube': {'player_client': ['android', 'ios', 'mweb', 'web']},
                'twitter': {'api': ['syndication', 'graphql', 'legacy']},
                'tiktok': {'api_hostname': ['api22-normal-c-useast2a.tiktokv.com']}
            }
        }

    file_path = None
    cut_src = None
    success_download = False

    # === مرحلة التحميل فقط - محاولة واحدة بس (بدون إعادة محاولة) عشان السرعة والخفة ===
    async with DOWNLOAD_SEMAPHORE:
        await status_msg.edit_text("🚀 جاري التحميل...")
        try:
            if _is_tiktok(url):
                file_path = (await run_isolated("download", url, opts))["file"]
            else:
                file_path = await asyncio.wait_for(run_blocking(_blocking_download, url, opts), timeout=90)
            if action == "edt":
                await status_msg.edit_text("🎬 جاري تطبيق التعديلات (قد ياخذ دقيقة)...")
                cut_src = file_path
                file_path = f"edt_{sid}.mp4"
                vf = FILTERS[edit_st["f"]][1] if edit_st["f"] else None
                ok = await _ffmpeg_edit(cut_src, file_path, edit_st["c"], vf)
                if not ok:
                    raise Exception("ffmpeg edit failed")
            if action == "aud": file_path = file_path.rsplit('.', 1)[0] + '.mp3'
            if action == "voc": file_path = file_path.rsplit('.', 1)[0] + '.ogg'

            if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                success_download = True
        except asyncio.TimeoutError:
            logger.error("Download timed out after 90s")
        except Exception as e:
            root_cause = f" | السبب الحقيقي: {e.__cause__}" if e.__cause__ else ""
            logger.error(f"Download failed: {e}{root_cause}")

    # === مرحلة الضغط والإرسال - خارج طابور التحميل، تحت سيمافور مستقل ===
    try:
        if success_download and file_path and os.path.exists(file_path) and os.path.getsize(file_path) > 0:

            # جدار حماية تيليجرام: أي ملف أكبر من 50 ميجا نرد برسالة صادقة وواضحة بدل ما نحاول
            # حلول بديلة تثقل على الموارد - الصدق والسرعة أهم من "إيجاد حل" لكل حالة
            final_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if final_size_mb >= 49.5:
                await status_msg.edit_text(f"مقطع حجمه أكثر من 50 ميجا ({final_size_mb:.1f} ميجا) - يتجاوز حد تليجرام للبوتات، ما نقدر نرسله للأسف.")
                track_download_status(False, platform)
                return

            await status_msg.edit_text("📤 جاري إرسال الملف...")
            with open(file_path, 'rb') as f:
                if action in ("vid", "edt"): await q.message.reply_video(video=f, caption="🎬 تم بواسطة @ZenDown_Bot", supports_streaming=True)
                elif action == "aud": await q.message.reply_audio(audio=f, caption="🎵 تم بواسطة @ZenDown_Bot")
                elif action == "voc": await q.message.reply_voice(voice=f, caption="🎙 تم بواسطة @ZenDown_Bot")

            # الملف وصل بنجاح - نسجل النجاح فوراً قبل أي خطوة إضافية غير حرجة
            track_download_status(True, platform)
            track_user_download(update.effective_user.id, platform)
            await status_msg.delete()

            if action == "edt":
                track_feature("edit_done", uid_now)
                if not premium:
                    use_free_trial(uid_now)
                    try:
                        await q.message.reply_text(
                            f"🎁 تبقّى لك <b>{free_trials_left(uid_now)}</b> من {int(get_setting('free_trials'))} تجارب مجانية.\nللاستمرار بدون حدود: /pro",
                            parse_mode="HTML")
                    except Exception:
                        pass

            # زر التبرع اختياري وغير حرج - أي فشل فيه (تايم آوت مثلاً) ما يجب يؤثر على نتيجة التحميل
            try:
                donate_markup = InlineKeyboardMarkup([[InlineKeyboardButton("تبرع للبوت بـ 1 ⭐", callback_data="donate_star")]])
                await q.message.reply_text("لو حاب تدعم استمرار البوت، تقدر تتبرع بنجمة ⬇️", reply_markup=donate_markup)
            except Exception as e:
                logger.error(f"Donate button send failed (non-critical): {e}")
        else:
            track_download_status(False, platform)
            await status_msg.edit_text("❌ حدث خطأ أثناء التحميل، قد يكون المقطع محمي كلياً أو يحتاج تسجيلاً إجبارياً.")
    except Exception as e:
        logger.error(f"Send Error: {e}")
        track_download_status(False, platform)
        await status_msg.edit_text("❌ حدث خطأ أثناء معالجة وإرسال الملف.")
    finally:
        for _p in (file_path, cut_src):
            if _p and os.path.exists(_p):
                try: os.remove(_p)
                except Exception: pass
        async with _pending_lock:
            _pending_downloads -= 1

# ================== معالج الأخطاء العام ==================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    يمسك أي استثناء غير متوقع بأي مكان بالبوت (بدل ما يضيع برسالة 'No error handlers are
    registered'). يسجل التتبع الكامل (traceback) بدون قص، عشان أي خلل جديد نقدر نشخصه
    بدقة من أول مرة بدل ما ننتظر يتكرر.
    """
    import traceback
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(f"استثناء غير متوقع (Unhandled): {context.error}\n{tb_string[-1500:]}")

# ================== التشغيل الرئيسي ==================
# ================== حارس الذاكرة (Memory Watchdog) ==================
async def _memory_watchdog():
    """
    يراقب استهلاك الذاكرة الفعلي للعملية كل 15 ثانية. لو اقترب من حد الخطر، يعيد تشغيل
    العملية بشكل منظم ونظيف (خلال ثوانٍ، وRender يعيد تشغيلها تلقائياً فوراً) بدل ما ينتظر
    حتى تمتلئ الذاكرة بالكامل ويضطر Render يقتل العملية بالقوة (اللي يسبب التجمد الكامل).
    فحص كل 15 ثانية (بدل كل 5 دقائق) عشان يلحق يتدارك القفزات السريعة بالذاكرة (زي وقت رفع
    ملف كبير لخدمة خارجية) قبل ما توصل الحد الفعلي وتضطر Render تتدخل بالقوة.
    هذا ما يحل سبب استهلاك الذاكرة نفسه، بس يحول أي مشكلة مستقبلية لانقطاع خاطف ومتحكم فيه
    بدل توقف كامل يحتاج تدخل يدوي.
    """
    THRESHOLD_MB = 400  # هامش أمان أكبر تحت حد 512 ميجا، لأن الفحص صار أسرع بكثير
    while True:
        await asyncio.sleep(15)  # فحص كل 15 ثانية (بدل 5 دقائق) - القفزات صارت أسرع من كذا
        try:
            with open('/proc/self/status') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        rss_mb = int(line.split()[1]) / 1024
                        logger.info(f"Memory watchdog: RSS={rss_mb:.0f}MB")
                        if rss_mb >= THRESHOLD_MB:
                            logger.error(f"Memory watchdog: تجاوزت الذاكرة {rss_mb:.0f}MB الحد الآمن ({THRESHOLD_MB}MB) - إعادة تشغيل منظمة الآن.")
                            # حفظ فوري ومضمون قبل الخروج - os._exit() يقفل كل شي بالقوة بدون
                            # أي تنظيف، فلازم نحفظ هنا صراحة قبل لا نوصل له، مو ننتظر الدورة التالية
                            await turso_push_now()
                            os._exit(0)
                        break
        except Exception as e:
            logger.error(f"Memory watchdog check failed: {e}")

async def _post_init(application):
    asyncio.create_task(_memory_watchdog())
    await turso_load_on_startup()
    apply_settings()
    asyncio.create_task(turso_sync_loop())
    # تيليجرام ما يسمح بأسماء أوامر عربية (لازم إنجليزي صغير بدون مسافات)، فنسجل الأمر
    # بالإنجليزي "mystats" لكن بوصف عربي - عشان يظهر بقائمة الأوامر لما يكتب المستخدم "/"
    try:
        await application.bot.set_my_commands([
            ("start", "🚀 بدء استخدام البوت"),
            ("pro", "👑 باقات Pro"),
            ("qr", "📱 تحويل رابط إلى QR"),
            ("mystats", "📊 إحصائياتي"),
            ("paysupport", "💬 دعم المدفوعات"),
        ])
        # أمر الأدمن - يظهر لك أنت فقط في قائمة "/" (كل التحكم صار داخل لوحة واحدة)
        from telegram import BotCommandScopeChat
        await application.bot.set_my_commands([
            ("start", "🚀 بدء استخدام البوت"),
            ("pro", "👑 باقات Pro"),
            ("qr", "📱 تحويل رابط إلى QR"),
            ("mystats", "📊 إحصائياتي"),
            ("paysupport", "💬 دعم المدفوعات"),
            ("admin", "⚙️ لوحة تحكم الأدمن"),
        ], scope=BotCommandScopeChat(chat_id=ADMIN_ID))
    except Exception as e:
        logger.error(f"set_my_commands failed: {e}")

async def _post_shutdown(application):
    """حفظ أخير عند أي إغلاق منظم (إعادة نشر يدوية، إيقاف من ريندر، تحديث...) - غير حالة
    os._exit() القسرية بتاعة حارس الذاكرة، اللي لها حفظها المباشر الخاص بها."""
    await turso_push_now()

def main():
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).post_init(_post_init).post_shutdown(_post_shutdown).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_capture), group=-1)
    app.add_handler(CallbackQueryHandler(broadcast_cancel_callback, pattern="^bc_cancel$"))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(mode_callback, pattern="^mode_(qr|ocr|dl)$"))
    app.add_handler(CallbackQueryHandler(ocr_cancel_callback, pattern="^ocr_cancel$"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(إعدادات|اعدادات) (الأدمن|الادمن)$|^لوحة (التحكم|الأدمن|الادمن)$|^(الأدمن|الادمن|ادمن)$"), admin_panel_command))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(bc_stop_callback, pattern="^bc_stop$"))
    app.add_handler(CallbackQueryHandler(bc_delete_callback, pattern="^bc_(del|delyes|delno)$"))
    app.add_handler(CallbackQueryHandler(edit_callback, pattern="^ed_(menu|fl|p|pick|cut|q|clr)_"))
    app.add_handler(CommandHandler("pro", pro_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(الباقات|باقات|اشتراك|الاشتراك|pro|Pro|PRO)$"), pro_command))
    app.add_handler(CommandHandler("qr", qr_command))
    app.add_handler(CommandHandler("paysupport", paysupport_command))
    app.add_handler(CallbackQueryHandler(pro_menu_callback, pattern="^pro_menu$"))
    app.add_handler(CallbackQueryHandler(buy_plan_callback, pattern="^buy_"))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(qr_cancel_callback, pattern="^qr_cancel$"))
    
    app.add_handler(CommandHandler("stats", show_stats_command))
    app.add_handler(CommandHandler("cookies", cookies_check_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(كوكيز|الكوكيز)$"), cookies_check_command))
    app.add_handler(CommandHandler("errors", show_errors_command))
    app.add_handler(CommandHandler("all_errors", show_all_errors_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(اخطاء|أخطاء)$"), show_errors_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(كل الأخطاء|جميع الأخطاء)$"), show_all_errors_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(احصائيات|إحصائيات)$"), show_stats_command))
    app.add_handler(CallbackQueryHandler(show_stats_command, pattern="^refresh_stats$"))

    app.add_handler(CommandHandler("mystats", show_my_stats_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(احصائياتي|إحصائياتي)$"), show_my_stats_command))

    app.add_handler(CallbackQueryHandler(download_action_callback, pattern="^(down_|ed_go_)"))
    app.add_handler(CallbackQueryHandler(donate_star_callback, pattern="^donate_star$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 تم تشغيل محرك @ZenDown_Bot بنجاح! مزود بحماية الـ OOM والجدار الأمني لتيليجرام.")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
