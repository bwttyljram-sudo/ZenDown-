import subprocess
import sys
import asyncio
import logging
import os
import uuid
import threading
import json
import re
import random
import shutil
import urllib.request
import urllib.error
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, WebAppInfo
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

# خادم التطبيق المصغر (webapp_api.py) يحل محل خادم الصحة على نفس المنفذ. لو الملف غير موجود أو فشل
# يرجع الخادم القديم تلقائياً، فلا يتأثر البوت أبداً.
try:
    import webapp_api
    webapp_api.start_server()
except Exception as _wa_err:
    print(f"⚠️ webapp_api غير متاح ({_wa_err}) - تشغيل خادم الصحة العادي")
    webapp_api = None
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
CHANNEL = "@Zenox_Tols"
ADMIN_ID = 9253474579

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
MAX_CONCURRENT_DOWNLOADS = 2          # التحميل خفيف على المعالج (شبكة)، فنسمح بطلبين معاً
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
PROCESS_SEMAPHORE = asyncio.Semaphore(1)     # معالجة ffmpeg الثقيلة بطابور مستقل: ما تسد التحميل العادي

# عداد الطلبات المنتظرة بالطابور - بدون سقف، أي عدد طلبات ممكن ينتظر بلا حد، وكل طلب منتظر
# ياخذ ذاكرة وهو واقف بالدور. وقت الزحمة الكبيرة (آلاف المستخدمين)، الطابور يكبر بلا توقف
# ويصير هو نفسه سبب انفجار الذاكرة (حلقة مفرغة). بحد أقصى للطابور، أي طلب زايد يترفض فوراً
# برسالة واضحة بدل ما يتراكم للأبد.
MAX_QUEUE_SIZE = 6
# رفع الملفات لتيليجرام يقرأ الملف كامل بالذاكرة (حتى 50MB للرفعة). كان بلا حد، فعشرات الرفعات المتزامنة وقت الزحمة
# تقفز بالذاكرة فوق حد الأمان. نحدّها برفعتين بنفس اللحظة.
SEND_SEMAPHORE = asyncio.Semaphore(2)
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

_STATS_VER = [0]          # يزيد مع كل تغيير؛ طبقة Turso والقرص يقارنون به ويتجاهلون لو ما تغيّر شيء
_STATS_DISK_VER = [0]

def save_stats():
    """خفيفة جداً: فقط تعلّم أن الحالة تغيّرت. الكتابة الفعلية (ثقيلة مع 17 ألف مستخدم) تتم مجمّعة في الخلفية."""
    _STATS_VER[0] += 1

def flush_stats_to_disk(force=False):
    if not force and _STATS_DISK_VER[0] == _STATS_VER[0]:
        return
    ver = _STATS_VER[0]
    try:
        tmp = STATS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False)
        os.replace(tmp, STATS_FILE)
        _STATS_DISK_VER[0] = ver
    except Exception as e:
        logger.error(f"stats disk flush failed: {e}")

async def stats_disk_loop():
    while True:
        await asyncio.sleep(60)
        try:
            flush_stats_to_disk()
        except Exception:
            pass

# ================== طبقة التخزين الدائم (ملف zen_store.py المنفصل) ==================
import zen_store
zen_store.STATS_VER = _STATS_VER          # عدّاد التغييرات مشترك مع طبقة التخزين (لتجاهل الحفظ لو ما تغيّر شيء)
from zen_store import (turso_load_on_startup, turso_push_now, turso_sync_loop, url_put, get_session_url,
                       send_backup, backup_loop, list_snapshots, restore_snapshot, restore_from_bytes,
                       _alert_admin, DIRTY_USERS, BOT_REF, BOOT_ID)

async def restore_from_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    try:
        f = await m.document.get_file()
        raw = bytes(await f.download_as_bytearray())
        before, added, now = await restore_from_bytes(raw)
        await m.reply_text(f"✅ تمت الاستعادة (دمج إضافي، لم يُحذف شيء)\n👥 قبل: {before}\n➕ مستخدمون جدد: {added}\n👥 الآن: {now}")
    except Exception as e:
        logger.error(f"restore failed: {e}")
        await m.reply_text(f"❌ تعذرت الاستعادة: {str(e)[:200]}")

def track_user_activity(user_id):
    uid = str(user_id)
    stats["users"][uid] = datetime.now().isoformat()
    DIRTY_USERS.add(uid)
    if stats.get("bc_dead"): stats["bc_dead"].pop(uid, None)      # رجع يتفاعل = نشيله من قائمة الحاظرين
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
_SUB_OK = {}            # user_id -> وقت آخر تحقق ناجح (نخزّن النجاح فقط)
SUB_CACHE_TTL = 300     # 5 دقايق: يخفف مئات آلاف الطلبات على تيليجرام وقت الزحمة بدون ما يضر الاشتراك الإجباري

async def check_user_subscription(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    now = time.time()
    ts = _SUB_OK.get(user_id)
    if ts and now - ts < SUB_CACHE_TTL:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        ok = member.status in ["member", "administrator", "creator"]
        if ok:
            if len(_SUB_OK) > 20000:
                _SUB_OK.clear()
            _SUB_OK[user_id] = now
        return ok
    except Exception:
        return False

def _sub_text():
    return (
        "🚧 <b>خطوة واحدة فقط قبل الاستخدام</b>\n\n"
        f"اشترك في قناة التحديثات {CHANNEL} 📢\n"
        "✅ هي <b>القناة الوحيدة</b> المطلوبة، ولا نطلب منك الاشتراك في أي قناة أخرى.\n"
        "نعلن فيها عن المزايا الجديدة وأي تحديث أو تغيير يخص البوت.\n\n"
        "بعد الاشتراك اضغط <b>تحقق 🔍</b> وابدأ التحميل فوراً."
    )

def _sub_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("اشترك في القناة 📡", url=f"https://t.me/{CHANNEL.lstrip('@')}", style="primary")],
        [InlineKeyboardButton("تحقق 🔍", callback_data="check_sub", style="success")]
    ])

async def _ask_subscribe(message):
    await message.reply_text(_sub_text(), parse_mode="HTML", reply_markup=_sub_markup())

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
            "📊 <b>إحصائياتك</b>\n━━━━━━━\n\n"
            f"{_pro_status_block(user.id)}"
            "ما سويت أي تحميل لسا! أرسل رابط فيديو وابدأ 🚀",
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
    pro_line = _pro_status_block(user.id)
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
    if update.callback_query and update.callback_query.data == "st_pro":
        return await show_pro_stats(update, context)

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
    fl_u, fl_n = feat_counts("edit_filter")
    cu_u, cu_n = feat_counts("edit_cut")
    sp_u, sp_n = feat_counts("edit_speed")
    or_u, or_n = feat_counts("edit_orient")
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

    try:
        _ap = webapp_api.app_stats_summary() if webapp_api else None
    except Exception:
        _ap = None
    app_block = ""
    if _ap:
        app_block = (
            "📱 <b>التطبيق المصغر</b>\n"
            "───────────────\n"
            f"👥 دخلوا التطبيق      : {_ap['total']}\n"
            f"🟢 نشطون الآن (5 د)   : {_ap['now']}\n"
            f"☀️ نشطون (اليوم)      : {_ap['day']}\n"
            f"📅 نشطون (7 أيام)     : {_ap['d7']}\n"
            f"🗓 نشطون (30 يوم)     : {_ap['d30']}\n"
            f"🚪 مرات الفتح         : {_ap['opens']}\n"
            f"🎬 تعديلات من التطبيق : {_ap['edits']}\n"
            f"📥 تحميلات من التطبيق : {_ap['downloads']}\n"
            f"💎 طلبات TON          : {_ap['ton_orders']} (مؤكَّدة منهم: {_ap['ton_done']})\n"
            "───────────────\n\n"
        )
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
        "🎬 <b>تعديل المقطع</b>\n"
        "───────────────\n"
        f"👀 فتحوا القائمة   : {eo_u} مستخدم\n"
        f"✅ طبّقوا فعلاً     : {ed_u} مستخدم ({ed_n} عملية)\n"
        f"🎨 فلاتر           : {fl_u} مستخدم ({fl_n})\n"
        f"✂️ قص             : {cu_u} مستخدم ({cu_n})\n"
        f"⏩ سرعة           : {sp_u} مستخدم ({sp_n})\n"
        f"📐 اتجاه          : {or_u} مستخدم ({or_n})\n"
        f"🎁 تجارب مجانية مستهلكة : {trials_used}\n"
        "───────────────\n\n"
        "🔤 <b>استخراج النص</b>\n"
        "───────────────\n"
        f"✅ ناجحة           : {oc_n}\n"
        f"❌ بدون نتيجة/فاشلة : {oc_f}\n"
        f"👥 المستخدمون      : {oc_u}\n"
        "───────────────\n\n"
        f"{app_block}"
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

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data="refresh_stats", style="primary"),
                                    InlineKeyboardButton("👑 إحصائيات Pro", callback_data="st_pro")]])
    if update.callback_query and update.callback_query.data in ("refresh_stats", "st_back"):
        await update.callback_query.answer("تم التحديث 🔄")
        try:
            await msg.edit_text(stats_msg, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
    else:
        await msg.reply_text(stats_msg, parse_mode="HTML", reply_markup=markup)

async def show_pro_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """صفحة إحصائيات Pro المنفصلة (زر داخل لوحة الإحصائيات)."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return
    cq = update.callback_query
    now = datetime.now()
    pro_now = sorted(((u, premium_until(u)) for u in stats.get("premium", {})), key=lambda x: x[1] or now)
    pro_now = [(u, e) for u, e in pro_now if e]
    by_plan = {k: 0 for k in PLANS}
    for u, _e in pro_now:
        by_plan[_pro_plan_of(u)] += 1
    soon = sum(1 for _u, e in pro_now if (e - now) <= timedelta(hours=48))
    plan_lines = "\n".join(f"   ▫️ {PLANS[k]['label']}: {n}" for k, n in by_plan.items())

    ed_u, ed_n = feat_counts("edit_done")
    _, fail_n = feat_counts("edit_fail")
    tot_edit = ed_n + fail_n
    ok_rate = (ed_n / tot_edit * 100) if tot_edit else 0.0
    fl_u, fl_n = feat_counts("edit_filter")
    cu_u, cu_n = feat_counts("edit_cut")
    sp_u, sp_n = feat_counts("edit_speed")
    or_u, or_n = feat_counts("edit_orient")
    trials_used = sum(p.get("free_edits", 0) for p in stats.get("user_profiles", {}).values())

    done_map = stats.get("feat", {}).get("edit_done", {})
    top = sorted(done_map.items(), key=lambda x: x[1], reverse=True)[:5]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    top_lines = []
    for i, (u, n) in enumerate(top):
        tag = " 👑" if premium_until(u) else ""
        top_lines.append(f"{medals[i]} <code>{u}</code>{tag} — {n} مقطع")
    top_str = "\n".join(top_lines) if top_lines else "لا يوجد بعد."

    lst = pro_now[:15]
    lst_str = "\n".join(f"• <code>{u}</code> — {_plan_label(u)} — باقي {_remaining_text(e)}" for u, e in lst) or "لا يوجد"
    more = f"\n… و{len(pro_now) - 15} آخرين" if len(pro_now) > 15 else ""

    text = (
        "👑 <b>إحصائيات Pro</b>\n━━━━━━━\n\n"
        "👥 <b>المشتركون</b>\n───────────────\n"
        f"👑 مشتركون الآن : {len(pro_now)}\n{plan_lines}\n"
        f"⏳ ينتهون خلال 48 ساعة : {soon}\n"
        f"🔔 تذكيرات تجديد أُرسلت : {len(stats.get('pro_reminded', {}))}\n"
        f"🧾 اشتراكات مباعة : {stats.get('plan_sales', 0)}\n"
        f"⭐ النجوم المستلمة : {stats.get('stars_received', 0)}\n"
        "───────────────\n\n"
        "🎬 <b>مقاطع التعديل</b>\n───────────────\n"
        f"✅ ناجحة : {ed_n} ({ed_u} مستخدم)\n"
        f"❌ فاشلة : {fail_n}\n"
        f"📈 نسبة النجاح : {ok_rate:.1f}%\n"
        f"🎨 فلاتر {fl_n} • ✂️ قص {cu_n} • ⏩ سرعة {sp_n} • 📐 اتجاه {or_n}\n"
        f"🎁 تجارب مجانية مستهلكة : {trials_used}\n"
        "───────────────\n\n"
        "🏆 <b>أبرز 5 مستهلكين للتعديل</b>\n───────────────\n"
        f"{top_str}\n"
        "───────────────\n\n"
        "📋 <b>الأقرب انتهاءً</b>\n───────────────\n"
        f"{lst_str}{more}"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data="st_pro", style="primary"),
                                    InlineKeyboardButton("⬅️ الإحصائيات", callback_data="refresh_stats")]])
    if cq:
        await cq.answer()
        try:
            await cq.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)

# ================== الإذاعة (شريط تقدم + إلغاء + حذف من عند الجميع) ==================
BROADCAST_MODE = {"on": False}
BC = {"running": False, "cancel": False, "lvl": 3, "pause_until": 0.0, "task": None, "progress": 0.0, "flood": 0}
BC_RATES = [2, 4, 8, 12, 18, 25]      # سرعات الإذاعة (رسالة/ثانية). حد تيليجرام ≈ 30
BC_WORKERS = 6                         # عدد الإرسالات المتوازية
BC_SEND_TIMEOUT = 25                   # مهلة كل إرسال (ثانية) فلا يعلّق طلب واحد الإذاعة كلها
INACTIVE_DAYS = 7

# ---------- اختيار فئة المستلمين للإذاعة ----------
BC_AUDIENCE = {"v": "all"}      # all / active / pro / custom
BC_CUSTOM = {"ids": []}         # المستلمون المحددون يدوياً (فئة custom)
ACTIVE_HOURS = 24               # تعريف "النشطون": تفاعلوا خلال آخر كم ساعة

def _audience_users(kind=None):
    kind = kind or BC_AUDIENCE["v"]
    if kind == "custom":
        return list(BC_CUSTOM["ids"])
    dead = stats.get("bc_dead", {})          # حاظرين/محذوفين: نستبعدهم (يرجعون تلقائياً لو تفاعلوا)
    ids = [u for u in stats["users"] if u not in dead]
    if kind == "pro":
        return [u for u in ids if premium_until(u)]
    if kind in ("active", "inactive"):
        lim = datetime.now() - (timedelta(hours=ACTIVE_HOURS) if kind == "active" else timedelta(days=INACTIVE_DAYS))
        out = []
        for u in ids:
            try:
                seen = datetime.fromisoformat(stats["users"][u])
            except Exception:
                continue
            if (seen >= lim) == (kind == "active"):
                out.append(u)
        return out
    return ids

def _bc_left():
    j = stats.get("bc_job") or {}
    return max(0, len(j.get("users", [])) - int(j.get("pos", 0)))

def _bc_open_markup():
    cur = BC_AUDIENCE["v"]
    def b(k, label):
        return InlineKeyboardButton(("✅ " if cur == k else "") + f"{label} ({len(_audience_users(k))})", callback_data=f"bc_aud_{k}")
    return InlineKeyboardMarkup([
        [b("all", "👥 الكل")],
        [b("active", f"🟢 النشطون {ACTIVE_HOURS}س"), b("pro", "👑 Pro")],
        [b("inactive", f"😴 غير النشطين {INACTIVE_DAYS}+ أيام")],
        [b("custom", "🎯 مستخدمون محددون")],
        *([[InlineKeyboardButton(f"▶️ استكمال الإذاعة السابقة ({_bc_left()} متبقي)", callback_data="bc_resume")]] if stats.get("bc_job") else []),
        [InlineKeyboardButton("❌ إلغاء الإذاعة", callback_data="bc_cancel")],
    ])

_BC_OPEN_TEXT = "📢 تم تفعيل الإذاعة.\nاختر الفئة المستلمة ثم أرسل أي رسالة (نص/صورة/ألبوم/ملف/محولة من قناة...) وتنرسل كما هي تماماً."

async def _bc_open(msg):
    BROADCAST_MODE["on"] = True
    BC_AUDIENCE["v"] = "all"
    BC_CUSTOM["ids"] = []
    if ADMIN_PENDING["mode"] == "bc_targets":
        ADMIN_PENDING["mode"] = None
    await msg.reply_text(_BC_OPEN_TEXT, reply_markup=_bc_open_markup())

async def bc_aud_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    BC_AUDIENCE["v"] = q.data.replace("bc_aud_", "")
    if BC_AUDIENCE["v"] == "custom":
        ADMIN_PENDING["mode"] = "bc_targets"
        await q.answer("🎯 أرسل المستلمين")
        await q.message.reply_text(
            "🎯 <b>إذاعة لمستخدمين محددين</b>\n\n"
            "أرسل واحداً من التالي:\n"
            "▫️ <b>ID واحد</b> → مثال: <code>123456789</code>\n"
            "▫️ <b>عدة IDs</b> في رسالة واحدة (مفصولة بمسافة أو سطر أو فاصلة)\n"
            "▫️ <b>رقم صغير</b> (أقل من 6 خانات) = عدد مستخدمين عشوائيين، مثال: <code>100</code>\n\n"
            "وبعدها أرسل رسالة الإذاعة نفسها.", parse_mode="HTML")
        try:
            await q.message.edit_reply_markup(reply_markup=_bc_open_markup())
        except Exception:
            pass
        return
    if ADMIN_PENDING["mode"] == "bc_targets":
        ADMIN_PENDING["mode"] = None
    await q.answer("تم اختيار الفئة")
    try:
        await q.message.edit_reply_markup(reply_markup=_bc_open_markup())
    except Exception:
        pass
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
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐢 أبطأ", callback_data="bc_spd_dn"), InlineKeyboardButton("🚀 أسرع", callback_data="bc_spd_up")],
        [InlineKeyboardButton("⛔ إلغاء الإذاعة", callback_data="bc_stop", style="danger")]])

def _bc_unstick_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔓 فك التعليق", callback_data="bc_unstick")]])

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

def _sender_from_job(bot, job):
    if job.get("kind") == "text":
        return _make_text_sender(bot, job["text"])
    return _make_sender(bot, job["chat"], job["ids"], job["fwd"])

async def _bc_send_one(sender, uid, pace, on_flood):
    from telegram.error import RetryAfter, Forbidden, BadRequest, TimedOut, NetworkError
    for _ in range(6):
        await pace()
        try:
            return "ok", await asyncio.wait_for(sender(int(uid)), BC_SEND_TIMEOUT)
        except RetryAfter as e:
            on_flood(float(getattr(e, "retry_after", 5)) + 1)      # طلب تبطئة من تيليجرام: الكل ينتظر ونخفّف السرعة
        except (TimedOut, NetworkError, asyncio.TimeoutError):
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
    return "other", "فشل بعد عدة محاولات"

def _fmt_eta(sec):
    sec = int(max(0, sec))
    return f"{sec // 3600}س {sec % 3600 // 60}د" if sec >= 3600 else f"{sec // 60}د {sec % 60}ث"

async def _run_broadcast(bot, sender, job, resume=None):
    if BC["running"]:
        await bot.send_message(chat_id=ADMIN_ID, text="⚠️ فيه عملية إذاعة/حذف جارية حالياً. لو تحسها عالقة اضغط فك التعليق.",
                               reply_markup=_bc_unstick_markup())
        return
    BC.update(running=True, cancel=False, pause_until=0.0, flood=0, task=asyncio.current_task(), progress=time.time())
    status = updater = None
    finished = False
    try:
        if resume:
            S, rec = resume, stats.get("last_broadcast") or {"time": datetime.now().isoformat(), "msgs": {}}
        else:
            users = _audience_users()
            if not users:
                await bot.send_message(chat_id=ADMIN_ID, text="⚠️ ما فيه مستلمين. اختر فئة فيها مستخدمين (أو حدّد الـ ID/العدد للمحددين) ثم أرسل الرسالة.")
                return
            rec = {"time": datetime.now().isoformat(), "msgs": {}}
            stats["last_broadcast"] = rec
            S = stats["bc_job"] = {"job": job, "users": users, "pos": 0, "ok": 0, "blocked": 0, "other": 0, "errs": {},
                                   "started": datetime.now().isoformat()}
        users, start = S["users"], int(S["pos"])
        total = len(users)
        q = asyncio.Queue()
        for u in users[start:]:
            q.put_nowait(u)
        st = {"taken": 0, "inflight": 0, "nxt": 0.0}
        t0 = time.time()

        def text_now():
            done = start + st["taken"] - st["inflight"]
            rate = BC_RATES[BC["lvl"]]
            left = total - done
            lines = [f"📢 <b>جاري الإذاعة</b>\n\n{_bar(done, total)}\n{done} / {total}\n",
                     f"✅ وصلت: {S['ok']}   🚫 حاظرين: {S['blocked']}   ⚠️ أخطاء: {S['other']}",
                     f"⚡ السرعة: {rate} رسالة/ث   ⏱ المتبقي: ~{_fmt_eta(left / rate)}"]
            wait = BC["pause_until"] - time.monotonic()
            if wait > 1:
                lines.append(f"⏳ تيليجرام طلب انتظار ~{int(wait)} ثانية (الإذاعة تكمل تلقائياً)")
            return "\n".join(lines)

        status = await bot.send_message(chat_id=ADMIN_ID, text=text_now(), parse_mode="HTML", reply_markup=_bc_cancel_markup())

        async def refresher():
            while True:
                await asyncio.sleep(3)
                try:
                    await status.edit_text(text_now(), parse_mode="HTML", reply_markup=_bc_cancel_markup())
                except Exception:
                    pass

        async def pace():
            while True:
                now = time.monotonic()
                if BC["pause_until"] > now:
                    await asyncio.sleep(min(BC["pause_until"] - now, 2))
                    continue
                slot = max(now, st["nxt"])
                st["nxt"] = slot + 1.0 / BC_RATES[BC["lvl"]]
                if slot > now:
                    await asyncio.sleep(slot - now)
                return

        def on_flood(wait):
            BC["pause_until"] = max(BC["pause_until"], time.monotonic() + wait)
            BC["lvl"] = max(0, BC["lvl"] - 1)
            BC["flood"] += 1

        async def worker():
            while not BC["cancel"]:
                try:
                    uid = q.get_nowait()
                except asyncio.QueueEmpty:
                    return
                st["taken"] += 1
                st["inflight"] += 1
                try:
                    r, info = await _bc_send_one(sender, uid, pace, on_flood)
                finally:
                    st["inflight"] -= 1
                if r == "ok":
                    S["ok"] += 1
                    rec["msgs"][uid] = info or []
                elif r == "blocked":
                    S["blocked"] += 1
                    stats.setdefault("bc_dead", {})[uid] = datetime.now().isoformat()
                else:
                    S["other"] += 1
                    S["errs"][info] = S["errs"].get(info, 0) + 1
                BC["progress"] = time.time()
                S["pos"] = start + st["taken"] - st["inflight"]
                if S["pos"] % 100 == 0:
                    save_stats()                  # نقطة حفظ: لو انقطع البوت نكمل من هنا

        updater = asyncio.create_task(refresher())
        await asyncio.gather(*[worker() for _ in range(BC_WORKERS)])
        finished = True
        cancelled = BC["cancel"]
        S["pos"] = start + st["taken"]
        done = S["pos"]
        stats.pop("bc_job", None)
        save_stats()
        await turso_push_now(force=True)
        detail = "".join(f"\n  • {k}: {v}" for k, v in list(S["errs"].items())[:5])
        title = "⛔ <b>أُلغيت الإذاعة</b>" if cancelled else "✅ <b>تمت الإذاعة</b>"
        updater.cancel()
        try:
            await status.edit_text(
                f"{title}\n\n{_bar(done, total)}\n{done} / {total}\n\n"
                f"✅ وصلت فعلاً: {S['ok']}\n🚫 حاظرين البوت: {S['blocked']} (يُستبعدون من الإذاعات القادمة)\n"
                f"⚠️ أخطاء أخرى: {S['other']}{detail}\n⏱ المدة: {_fmt_eta(time.time() - t0)}   🌊 طلبات انتظار: {BC['flood']}",
                parse_mode="HTML", reply_markup=_bc_delete_markup() if S["ok"] else None)
        except Exception:
            pass
    except asyncio.CancelledError:
        try:
            await bot.send_message(chat_id=ADMIN_ID, text="🔓 تم فك تعليق الإذاعة. التقدم محفوظ، تقدر تضغط «▶️ استكمال» من شاشة الإذاعة.")
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Broadcast crashed: {e}")
    finally:
        if updater:
            updater.cancel()
        BC["running"] = False
        BC["task"] = None
        BC_AUDIENCE["v"] = "all"   # نرجّع الفئة للكل بعد كل إذاعة (أمان)

async def bc_speed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    BC["lvl"] = max(0, min(len(BC_RATES) - 1, BC["lvl"] + (1 if q.data == "bc_spd_up" else -1)))
    await q.answer(f"⚡ السرعة: {BC_RATES[BC['lvl']]} رسالة/ثانية")

async def bc_unstick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    t = BC.get("task")
    if t and not t.done():
        t.cancel()
    BC.update(running=False, task=None)
    await q.answer("🔓 تم فك التعليق")

async def bc_resume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer()
        return
    S = stats.get("bc_job")
    if not S:
        await q.answer("ما فيه إذاعة غير مكتملة", show_alert=True)
        return
    await q.answer("▶️ جاري الاستكمال")
    BROADCAST_MODE["on"] = False
    _bg(_run_broadcast(context.bot, _sender_from_job(context.bot, S["job"]), S["job"], resume=S))

async def bc_watchdog_loop():
    """يفك الإذاعة تلقائياً لو ما تقدّمت 4 دقائق (بدون وجود انتظار من تيليجرام)، ويبلّغ الأدمن."""
    while True:
        await asyncio.sleep(30)
        try:
            if BC["running"] and BC.get("task") and time.time() - BC["progress"] > 240 and BC["pause_until"] < time.monotonic():
                BC["task"].cancel()
        except Exception:
            pass

async def _bc_startup_notice(bot):
    await asyncio.sleep(25)
    if stats.get("bc_job") and _bc_left() > 0:
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ فيه إذاعة غير مكتملة ({_bc_left()} متبقي من {len(stats['bc_job']['users'])}).",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ استكمال الإذاعة", callback_data="bc_resume")]]))
        except Exception:
            pass

async def _run_bc_delete(bot):
    rec = stats.get("last_broadcast") or {}
    msgs = rec.get("msgs") or {}
    if not msgs:
        await bot.send_message(chat_id=ADMIN_ID, text="ℹ️ ما فيه إذاعة محفوظة لحذفها.")
        return
    if BC["running"]:
        await bot.send_message(chat_id=ADMIN_ID, text="⚠️ فيه عملية إذاعة/حذف جارية حالياً. لو تحسها عالقة اضغط فك التعليق.", reply_markup=_bc_unstick_markup())
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
    job = {"kind": "msg", "chat": g["chat"], "ids": ids, "fwd": g["fwd"]}
    await _run_broadcast(bot, _sender_from_job(bot, job), job)

async def broadcast_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يلتقط رسائل الأدمن: إدخال لوحة التحكم (منح/إلغاء اشتراك) أو رسالة الإذاعة (تُرسل كما هي تماماً)."""
    user = update.effective_user
    m = update.effective_message
    if not user or user.id != ADMIN_ID or not m or update.effective_chat.type != "private":
        return

    # لو الأدمن أرسل "ID عدد_الأيام" مباشرة (بعد إعادة تشغيل ضيّعت الحالة، أو بدون ضغط الزر) نعتبرها منح اشتراك
    if (not ADMIN_PENDING["mode"]) and m.text and not BROADCAST_MODE["on"] \
            and re.fullmatch(r"\d{6,}\s+\d{1,4}", m.text.strip().translate(_AR_DIGITS)):
        ADMIN_PENDING["mode"] = "grant"

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
                was_active = premium_until(tid) is not None
                exp = base + timedelta(days=days)
                stats.setdefault("premium", {})[tid] = exp.isoformat()
                std = {p["days"]: k for k, p in PLANS.items()}.get(days)       # 1/7/30 = باقة قياسية، غيرها مخصّصة
                info = stats.setdefault("pro_info", {}).setdefault(tid, {})
                if not was_active or "since" not in info:
                    info["since"] = datetime.now().isoformat()
                info["plan"] = std or _plan_key_for_days(days)
                info["last"] = datetime.now().isoformat()
                info["granted"] = True
                if std: info.pop("custom_days", None)
                else: info["custom_days"] = days
                stats.setdefault("pro_reminded", {}).pop(tid, None)
                save_stats()
                label = PLANS[std]["label"] if std else f"مخصّصة ({days} يوم)"
                await m.reply_text(f"✅ تم منح Pro للمستخدم {tid}: باقة {label} (حتى {exp.strftime('%Y-%m-%d')}).")
                try:
                    await context.bot.send_message(chat_id=int(tid), parse_mode="HTML",
                        text=f"🎁 تم منحك اشتراك <b>Pro</b> — باقة <b>{label}</b>!\n📅 ينتهي: <b>{exp.strftime('%Y-%m-%d %H:%M')}</b>\nاستمتع 👑")
                except Exception:
                    pass
        elif mode == "bc_targets":
            toks = re.findall(r"\d+", m.text.translate(_AR_DIGITS))
            big = [t for t in toks if len(t) >= 6]
            if big:
                ids = list(dict.fromkeys(big))
                BC_CUSTOM["ids"] = ids
                unknown = sum(1 for i in ids if i not in stats["users"])
                note = f"\n⚠️ {unknown} منهم غير مسجلين في البوت (راح نحاول نرسل لهم)." if unknown else ""
                await m.reply_text(f"✅ تم تحديد <b>{len(ids)}</b> مستخدم.{note}\nالحين أرسل رسالة الإذاعة 👇", parse_mode="HTML")
            elif len(toks) == 1 and 0 < int(toks[0]) < 1000000:
                n = min(int(toks[0]), len(stats["users"]))
                BC_CUSTOM["ids"] = random.sample(list(stats["users"].keys()), n)
                await m.reply_text(f"✅ تم اختيار <b>{n}</b> مستخدم عشوائياً من {len(stats['users'])}.\nالحين أرسل رسالة الإذاعة 👇", parse_mode="HTML")
            else:
                ADMIN_PENDING["mode"] = "bc_targets"     # نبقى بانتظار مدخل صحيح
                await m.reply_text("⚠️ ما فهمت. أرسل ID أو عدة IDs أو رقماً صغيراً للعدد العشوائي (مثل 100).")
            raise ApplicationHandlerStop
        elif mode == "bkchan":
            v = m.text.strip().translate(_AR_DIGITS)
            if v == "0":
                set_setting("backup_chat", "")
                await m.reply_text("✅ أُلغيت قناة النسخ.")
            elif re.fullmatch(r"-?\d{5,}", v):
                try:
                    await context.bot.send_message(chat_id=int(v), text="✅ تم ربط هذه القناة لاستقبال النسخ الاحتياطية.")
                    set_setting("backup_chat", v)
                    await m.reply_text(f"✅ تم حفظ القناة {v}. النسخة القادمة ستصلها.")
                except Exception as e:
                    await m.reply_text(f"❌ ما أقدر أرسل للقناة: {str(e)[:150]}\nتأكد أن البوت مشرف فيها.")
            else:
                await m.reply_text("⚠️ أرسل ID صحيح مثل <code>-1001234567890</code>", parse_mode="HTML")
        elif mode == "revoke":
            if not nums:
                await m.reply_text("⚠️ أرسل ID المستخدم فقط.")
            elif stats.get("premium", {}).pop(nums[0], None):
                stats.get("pro_info", {}).pop(nums[0], None)
                stats.get("pro_reminded", {}).pop(nums[0], None)
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
        job = {"kind": "msg", "chat": m.chat_id, "ids": [m.message_id], "fwd": fwd}
        _bg(_run_broadcast(context.bot, _sender_from_job(context.bot, job), job))
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
        await _bc_open(msg)
        return
    if not stats["users"]:
        await msg.reply_text("❌ لا يوجد مستخدمين مسجلين في قاعدة البيانات.")
        return
    job = {"kind": "text", "text": text}
    _bg(_run_broadcast(context.bot, _sender_from_job(context.bot, job), job))

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
        [InlineKeyboardButton("💾 النسخ الاحتياطي", callback_data="adm_bk")],
    ])

def _bk_text():
    ch = str(get_setting("backup_chat") or "").strip()
    last = float(stats.get("last_backup_ts", 0))
    last_s = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M") if last else "—"
    return ("💾 <b>النسخ الاحتياطي</b>\n━━━━━━━\n"
            f"📣 قناة النسخ: <code>{ch or 'غير محددة (تُرسل لك فقط)'}</code>\n"
            f"🕒 آخر نسخة: <b>{last_s}</b>\n"
            f"👥 المستخدمون: <b>{len(stats.get('users', {}))}</b>\n"
            f"🗄 Turso: <b>{'متصل' if zen_store.TURSO_LOADED else 'غير محمّل'}</b>  |  BOOT <code>{BOOT_ID}</code>\n"
            "النسخة تُرسل تلقائياً كل 24 ساعة. أضف البوت مشرفاً في القناة.")

def _bk_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💾 نسخة الآن", callback_data="adm_bk_now")],
        [InlineKeyboardButton("📣 تعيين/تغيير قناة النسخ", callback_data="adm_bk_ch")],
        [InlineKeyboardButton("🗂 اللقطات (Turso)", callback_data="adm_bk_snaps")],
        [InlineKeyboardButton("⬅️ رجوع", callback_data="adm_home")],
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
    if d.startswith("adm_bk"):
        if d == "adm_bk":
            await _adm_edit(q, _bk_text(), _bk_markup())
        elif d == "adm_bk_now":
            ok = await send_backup(context.bot, "يدوية")
            await q.message.reply_text("✅ أُرسلت النسخة." if ok else "❌ تعذر إرسال النسخة (راجع التنبيهات).")
            await _adm_edit(q, _bk_text(), _bk_markup())
        elif d == "adm_bk_ch":
            ADMIN_PENDING["mode"] = "bkchan"
            await q.message.reply_text("📣 أرسل ID القناة (مثال: <code>-1001234567890</code>)، أو <code>0</code> لإلغاء القناة.\nلازم البوت يكون مشرفاً فيها.", parse_mode="HTML")
        elif d == "adm_bk_snaps":
            try:
                snaps = await list_snapshots(10)
            except Exception as e:
                await q.message.reply_text(f"❌ {str(e)[:150]}")
                return
            rows = [[InlineKeyboardButton(f"♻️ #{i} • {k} • {c} مستخدم • {t[:16]}", callback_data=f"adm_bk_r_{i}")] for i, k, c, t in snaps]
            rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data="adm_bk")])
            await _adm_edit(q, "🗂 اختر لقطة لدمجها (إضافي فقط، لا يُحذف شيء):", InlineKeyboardMarkup(rows))
        elif d.startswith("adm_bk_r_"):
            try:
                b, a, n = await restore_snapshot(int(d.split("_")[-1]))
                await q.message.reply_text(f"✅ تم الدمج\n👥 قبل: {b}\n➕ جدد: {a}\n👥 الآن: {n}")
            except Exception as e:
                await q.message.reply_text(f"❌ {str(e)[:150]}")
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
        await _bc_open(q.message)
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

def _blocking_get_thumb_info(url):
    """مثل _blocking_get_thumbnail لكن يرجّع أيضاً مدة المقطع (نفس الطلب، بدون كلفة إضافية)."""
    opts = {
        'quiet': True, 'no_warnings': True, 'cookiefile': COOKIES_FILE, 'proxy': PROXY_URL,
        'skip_download': True, 'socket_timeout': 15,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get('thumbnail'), info.get('duration')

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

# ---- سناب شات وأمثاله: روابط CDN تنتهي بامتداد غريب (مثل .IRZXSOY) فيرفضها yt-dlp "لأسباب أمنية" ----
_UNUSUAL_EXT_RE = re.compile(r"extension \('([^']{1,24})'\) is unusual")
_SAFE_OUT_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".mp3", ".m4a", ".ogg", ".opus", ".jpg", ".jpeg", ".png", ".webp", ".gif"}

def _allow_extension(ext):
    """نسمح بهذا الامتداد المحدد فقط (أحرف وأرقام قصيرة) بدل إيقاف حماية yt-dlp بالكامل."""
    try:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,24}", ext):
            return False
        from yt_dlp.utils._utils import _UnsafeExtensionError as _U
        _U.ALLOWED_EXTENSIONS = frozenset(set(_U.ALLOWED_EXTENSIONS) | {ext, ext.lower()})
        return True
    except Exception as e:
        logger.error(f"allow_extension failed: {e}")
        return False

def _normalize_media_ext(path, opts):
    """الملف الفعلي فيديو عادي حتى لو امتداده غريب: نعيد تسميته .mp4 ليرسله تيليجرام كفيديو."""
    try:
        if opts.get("postprocessors"):        # الصوت: الملف الأصلي يُحذف بعد التحويل
            return path
        if path and os.path.exists(path):
            root, ext = os.path.splitext(path)
            if ext.lower() not in _SAFE_OUT_EXTS:
                new_path = root + ".mp4"
                os.replace(path, new_path)
                return new_path
    except Exception as e:
        logger.error(f"normalize ext failed: {e}")
    return path

def _blocking_download(url, opts):
    def _run(o):
        with YoutubeDL(o) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    try:
        path = _run(opts)
    except Exception as e:
        m = _UNUSUAL_EXT_RE.search(str(e))
        if not (m and _allow_extension(m.group(1))):
            raise
        logger.info(f"امتداد غير معتاد ({m.group(1)}) - إعادة المحاولة مع السماح به")
        retry = dict(opts)
        if not retry.get("postprocessors"):
            retry["format"] = "best"          # مرشّحات الصيغة (ext=mp4) ما تناسب الامتداد الغريب
        path = _run(retry)
    return _normalize_media_ext(path, opts)

def _get_urllib_opener():
    """يبني opener يستخدم البروكسي لو معرّف (PROXY_URL)، وإلا opener عادي."""
    if PROXY_URL:
        proxy_handler = urllib.request.ProxyHandler({'http': PROXY_URL, 'https': PROXY_URL})
        return urllib.request.build_opener(proxy_handler)
    return urllib.request.build_opener()

# ================== استقبال الرسائل والبدء ==================
# ================== التطبيق المصغر (Mini App) + شرح الاستخدام ==================
def _app_url():
    return webapp_api.app_url() if webapp_api else ""

def _app_row(text="🚀 فتح تطبيق ZenDown"):
    """صف زر فتح التطبيق (فارغ لو الرابط غير معروف، فلا يظهر زر معطّل)."""
    u = _app_url()
    if not u:
        return []
    return [InlineKeyboardButton(text, web_app=WebAppInfo(url=u), style="primary")]

def _start_markup():
    rows = [
        [_btn("📱 إنشاء QR", "mode_qr", "sec"), _btn("🔤 استخراج النص من الصور", "mode_ocr", "sec")],
        [_btn("📥 تحميل شامل", "mode_dl", "main")],
    ]
    app = _app_row()
    if app:
        rows.append(app)
    rows.append([InlineKeyboardButton("📖 كيف أستخدم البوت؟", callback_data="how_1")])
    return InlineKeyboardMarkup(rows)

HOW_STEPS = {
    1: ("📥 <b>١/٣ — التحميل</b>\n\n"
        "انسخ رابط أي مقطع (تيك توك، إنستغرام، فيسبوك، X، سناب، بينترست) وأرسله هنا في المحادثة.\n"
        "اختر <b>فيديو</b> أو <b>صوت MP3</b> أو <b>صورة</b>، ويصلك الملف جاهزاً خلال لحظات."),
    2: ("🎬 <b>٢/٣ — تعديل المقطع</b>\n\n"
        "بعد التحميل اضغط زر التعديل لإضافة <b>فلتر</b>، أو <b>قص</b> جزء، أو تغيير <b>السرعة</b>، أو تحويل المقطع <b>عمودي/عرضي</b>.\n"
        "لديك تجارب مجانية، وبعدها يكون التعديل لمشتركي Pro 👑."),
    3: ("🚀 <b>٣/٣ — تطبيق ZenDown</b>\n\n"
        "تطبيق صغير داخل تيليجرام بتصميم أوضح: الصق الرابط واختر الصيغة، وتابع <b>اشتراكك</b> وتجدده بنجوم تيليجرام ⭐ من مكان واحد.\n"
        "ما فيه تسجيل ولا تحميل — يفتح بضغطة."),
}

def _how_markup(step):
    rows = []
    nav = []
    if step > 1:
        nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"how_{step-1}"))
    if step < 3:
        nav.append(InlineKeyboardButton("التالي ▶️", callback_data=f"how_{step+1}"))
    if nav:
        rows.append(nav)
    if step == 3:
        app = _app_row("🚀 افتح التطبيق الآن")
        if app:
            rows.append(app)
    return InlineKeyboardMarkup(rows) if rows else None

async def how_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        step = int(q.data.split("_")[1])
    except Exception:
        step = 1
    step = min(max(step, 1), 3)
    try:
        await q.message.edit_text(HOW_STEPS[step], parse_mode="HTML", reply_markup=_how_markup(step))
    except Exception as e:
        if "not modified" not in str(e).lower():
            await q.message.reply_text(HOW_STEPS[step], parse_mode="HTML", reply_markup=_how_markup(step))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    track_user_activity(user.id)
    await update.message.reply_text(HOW_STEPS[1], parse_mode="HTML", reply_markup=_how_markup(1))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    is_new = str(user.id) not in stats["users"]      # مستخدم جديد كلياً = يظهر له الشرح مرة واحدة
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        await _ask_subscribe(update.message)
        return

    # رابط دخول مباشر (Deep Link): https://t.me/ZenDown_Bot?start=mystats
    if context.args and context.args[0] == "mystats":
        await show_my_stats_command(update, context)
        return
    if context.args and context.args[0] == "help":
        await help_command(update, context)
        return
    if context.args and context.args[0] == "paysupport":
        await paysupport_command(update, context)
        return

    import html as _html
    await update.message.reply_text(
        f"أهلاً بك <b>{_html.escape(user.first_name or 'صديقنا')}</b> في @ZenDown_Bot 🚀\n\n"
        "📥 أرسل رابط أي مقطع وسأحمّله لك مباشرة.\n"
        "أو اختر خدمة إضافية من الأزرار 👇",
        parse_mode="HTML", reply_markup=_start_markup())
    if is_new:
        try:
            await update.message.reply_text(HOW_STEPS[1], parse_mode="HTML", reply_markup=_how_markup(1))
        except Exception as e:
            logger.info(f"intro tour not sent to {user.id}: {e}")

async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أزرار رسالة الترحيب: QR / استخراج النص / التحميل الشامل."""
    q = update.callback_query
    uid = q.from_user.id
    await q.answer()
    track_user_activity(uid)
    if not await check_user_subscription(context.bot, uid):
        await _ask_subscribe(q.message)
        return
    QR_MODE_USERS.discard(uid)
    OCR_MODE_USERS.discard(uid)
    TRIM_PENDING.pop(uid, None)
    SPEED_PENDING.pop(uid, None)
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
        await _ask_subscribe(m)
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
        await _ask_subscribe(update.message)
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

    # شاشة السرعة مفتوحة: أي رقم يرسله المستخدم يثبّت السرعة (حرية كاملة بين SPEED_MIN و SPEED_MAX)
    if user.id in SPEED_PENDING and not text.startswith("http"):
        pend = SPEED_PENDING[user.id]
        sid = pend["sid"]
        ref = pend.get("msg")
        val, err = _parse_speed(text)
        if not err:
            _edit_get(user.id, sid)["s"] = val
        try:
            await update.message.delete()
        except Exception:
            pass
        txt = _speed_text(user.id, sid, err)
        mk = _speed_markup(user.id, sid)
        try:
            if ref:
                await context.bot.edit_message_text(chat_id=ref[0], message_id=ref[1], text=txt, parse_mode="HTML", reply_markup=mk)
            else:
                raise Exception("no ref")
        except Exception as e:
            if "not modified" not in str(e).lower():
                await context.bot.send_message(chat_id=update.effective_chat.id, text=txt, parse_mode="HTML", reply_markup=mk)
        return

    # وضع القص: إدخال سهل خطوة بخطوة. كل الردود تُعدَّل في نفس رسالة القائمة وتُحذف رسالة المستخدم (شات نظيف)
    if user.id in TRIM_PENDING and not text.startswith("http"):
        pend = TRIM_PENDING[user.id]
        sid = pend["sid"]
        ref = pend.get("msg")

        async def _cut_ui(txt, markup):
            try:
                await update.message.delete()
            except Exception:
                pass
            if ref:
                try:
                    await context.bot.edit_message_text(chat_id=ref[0], message_id=ref[1], text=txt, parse_mode="HTML", reply_markup=markup)
                    return
                except Exception as e:
                    if "not modified" in str(e).lower():
                        return
            await context.bot.send_message(chat_id=update.effective_chat.id, text=txt, parse_mode="HTML", reply_markup=markup)

        toks = _time_tokens(text)
        if not toks:
            await _cut_ui(_cut_text("ما فهمت 😅 أرسل رقم بسيط مثل 10 أو 1:05", pend["start"]), _cut_markup(sid))
            return
        if pend["start"] is None and len(toks) == 1:
            pend["start"] = toks[0]
            await _cut_ui(_cut_text(None, toks[0]), _cut_markup(sid))
            return
        s_t, e_t = (toks[0], toks[1]) if (pend["start"] is None) else (pend["start"], toks[0])
        if e_t <= s_t:
            pend["start"] = None if len(toks) >= 2 else pend["start"]
            await _cut_ui(_cut_text(f"النهاية لازم تكون بعد البداية ({_fmt(s_t)}). أرسل وقت النهاية من جديد.", pend["start"]), _cut_markup(sid))
            return
        if e_t - s_t > TRIM_MAX_SECONDS:
            await _cut_ui(_cut_text(f"أقصى مدة للقص {TRIM_MAX_SECONDS} ثانية، وأنت اخترت {e_t - s_t}. أرسل وقت النهاية من جديد.", pend["start"]), _cut_markup(sid))
            return
        _edit_get(user.id, sid)["c"] = (s_t, e_t)
        TRIM_PENDING.pop(user.id, None)
        await _cut_ui(_edit_menu_text(user.id, sid), _edit_menu_markup(user.id, sid))
        return
    TRIM_PENDING.pop(user.id, None)
    SPEED_PENDING.pop(user.id, None)

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
    _bg(url_put(sid, url))

    caption = LINK_CAPTION
    markup = _link_markup(sid)

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
    "maint": False, "backup_chat": "",
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
    "vintage": ("📼 قديم", "curves=preset=vintage,eq=saturation=0.85,noise=alls=8:allf=t,vignette=PI/4"),
    "mirror":  ("🪞 انعكاس (قلب أفقي)", "hflip"),
    "cine":    ("🎞 سينمائي", "colorbalance=rs=-.12:gs=-.03:bs=.15:rh=.2:bh=-.15,eq=contrast=1.2:saturation=1.2,vignette=PI/6,drawbox=x=0:y=0:w=iw:h=ih/10:color=black:t=fill,drawbox=x=0:y=ih*9/10:w=iw:h=ih/10:color=black:t=fill"),
    "sharp":   ("🔍 حاد", "unsharp=7:7:2.5:7:7:1.0,eq=contrast=1.15:saturation=1.15"),
    "golden":  ("🌅 ساعة ذهبية", "colorbalance=rs=.25:gs=.1:bs=-.3:rm=.15:bm=-.15,eq=brightness=0.04:saturation=1.4"),
    "ice":     ("🧊 جليدي", "colorbalance=rs=-.25:bs=.3:bm=.15,eq=saturation=0.8:brightness=0.04:contrast=1.1"),
}
FILTERS_PER_PAGE = 6
SPEED_FAST = ["1.1", "1.2", "1.3"]    # أزرار التسريع الرسمية
SPEED_SLOW = ["0.9", "0.8", "0.7"]    # أزرار الإبطاء الرسمية
SPEEDS = SPEED_FAST + SPEED_SLOW
SPEED_MIN, SPEED_MAX = 0.25, 4.0      # نطاق السرعة الحرة (بالنص)
SPEED_PENDING = {}                    # user_id -> {"sid", "msg": (chat_id, message_id)} لما تكون شاشة السرعة مفتوحة
ORIENT = {"v": ("📱 عمودي 9:16", 720, 1280), "h": ("🖥 عرضي 16:9", 1280, 720)}
EDIT_STATE = {}     # f"{user_id}:{sid}" -> {"f": فلتر, "c": (بداية, نهاية), "s": سرعة, "p": تغيير النبرة, "o": v/h}
TRIM_PENDING = {}   # user_id -> {"sid": ..., "start": None أو ثواني, "msg": (chat_id, message_id)}
THUMB_CACHE = BoundedCache(max_size=60)   # sid -> bytes (صورة المعاينة)
DUR_CACHE = BoundedCache(max_size=200)    # sid -> مدة المقطع بالثواني (للتطبيق المصغر)

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

# ---------- معلومات اشتراك Pro (الباقة + تاريخ البدء) وتذكير التجديد ----------
PRO_REMIND_BEFORE = {"daily": timedelta(hours=3), "weekly": timedelta(hours=24), "monthly": timedelta(hours=48)}

def _pro_plan_of(uid):
    """نوع باقة المشترك. المشتركون القدامى (قبل تسجيل الباقة) يُعتبرون شهري."""
    p = (stats.get("pro_info", {}).get(str(uid)) or {}).get("plan")
    return p if p in PLANS else "monthly"

def _plan_label(uid):
    """اسم الباقة للعرض: الحقيقي من التسجيل، أو «مخصّصة» للمنح بأيام غير قياسية، أو تقديري للمشتركين القدامى."""
    info = stats.get("pro_info", {}).get(str(uid)) or {}
    if info.get("custom_days"):
        return f"مخصّصة ({info['custom_days']} يوم)"
    lab = PLANS[_pro_plan_of(uid)]["label"]
    return lab if info.get("plan") in PLANS else lab + " (تقديري)"

def _plan_key_for_days(days):
    """أقرب باقة لعدد أيام المنحة (للتذكير وزر التجديد)."""
    return min(PLANS, key=lambda k: abs(PLANS[k]["days"] - days))

def _remaining_text(exp):
    left = exp - datetime.now()
    if left.total_seconds() <= 0:
        return "انتهى"
    d, rem = left.days, left.seconds
    h, m = rem // 3600, (rem % 3600) // 60
    if d > 0:
        return f"{d} يوم و{h} ساعة"
    if h > 0:
        return f"{h} ساعة و{m} دقيقة"
    return f"{m} دقيقة"

def _pro_status_block(uid):
    """سطور حالة Pro للمشتركين فقط (تظهر في /mystats). فارغة لغير المشترك."""
    exp = premium_until(uid)
    if not exp:
        return ""
    info = stats.get("pro_info", {}).get(str(uid)) or {}
    plan_key = _pro_plan_of(uid)
    approx = ""
    try:
        since = datetime.fromisoformat(info["since"])
    except Exception:
        since = exp - timedelta(days=PLANS[plan_key]["days"])     # مشترك قديم: تقدير تقريبي
        approx = "≈ "
    return (
        "👑 <b>اشتراك Pro</b>\n"
        f"▫️ الباقة: <b>{_plan_label(uid)}</b>\n"
        f"▫️ بدأ: <b>{approx}{since.strftime('%Y-%m-%d')}</b>\n"
        f"▫️ ينتهي: <b>{exp.strftime('%Y-%m-%d %H:%M')}</b>\n"
        f"▫️ المتبقي: <b>{_remaining_text(exp)}</b>\n"
        "───────────────\n"
    )

async def _send_renew_reminders(bot):
    """يرسل تذكير التجديد (مرة واحدة لكل موعد انتهاء) قبل الانتهاء بفترة بسيطة حسب نوع الباقة."""
    now = datetime.now()
    reminded = stats.setdefault("pro_reminded", {})
    sent = 0
    for uid, exp_iso in list(stats.get("premium", {}).items()):
        try:
            exp = datetime.fromisoformat(exp_iso)
        except Exception:
            continue
        left = exp - now
        plan_key = _pro_plan_of(uid)
        if left.total_seconds() <= 0 or left > PRO_REMIND_BEFORE[plan_key] or reminded.get(uid) == exp_iso:
            continue
        reminded[uid] = exp_iso
        plan = PLANS[plan_key]
        try:
            await bot.send_message(
                chat_id=int(uid), parse_mode="HTML",
                text=(f"⏰ <b>اشتراكك في ZenDown Pro على وشك الانتهاء</b>\n\n"
                      f"باقتك: <b>{_plan_label(uid)}</b>\n"
                      f"📅 ينتهي: <b>{exp.strftime('%Y-%m-%d %H:%M')}</b> (المتبقي: {_remaining_text(exp)})\n\n"
                      "جدّد الآن بضغطة واحدة وخلّ مزاياك مستمرة بدون انقطاع:\n"
                      "🚀 تخطي الطابور • 🎬 تعديل المقطع\n\n"
                      "التجديد يُضاف لمدتك الحالية، ما تخسر أي وقت متبقي 👇"),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    f"🔄 تجديد الباقة — {plan['stars']} ⭐", callback_data=f"buy_{plan_key}", style="success")]]))
            sent += 1
        except Exception as e:
            logger.info(f"renew reminder not delivered to {uid}: {e}")
        await asyncio.sleep(0.1)
    if sent or reminded:
        save_stats()
    if sent:
        await turso_push_now(force=True)
    return sent

async def pro_reminder_loop(bot):
    await asyncio.sleep(90)
    while True:
        try:
            await _send_renew_reminders(bot)
        except Exception as e:
            logger.error(f"pro_reminder_loop failed: {e}")
        await asyncio.sleep(1800)

def premium_until_before(base, uid):
    """True لو كان للمستخدم اشتراك فعّال لحظة الدفع (يعني تجديد/تمديد، فنحافظ على تاريخ البدء الأصلي)."""
    try:
        return base > datetime.now() + timedelta(seconds=5)
    except Exception:
        return False

def _plans_text(user_id) -> str:
    until = premium_until(user_id)
    status = f"✅ اشتراكك فعّال حتى <b>{until.strftime('%Y-%m-%d %H:%M')}</b>\n\n" if until else ""
    return (
        "👑 <b>ZenDown Pro</b>\n"
        "━━━━━━━\n\n"
        f"{status}"
        "البوت يبقى <b>مجاني بالكامل</b> كما هو، وPro إضافة اختيارية لمن يبي مزايا أكثر:\n\n"
        "🚀 <b>تخطي الطابور</b> — ما يُرفض طلبك وقت الازدحام\n"
        f"🎬 <b>تعديل المقطع</b> — فلاتر + قص + سرعة + اتجاه (عمودي/عرضي) في ملف واحد\n"
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
    rows = [
        [InlineKeyboardButton(f"🔥 شهري — {PLANS['monthly']['stars']} ⭐", callback_data="buy_monthly", style="primary")],
        [InlineKeyboardButton(f"أسبوعي — {PLANS['weekly']['stars']} ⭐", callback_data="buy_weekly"),
         InlineKeyboardButton(f"يومي — {PLANS['daily']['stars']} ⭐", callback_data="buy_daily")],
    ]
    app = _app_row("🚀 افتح التطبيق")
    if app:
        rows.append(app)
    return InlineKeyboardMarkup(rows)

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
            description=f"اشتراك Pro لمدة {plan['days']} يوم: تخطي الطابور + تعديل المقطع (فلاتر، قص، سرعة، اتجاه).",
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
        await _ask_subscribe(update.message)
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
_EDIT_DEFAULT = {"f": None, "c": None, "s": None, "p": True, "o": None}   # تغيير النبرة مفعّل افتراضياً

def _edit_get(uid, sid):
    k = f"{uid}:{sid}"
    if k not in EDIT_STATE:
        if len(EDIT_STATE) > 400:
            EDIT_STATE.pop(next(iter(EDIT_STATE)))
        EDIT_STATE[k] = dict(_EDIT_DEFAULT)
    st = EDIT_STATE[k]
    for kk, vv in _EDIT_DEFAULT.items():
        st.setdefault(kk, vv)
    return st

def _ori_graph(kind):
    """يحوّل المقطع لعمودي/عرضي مع خلفية ضبابية (الخلفية تُصغَّر ثم تُكبَّر = ضبابية رخيصة على المعالج)."""
    _, W, H = ORIENT[kind]
    sw, sh = W // 10, H // 10
    return (f"split[oa][ob];[oa]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},boxblur=2:1,scale={W}:{H}[obg];"
            f"[ob]scale={W}:{H}:force_original_aspect_ratio=decrease[ofg];[obg][ofg]overlay=(W-w)/2:(H-h)/2")

def _edit_vf(st):
    """سلسلة الفلاتر النهائية (اتجاه ← فلتر ← سرعة). None لو ما فيه شي يحتاج إعادة ترميز."""
    parts = []
    if st.get("o") in ORIENT:
        parts.append(_ori_graph(st["o"]))
    if st.get("f") in FILTERS:
        parts.append(FILTERS[st["f"]][1])
    if st.get("s"):
        parts.append(f"setpts=PTS/{st['s']}")
    return ",".join(parts) or None

def _audio_filter(spd, pitch):
    spd = float(spd)
    if pitch:     # تغيير النبرة مع السرعة (إبطاء = غليظ، تسريع = رفيع) مثل كاب كات
        return f"aresample=44100,asetrate=44100*{spd},aresample=44100"
    chain, r = [], spd      # نبرة ثابتة (atempo يقبل 0.5 إلى 2 للمرحلة الواحدة)
    while r > 2.0:
        chain.append("atempo=2.0"); r /= 2.0
    while r < 0.5:
        chain.append("atempo=0.5"); r /= 0.5
    chain.append(f"atempo={r:.4f}")
    return ",".join(chain)

def _has_edit(st):
    return bool(st.get("f") or st.get("c") or st.get("s") or st.get("o"))

def _edit_menu_text(uid, sid):
    st = _edit_get(uid, sid)
    flt = FILTERS[st["f"]][0] if st["f"] else "بدون"
    c = st["c"]
    cut = f"{_fmt(c[0])} ← {_fmt(c[1])} ({c[1] - c[0]} ث)" if c else "بدون"
    spd = f"{st['s']}x · {'🎚 تغيير النبرة' if st['p'] else '🎙 صوت طبيعي'}" if st["s"] else "بدون"
    ori = ORIENT[st["o"]][0] if st["o"] in ORIENT else "الأصلي"
    note = f"\n<i>مع الفلتر/السرعة/الاتجاه يكون الناتج حتى {FILTER_MAX_SECONDS} ثانية</i>" if (st["f"] or st["s"] or st["o"]) else ""
    return (
        "🎬 <b>تعديل المقطع</b>\n━━━━━━━\n"
        f"🎨 الفلتر: <b>{flt}</b>\n"
        f"✂️ القص: <b>{cut}</b>\n"
        f"⏩ السرعة: <b>{spd}</b>\n"
        f"📐 الاتجاه: <b>{ori}</b>{note}\n\n"
        f"{_trial_line(uid)}\n\n"
        "اختر ما تبيه، ثم اضغط <b>تطبيق وإرسال</b> 👇"
    )

def _edit_menu_markup(uid, sid):
    st = _edit_get(uid, sid)
    rows = [
        [_btn("🎨 الفلتر" if not st["f"] else "🎨 تغيير الفلتر", f"ed_fl_{sid}", "main"),
         _btn("✂️ القص" if not st["c"] else "✂️ تغيير القص", f"ed_cut_{sid}", "main")],
        [_btn("⏩ السرعة" if not st["s"] else "⏩ تغيير السرعة", f"ed_sp_{sid}", "main"),
         _btn("📐 الاتجاه" if not st["o"] else "📐 تغيير الاتجاه", f"ed_or_{sid}", "main")],
    ]
    if _has_edit(st):
        rows.append([InlineKeyboardButton("✅ تطبيق وإرسال", callback_data=f"ed_go_{sid}", style="success")])
        rows.append([InlineKeyboardButton("🗑 مسح التعديلات", callback_data=f"ed_clr_{sid}")])
    rows.append([InlineKeyboardButton("↩️ رجوع للتحميل", callback_data=f"ed_home_{sid}")])
    return InlineKeyboardMarkup(rows)

def _link_markup(sid):
    return InlineKeyboardMarkup([
        [_btn("🎥 فيديو MP4", f"down_vid_{sid}", "main")],
        [_btn("🎵 صوت MP3", f"down_aud_{sid}", "sec"),
         _btn("🖼 صورة", f"down_img_{sid}", "sec")],
        [_btn("📝 نسخ الوصف", f"down_cap_{sid}", "sec")],
        [_btn("تعديل المقطع 🎬", f"ed_open_{sid}", "main")]
    ])

LINK_CAPTION = "🎬 <b>رابط جاهز للتحميل</b>"

async def _show(q, text, markup, photo=None):
    """يعرض الشاشة التالية في نفس الرسالة (تعديل مكانها). مع الصور: تُحذف الرسالة وتحل مكانها الجديدة،
    ومن صورة لصورة نعدّلها مباشرة. هكذا يبقى الشات نظيفاً برسالة واحدة."""
    from telegram import InputMediaPhoto
    msg = q.message
    bot = q.get_bot()
    try:
        if photo is None:
            if msg.photo:
                try: await msg.delete()
                except Exception: pass
                await bot.send_message(chat_id=msg.chat_id, text=text, parse_mode="HTML", reply_markup=markup)
            else:
                await msg.edit_text(text, parse_mode="HTML", reply_markup=markup)
        else:
            if msg.photo:
                await msg.edit_media(InputMediaPhoto(media=photo, caption=text, parse_mode="HTML"), reply_markup=markup)
            else:
                try: await msg.delete()
                except Exception: pass
                await bot.send_photo(chat_id=msg.chat_id, photo=photo, caption=text, parse_mode="HTML", reply_markup=markup)
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        logger.error(f"_show failed: {e}")
        try:
            if photo is None:
                await bot.send_message(chat_id=msg.chat_id, text=text, parse_mode="HTML", reply_markup=markup)
            else:
                await bot.send_photo(chat_id=msg.chat_id, photo=photo, caption=text, parse_mode="HTML", reply_markup=markup)
        except Exception as e2:
            logger.error(f"_show fallback failed: {e2}")

def _filters_page_count():
    return (len(FILTERS) + FILTERS_PER_PAGE - 1) // FILTERS_PER_PAGE

def _filters_text(page):
    return (f"🎨 <b>الفلاتر</b> — صفحة {page + 1}/{_filters_page_count()}\n"
            "اضغط على فلتر لمعاينته على صورة من المقطع 👇")

def _filters_markup(sid, page=0):
    keys = list(FILTERS.keys())
    n = _filters_page_count()
    page = max(0, min(page, n - 1))
    chunk = keys[page * FILTERS_PER_PAGE:(page + 1) * FILTERS_PER_PAGE]
    rows = []
    for i in range(0, len(chunk), 2):
        rows.append([InlineKeyboardButton(FILTERS[k][0], callback_data=f"ed_p_{k}_{sid}") for k in chunk[i:i + 2]])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("‹ السابق", callback_data=f"ed_pg_{page - 1}_{sid}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{n}", callback_data=f"ed_pg_{page}_{sid}"))
    if page < n - 1:
        nav.append(InlineKeyboardButton("التالي ›", callback_data=f"ed_pg_{page + 1}_{sid}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"ed_menu_{sid}")])
    return InlineKeyboardMarkup(rows)

def _parse_speed(text):
    """يفهم سرعة مكتوبة بحرية: 1.5 / 2x / x3 / ٢ / ١٫٥ / 1,5. يرجّع (قيمة نصية أو None للعادية، رسالة خطأ)."""
    t = (text or "").strip().lower()
    t = t.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫،,×", "0123456789...x"))
    m = re.fullmatch(r"x?\s*(\d+(?:\.\d+)?)\s*x?", t)
    if not m:
        return None, "أرسل رقماً فقط، مثال: 1.5 أو 2 أو 0.75"
    v = round(float(m.group(1)), 2)
    if v < SPEED_MIN or v > SPEED_MAX:
        return None, f"السرعة لازم تكون بين {SPEED_MIN:g} و{SPEED_MAX:g}"
    return (None if v == 1 else f"{v:g}"), None

def _speed_text(uid, sid, note=None):
    st = _edit_get(uid, sid)
    cur = f"{st['s']}x" if st["s"] else "عادية 1x"
    warn = f"\n⚠️ {note}\n" if note else ""
    return (
        "⏩ <b>السرعة</b>\n━━━━━━━\n"
        f"السرعة الحالية: <b>{cur}</b>\n"
        f"✍️ اختر من الأزرار، أو <b>أرسل رقماً</b> بحرية (مثال: <code>1.75</code>) من {SPEED_MIN:g} إلى {SPEED_MAX:g}\n{warn}\n"
        "🎙 <b>صوت طبيعي:</b> الصوت يتسارع/يتباطأ وتبقى نبرته كما هي\n"
        "🎚 <b>تغيير النبرة:</b> مع الإبطاء يصير الصوت غليظاً وفخماً، ومع التسريع خفيفاً ورفيعاً (مثل كاب كات)\n"
        f"<i>الناتج حتى {FILTER_MAX_SECONDS} ثانية.</i>"
    )

def _speed_markup(uid, sid):
    st = _edit_get(uid, sid)
    def sb(v):
        lab, on = ("🐢 " if float(v) < 1 else "🐇 ") + f"{v}x", st["s"] == v
        return InlineKeyboardButton(("✅ " if on else "") + lab, callback_data=f"ed_sv_{v}_{sid}")
    rows = [[sb(v) for v in SPEED_FAST], [sb(v) for v in SPEED_SLOW]]
    rows.append([InlineKeyboardButton(("✅ " if not st["p"] else "") + "🎙 صوت طبيعي", callback_data=f"ed_pit_0_{sid}"),
                 InlineKeyboardButton(("✅ " if st["p"] else "") + "🎚 تغيير النبرة", callback_data=f"ed_pit_1_{sid}")])
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"ed_menu_{sid}")])
    return InlineKeyboardMarkup(rows)

def _ori_text(uid, sid):
    st = _edit_get(uid, sid)
    cur = ORIENT[st["o"]][0] if st["o"] in ORIENT else "الأصلي"
    return (
        "📐 <b>اتجاه المقطع</b>\n━━━━━━━\n"
        f"الحالي: <b>{cur}</b>\n\n"
        "نحوّل المقطع إلى عمودي (ستوري/ريلز) أو عرضي، مع خلفية ضبابية بدل الأطراف السوداء.\n"
        "اضغط على اتجاه لمعاينته على صورة من المقطع 👇"
    )

def _ori_markup(uid, sid):
    st = _edit_get(uid, sid)
    rows = [[InlineKeyboardButton(ORIENT[k][0], callback_data=f"ed_op_{k}_{sid}") for k in ("v", "h")]]
    if st["o"]:
        rows.append([InlineKeyboardButton("⬜ الأصلي (إلغاء التحويل)", callback_data=f"ed_oc_n_{sid}")])
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"ed_menu_{sid}")])
    return InlineKeyboardMarkup(rows)

def _cut_text(note=None, start=None):
    head = "✂️ <b>قص الفيديو</b>\n\n"
    if start is not None:
        body = f"✅ البداية: <b>{_fmt(start)}</b>\nالحين أرسل <b>وقت النهاية</b> (مثال: <code>{start + 30}</code>)\n"
    else:
        body = ("اختر قصاً سريعاً من الأزرار، أو أرسل <b>وقت البداية</b> برقم بسيط (مثال: <code>10</code> أو <code>1:05</code>)، "
                "وبعدها أرسل <b>وقت النهاية</b>.\n")
    warn = f"\n⚠️ {note}\n" if note else ""
    return f"{head}{body}{warn}\n<i>أقصى مدة للقص: {TRIM_MAX_SECONDS} ثانية.</i>"

def _cut_markup(sid):
    quick = [InlineKeyboardButton(f"⏱ أول {n} ث", callback_data=f"ed_q_{n}_{sid}") for n in (15, 30, 60) if n <= TRIM_MAX_SECONDS]
    rows = [quick] if quick else []
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=f"ed_menu_{sid}")])
    return InlineKeyboardMarkup(rows)

async def _get_thumb(sid, url):
    img = THUMB_CACHE.get(sid)
    if img:
        return img
    dur = None
    if _is_tiktok(url):
        async with TIKTOK_INFO_SEM:
            _tinfo = await run_isolated("info", url, _tt_info_opts())
        thumb_url, dur = _tinfo.get("thumbnail"), _tinfo.get("duration")
    else:
        thumb_url, dur = await asyncio.wait_for(run_blocking(_blocking_get_thumb_info, url), timeout=30)
    if not thumb_url:
        raise Exception("no thumbnail")
    img = await asyncio.wait_for(run_blocking(_blocking_fetch_bytes, thumb_url), timeout=20)
    THUMB_CACHE[sid] = img
    try:
        if dur:
            DUR_CACHE[sid] = float(dur)
    except Exception:
        pass
    return img

async def _pro_upsell_apply(q):
    """يظهر لغير المشترك بعد انتهاء التجارب المجانية: مختصر + الباقات."""
    total = int(get_setting("free_trials"))
    head = (f"🔒 <b>انتهت تجاربك المجانية</b> ({total} من {total})" if total > 0
            else "👑 <b>استلام الفيديو المعدّل متاح لمشتركي Pro</b>")
    await q.message.reply_text(
        f"{head}\n\n"
        "مع Pro تحصل على:\n"
        "🎬 فلاتر + قص + سرعة + اتجاه في ملف واحد\n"
        "🚀 تخطي الطابور\n"
        "👑 شارة Pro\n\n"
        "اختر باقتك 👇",
        parse_mode="HTML", reply_markup=_plans_markup())

# ---------- أدوات ffmpeg ----------
async def _ffmpeg_exec(args, timeout):
    _nice = ["nice", "-n", "10"] if shutil.which("nice") else []     # أولوية أقل: ffmpeg ما يخنق ردود البوت
    proc = await asyncio.create_subprocess_exec(
        *_nice, "ffmpeg", "-y", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try: proc.kill()
        except Exception: pass
        raise
    if proc.returncode != 0:
        logger.error(f"ffmpeg failed: {(_err or b'')[-300:].decode(errors='ignore')}")
    return proc.returncode == 0

async def _ffmpeg_edit(src, dst, cut, vf, speed=None, pitch=False, has_ori=False):
    """يطبّق القص/الفلتر/السرعة/الاتجاه في خطوة واحدة. القص وحده سريع (بدون إعادة ترميز)،
    ومع أي شي ثاني نعيد الترميز بإعدادات خفيفة (ultrafast، 720p، والناتج حتى FILTER_MAX_SECONDS)."""
    start = cut[0] if cut else 0
    dur = (cut[1] - cut[0]) if cut else None
    if not vf:
        args = ["-ss", str(start), "-i", src] + (["-t", str(dur)] if dur else []) + \
               ["-c", "copy", "-avoid_negative_ts", "make_zero", dst]
        ok = await _ffmpeg_exec(args, timeout=60)
    else:
        spd = float(speed) if speed else 1.0
        max_in = FILTER_MAX_SECONDS * spd            # مدة الدخل التي تعطي ناتجاً ≤ الحد
        d_in = min(dur, max_in) if dur else max_in
        _cap = 720 if d_in <= 20 else 540          # مقاطع أطول = دقة أقل = ملف أصغر ومعالجة أسرع
        vchain = vf if has_ori else f"{vf},scale=-2:'min({_cap},trunc(ih/2)*2)'"
        args = ["-ss", str(start), "-t", f"{d_in:.2f}", "-i", src, "-vf", vchain]
        if speed:
            args += ["-af", _audio_filter(speed, pitch)]
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "31", "-threads", "1",
                 "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", dst]
        ok = await _ffmpeg_exec(args, timeout=180)
    return ok and os.path.exists(dst) and os.path.getsize(dst) > 0

# ================== زر «إزالة حقوق النشر» تحت كل فيديو: يفتح نموذج تعديل الفيديو ==================
TPL_BTN_LABEL = "إزالة حقوق النشر 🧹"

def _tpl_markup(sid):
    u = webapp_api.app_url(sid) if webapp_api else ""
    if u:     # يفتح لوحة التعديل في التطبيق المصغر مباشرة على هذا المقطع
        return InlineKeyboardMarkup([[InlineKeyboardButton(TPL_BTN_LABEL, web_app=WebAppInfo(url=u), style="success")]])
    return InlineKeyboardMarkup([[InlineKeyboardButton(TPL_BTN_LABEL, callback_data=f"ed_ovid_{sid}", style="success")]])

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

# ---------- معالج أزرار تعديل المقطع (كل شي في رسالة واحدة تتعدّل مكانها) ----------
async def edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    if get_setting("maint") and uid != ADMIN_ID:
        await q.answer("🔧 البوت تحت الصيانة حالياً", show_alert=True)
        return
    parts = q.data.split("_")          # ed_<action>[_<arg>]_<sid>
    action, sid = parts[1], parts[-1]
    arg = parts[2] if len(parts) == 4 else None
    url = await get_session_url(sid)
    if not url:
        await q.answer("انتهت صلاحية الجلسة، أعد إرسال الرابط", show_alert=True)
        return
    st = _edit_get(uid, sid)
    if action not in ("sp", "sv", "pit"):
        SPEED_PENDING.pop(uid, None)       # خرج من شاشة السرعة: نوقف استقبال الأرقام

    async def menu():
        await _show(q, _edit_menu_text(uid, sid), _edit_menu_markup(uid, sid))

    if action == "ovid":
        # الزر تحت الفيديو المرسَل: رسالة الفيديو ما تنعدل نصاً، فنرسل قائمة التعديل كرسالة جديدة تحته
        await q.answer()
        track_feature("edit_open", uid)
        TRIM_PENDING.pop(uid, None)
        await q.message.reply_text(_edit_menu_text(uid, sid), parse_mode="HTML",
                                   reply_markup=_edit_menu_markup(uid, sid))
        return

    if action in ("open", "menu"):
        await q.answer()
        if action == "open":
            track_feature("edit_open", uid)      # نحسب الفتح الفعلي فقط (مو الرجوع من الشاشات الفرعية)
        TRIM_PENDING.pop(uid, None)
        await menu()
        return

    if action == "home":
        await q.answer()
        TRIM_PENDING.pop(uid, None)
        await _show(q, LINK_CAPTION, _link_markup(sid))
        return

    if action == "clr":
        await q.answer("تم المسح")
        EDIT_STATE[f"{uid}:{sid}"] = dict(_EDIT_DEFAULT)
        await menu()
        return

    # ----- الفلاتر (صفحات) -----
    if action in ("fl", "pg"):
        await q.answer()
        page = int(arg) if (action == "pg" and arg and arg.isdigit()) else 0
        await _show(q, _filters_text(page), _filters_markup(sid, page))
        return

    if action == "pick" and arg in FILTERS:
        st["f"] = arg
        await q.answer("✅ تم اختيار الفلتر")
        await menu()
        return

    if action == "p" and arg in FILTERS:
        await q.answer("⏳ جاري تجهيز المعاينة...")
        idx = list(FILTERS.keys()).index(arg)
        back = f"ed_pg_{idx // FILTERS_PER_PAGE}_{sid}"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ اختيار هذا الفلتر", callback_data=f"ed_pick_{arg}_{sid}", style="success")],
            [InlineKeyboardButton("↩️ رجوع", callback_data=back)],
        ])
        label, vf = FILTERS[arg]
        try:
            img = await _get_thumb(sid, url)
            out = await _filter_preview_image(img, vf, f"{uid}_{sid}_{arg}")
            if not out:
                raise Exception("preview failed")
            await _show(q, f"🎨 معاينة: <b>{label}</b>", markup, photo=out)
        except Exception as e:
            logger.error(f"Filter preview failed: {e}")
            await _show(q, f"❌ تعذرت معاينة الفلتر لهذا الرابط.\nتقدر تختاره مباشرة: <b>{label}</b>", markup)
        return

    # ----- القص -----
    if action == "cut":
        await q.answer()
        TRIM_PENDING[uid] = {"sid": sid, "start": None, "msg": (q.message.chat_id, q.message.message_id)}
        await _show(q, _cut_text(), _cut_markup(sid))
        return

    if action == "q" and arg and arg.isdigit():
        n = min(int(arg), TRIM_MAX_SECONDS)
        st["c"] = (0, n)
        TRIM_PENDING.pop(uid, None)
        await q.answer("✅ تم تحديد القص")
        await menu()
        return

    # ----- السرعة -----
    if action == "sp":
        await q.answer()
        SPEED_PENDING[uid] = {"sid": sid, "msg": (q.message.chat_id, q.message.message_id)}
        await _show(q, _speed_text(uid, sid), _speed_markup(uid, sid))
        return

    if action == "sv" and arg:
        st["s"] = None if (arg not in SPEEDS or st["s"] == arg) else arg     # الضغط على المحددة مرة ثانية = إلغاء (السرعة العادية)
        SPEED_PENDING[uid] = {"sid": sid, "msg": (q.message.chat_id, q.message.message_id)}
        await q.answer("✅ تم" if st["s"] else "السرعة العادية")
        await _show(q, _speed_text(uid, sid), _speed_markup(uid, sid))
        return

    if action == "pit" and arg in ("0", "1"):
        st["p"] = (arg == "1")
        SPEED_PENDING[uid] = {"sid": sid, "msg": (q.message.chat_id, q.message.message_id)}
        await q.answer("🎚 تغيير النبرة" if st["p"] else "🎙 صوت طبيعي")
        await _show(q, _speed_text(uid, sid), _speed_markup(uid, sid))
        return

    # ----- الاتجاه (عمودي/عرضي) -----
    if action == "or":
        await q.answer()
        await _show(q, _ori_text(uid, sid), _ori_markup(uid, sid))
        return

    if action == "op" and arg in ORIENT:
        await q.answer("⏳ جاري تجهيز المعاينة...")
        label = ORIENT[arg][0]
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ اعتماد {label}", callback_data=f"ed_oc_{arg}_{sid}", style="success")],
            [InlineKeyboardButton("↩️ رجوع", callback_data=f"ed_or_{sid}")],
        ])
        vf = _ori_graph(arg) + ("," + FILTERS[st["f"]][1] if st["f"] in FILTERS else "")
        try:
            img = await _get_thumb(sid, url)
            out = await _filter_preview_image(img, vf, f"{uid}_{sid}_o{arg}")
            if not out:
                raise Exception("preview failed")
            await _show(q, f"📐 معاينة: <b>{label}</b>", markup, photo=out)
        except Exception as e:
            logger.error(f"Orientation preview failed: {e}")
            await _show(q, f"❌ تعذرت المعاينة لهذا الرابط.\nتقدر تعتمد مباشرة: <b>{label}</b>", markup)
        return

    if action == "oc" and arg in ("v", "h", "n"):
        st["o"] = arg if arg in ORIENT else None
        await q.answer("✅ تم" if st["o"] else "رجع الاتجاه الأصلي")
        await menu()
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
        _info = stats.setdefault("pro_info", {}).setdefault(uid, {})
        if not premium_until_before(base, uid) or "since" not in _info:
            _info["since"] = datetime.now().isoformat()
        _info["plan"] = payload[5:]
        _info.pop("custom_days", None)
        _info["last"] = datetime.now().isoformat()
        _info["count"] = int(_info.get("count", 0)) + 1
        stats.setdefault("pro_reminded", {}).pop(uid, None)
        save_stats()
        await update.message.reply_text(
            f"🎉 <b>أهلاً بك في ZenDown Pro!</b>\n\n"
            f"✅ تم تفعيل الباقة <b>{plan['label']}</b>\n"
            f"📅 تنتهي في: <b>{new_exp.strftime('%Y-%m-%d %H:%M')}</b>\n\n"
            "مزاياك الآن:\n🚀 تخطي الطابور\n🎬 تعديل المقطع (فلاتر + قص + سرعة + اتجاه) من زر «تعديل المقطع» تحت أي رابط\n\nشكراً لدعمك 💙",
            parse_mode="HTML")
        return
    stats["star_donations"] = stats.get("star_donations", 0) + 1
    save_stats()
    await update.message.reply_text("🌟 شكراً جزيلاً على دعمك! هذا يساعدنا نستمر ونطوّر البوت. 💙")

# ================== طلبات الدفع بـ TON من التطبيق المصغر (تفعيل يدوي بمراجعة الأدمن) ==================
def _apply_plan(uid, plan_key):
    """يفعّل/يمدّد باقة لمستخدم بنفس منطق الدفع بالنجوم. يرجّع تاريخ الانتهاء الجديد."""
    plan = PLANS[plan_key]
    uid = str(uid)
    stats.setdefault("premium", {})
    base = premium_until(uid) or datetime.now()
    new_exp = base + timedelta(days=plan["days"])
    stats["premium"][uid] = new_exp.isoformat()
    stats["plan_sales"] = stats.get("plan_sales", 0) + 1
    _info = stats.setdefault("pro_info", {}).setdefault(uid, {})
    if not premium_until_before(base, uid) or "since" not in _info:
        _info["since"] = datetime.now().isoformat()
    _info["plan"] = plan_key
    _info.pop("custom_days", None)
    _info["last"] = datetime.now().isoformat()
    _info["count"] = int(_info.get("count", 0)) + 1
    stats.setdefault("pro_reminded", {}).pop(uid, None)
    save_stats()
    return new_exp

async def ton_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != ADMIN_ID:
        await q.answer("للأدمن فقط", show_alert=True)
        return
    act, oid = q.data.split("_", 1)           # tonok_<id> | tonno_<id>
    o = stats.get("ton_orders", {}).get(oid)
    if not o:
        await q.answer("الطلب غير موجود (قد يكون انتهى)", show_alert=True)
        return
    if o.get("st") in ("done", "rejected"):
        await q.answer("تمت معالجة هذا الطلب سابقاً", show_alert=True)
        return
    uid = o["uid"]
    try:
        base_txt = q.message.text_html or ""
    except Exception:
        base_txt = ""
    if act == "tonok" and o.get("plan") in PLANS:
        new_exp = _apply_plan(uid, o["plan"])
        o["st"] = "done"
        stats["ton_received"] = round(float(stats.get("ton_received", 0)) + float(o.get("ton", 0)), 4)
        if webapp_api:
            try: webapp_api._bump("ton_done")
            except Exception: pass
        save_stats()
        await q.answer("✅ تم التفعيل")
        try:
            await q.message.edit_text(base_txt + f"\n\n✅ <b>تم تفعيل الباقة</b> حتى {new_exp.strftime('%Y-%m-%d %H:%M')}",
                                      parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=uid, parse_mode="HTML",
                text=(f"🎉 <b>أهلاً بك في ZenDown Pro!</b>\n\n"
                      f"✅ تم تأكيد تحويلك وتفعيل الباقة <b>{PLANS[o['plan']]['label']}</b>\n"
                      f"📅 تنتهي في: <b>{new_exp.strftime('%Y-%m-%d %H:%M')}</b>\n\nشكراً لدعمك 💙"))
        except Exception as e:
            logger.info(f"ton activation notice failed for {uid}: {e}")
    else:
        o["st"] = "rejected"
        save_stats()
        await q.answer("تم الرفض")
        try:
            await q.message.edit_text(base_txt + "\n\n❌ <b>تم رفض الطلب</b>", parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=uid,
                text="ℹ️ لم نتمكن من تأكيد تحويلك. إذا كنت متأكداً أنك حوّلت مع التعليق الصحيح، راسل الدعم بالأمر /paysupport.")
        except Exception:
            pass

async def _clear_status(msg):
    """بعد التسليم: نحذف رسالة الحالة، ولو فشل الحذف (مهلة/ضغط) نعيد المحاولة ثم نحوّلها إلى «تم» بدل ما تبقى عالقة."""
    for _ in range(3):
        try:
            await msg.delete()
            return
        except Exception as e:
            logger.info(f"status delete retry: {e}")
            await asyncio.sleep(1.5)
    try:
        await msg.edit_text("✅ تم الإرسال")
    except Exception:
        pass

async def download_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    parts = q.data.split("_")
    if parts[0] == "ed":          # ed_go_<sid> : تطبيق التعديلات (فلتر + قص)
        action, sid = "edt", parts[-1]
    else:
        _, action, sid = parts
    url = await get_session_url(sid)

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
        SPEED_PENDING.pop(uid_now, None)
        if not _has_edit(edit_st):
            await q.message.reply_text("اختر فلتراً أو قصاً أو سرعة أو اتجاهاً أولاً من قائمة 🎬 تعديل المقطع.")
            return

    # فحص الزحمة: لو عدد الطلبات المنتظرة وصل للحد الأقصى، نرفض فوراً برسالة واضحة
    # بدل ما نضيف الطلب لطابور بلا سقف يتراكم ويصير هو نفسه سبب انفجار الذاكرة.
    global _pending_downloads
    async with _pending_lock:
        _pending_downloads += 1

    platform = detect_platform(url)
    if action == "edt":
        # نستخدم رسالة القائمة نفسها كرسالة حالة (بدون رسائل جديدة)
        status_msg = q.message
        try:
            await status_msg.edit_text("⏳ أضيفت إلى طابور التحميل الذكي...")
        except Exception:
            status_msg = await q.message.reply_text("⏳ أضيفت إلى طابور التحميل الذكي...")
    else:
        status_msg = await q.message.reply_text("⏳ أضيفت إلى طابور التحميل الذكي...")

    async def _fail(text):
        """رسالة فشل: في التعديل نرجّع القائمة تحتها ليكمل المستخدم بدون إعادة البدء."""
        if action == "edt":
            try:
                await status_msg.edit_text(f"{text}\n\n{_edit_menu_text(uid_now, sid)}", parse_mode="HTML",
                                           reply_markup=_edit_menu_markup(uid_now, sid))
                return
            except Exception:
                pass
        await status_msg.edit_text(text)
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

    # === مرحلة التحميل (بوابة مستقلة) ثم معالجة ffmpeg (بوابة مستقلة) - الثقيلة ما تسد الخفيفة ===
    await status_msg.edit_text("🚀 جاري التحميل...")
    try:
        async with DOWNLOAD_SEMAPHORE:
            if _is_tiktok(url):
                file_path = (await run_isolated("download", url, opts))["file"]
            else:
                file_path = await asyncio.wait_for(run_blocking(_blocking_download, url, opts), timeout=90)
        if action == "edt":
            try:
                await status_msg.edit_text("⏳ بانتظار دورك في معالجة الفيديو...")
            except Exception:
                pass
            async with PROCESS_SEMAPHORE:
                try:
                    await status_msg.edit_text("🎬 جاري تطبيق التعديلات (قد ياخذ دقيقة)...")
                except Exception:
                    pass
                cut_src = file_path
                file_path = f"edt_{sid}.mp4"
                vf = _edit_vf(edit_st)
                ok = await _ffmpeg_edit(cut_src, file_path, edit_st["c"], vf,
                                        speed=edit_st["s"], pitch=edit_st["p"], has_ori=bool(edit_st["o"]))
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
                if action == "edt": track_feature("edit_fail", uid_now)
                await _fail(f"مقطع حجمه أكثر من 50 ميجا ({final_size_mb:.1f} ميجا) - يتجاوز حد تليجرام للبوتات، ما نقدر نرسله للأسف.")
                track_download_status(False, platform)
                return

            try:
                await status_msg.edit_text("📤 جاري إرسال الملف...")
            except Exception as e:
                logger.info(f"status edit (sending) failed, non-critical: {e}")
            async with SEND_SEMAPHORE:
                with open(file_path, 'rb') as f:
                    if action == "vid": await q.message.reply_video(video=f, caption="🎬 تم بواسطة @ZenDown_Bot", supports_streaming=True, reply_markup=_tpl_markup(sid))
                    elif action == "edt": await q.message.reply_video(video=f, caption="🎬 تم بواسطة @ZenDown_Bot", supports_streaming=True)
                    elif action == "aud": await q.message.reply_audio(audio=f, caption="🎵 تم بواسطة @ZenDown_Bot")
                    elif action == "voc": await q.message.reply_voice(voice=f, caption="🎙 تم بواسطة @ZenDown_Bot")

            # الملف وصل بنجاح - نسجل النجاح فوراً قبل أي خطوة إضافية غير حرجة
            track_download_status(True, platform)
            track_user_download(update.effective_user.id, platform)

            if action == "edt":
                track_feature("edit_done", uid_now)
                if edit_st.get("s"): track_feature("edit_speed", uid_now)
                if edit_st.get("o"): track_feature("edit_orient", uid_now)
                if edit_st.get("f"): track_feature("edit_filter", uid_now)
                if edit_st.get("c"): track_feature("edit_cut", uid_now)
                if not premium:
                    use_free_trial(uid_now)
                # بعد التسليم نحذف رسالة الحالة/قائمة التعديل نهائياً (لا تُرسل مجدداً)
                await _clear_status(status_msg)
                try:
                    if q.message.message_id != status_msg.message_id:
                        await q.message.delete()
                except Exception:
                    pass
                return   # بدون رسالة تبرع هنا (نخلي الشات نظيف)
            else:
                await _clear_status(status_msg)

            # زر التبرع اختياري وغير حرج - أي فشل فيه (تايم آوت مثلاً) ما يجب يؤثر على نتيجة التحميل
            try:
                donate_markup = InlineKeyboardMarkup([[InlineKeyboardButton("تبرع للبوت بـ 1 ⭐", callback_data="donate_star")]])
                await q.message.reply_text("لو حاب تدعم استمرار البوت، تقدر تتبرع بنجمة ⬇️", reply_markup=donate_markup)
            except Exception as e:
                logger.error(f"Donate button send failed (non-critical): {e}")
        else:
            track_download_status(False, platform)
            if action == "edt": track_feature("edit_fail", uid_now)
            await _fail("❌ حدث خطأ أثناء التحميل، قد يكون المقطع محمي كلياً أو يحتاج تسجيلاً إجبارياً.")
    except Exception as e:
        logger.error(f"Send Error: {e}")
        if action == "edt": track_feature("edit_fail", uid_now)
        track_download_status(False, platform)
        await _fail("❌ حدث خطأ أثناء معالجة وإرسال الملف.")
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
    try:
        from telegram.error import Conflict
        if isinstance(context.error, Conflict):
            await _alert_admin("conflict", "⚠️ Conflict: نسخة ثانية من البوت تعمل بنفس التوكن! أوقف أي خدمة Render مكررة.", every=1800)
            return
        if isinstance(update, Update) and update.callback_query:
            await update.callback_query.answer("⚠️ حدث خطأ مؤقت، حاول مرة ثانية", show_alert=True)
    except Exception:
        pass

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
                            flush_stats_to_disk(force=True)
                            await turso_push_now(force=True)
                            os._exit(0)
                        break
        except Exception as e:
            logger.error(f"Memory watchdog check failed: {e}")

async def _post_init(application):
    BOT_REF["bot"] = application.bot
    if webapp_api:
        webapp_api.set_runtime(asyncio.get_running_loop(), application.bot)
    asyncio.create_task(_memory_watchdog())
    await turso_load_on_startup()
    apply_settings()
    asyncio.create_task(turso_sync_loop())
    asyncio.create_task(backup_loop())
    asyncio.create_task(stats_disk_loop())
    asyncio.create_task(bc_watchdog_loop())
    asyncio.create_task(_bc_startup_notice(application.bot))
    asyncio.create_task(pro_reminder_loop(application.bot))
    # تيليجرام ما يسمح بأسماء أوامر عربية (لازم إنجليزي صغير بدون مسافات)، فنسجل الأمر
    # بالإنجليزي "mystats" لكن بوصف عربي - عشان يظهر بقائمة الأوامر لما يكتب المستخدم "/"
    try:
        await application.bot.set_my_commands([
            ("start", "🚀 بدء استخدام البوت"),
            ("help", "📖 كيف أستخدم البوت"),
            ("pro", "👑 باقات Pro"),
            ("qr", "📱 تحويل رابط إلى QR"),
            ("mystats", "📊 إحصائياتي"),
            ("paysupport", "💬 دعم المدفوعات"),
        ])
        # أمر الأدمن - يظهر لك أنت فقط في قائمة "/" (كل التحكم صار داخل لوحة واحدة)
        from telegram import BotCommandScopeChat
        await application.bot.set_my_commands([
            ("start", "🚀 بدء استخدام البوت"),
            ("help", "📖 كيف أستخدم البوت"),
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
    flush_stats_to_disk(force=True)
    await turso_push_now(force=True)

def main():
    if webapp_api:
        webapp_api.configure(sys.modules[__name__], TOKEN, ADMIN_ID)
    zen_store.configure(stats_ref=stats, logger_ref=logger, admin_id=ADMIN_ID, get_setting_fn=get_setting,
                         save_stats_fn=save_stats, url_cache=URL_CACHE, empty_platform_stats_fn=_empty_platform_stats)
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(128)\
        .read_timeout(30).write_timeout(120).connect_timeout(15).pool_timeout(20).connection_pool_size(64).post_init(_post_init).post_shutdown(_post_shutdown).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_capture), group=-1)
    app.add_handler(CallbackQueryHandler(broadcast_cancel_callback, pattern="^bc_cancel$"))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.CaptionRegex(r"(?i)restore|استعادة") & filters.User(ADMIN_ID), restore_from_document))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(how_callback, pattern="^how_[123]$"))
    app.add_handler(CallbackQueryHandler(ton_admin_callback, pattern="^ton(ok|no)_[0-9A-F]{6}$"))
    app.add_handler(CallbackQueryHandler(mode_callback, pattern="^mode_(qr|ocr|dl)$"))
    app.add_handler(CallbackQueryHandler(ocr_cancel_callback, pattern="^ocr_cancel$"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(إعدادات|اعدادات) (الأدمن|الادمن)$|^لوحة (التحكم|الأدمن|الادمن)$|^(الأدمن|الادمن|ادمن)$"), admin_panel_command))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(bc_stop_callback, pattern="^bc_stop$"))
    app.add_handler(CallbackQueryHandler(bc_speed_callback, pattern="^bc_spd_(up|dn)$"))
    app.add_handler(CallbackQueryHandler(bc_unstick_callback, pattern="^bc_unstick$"))
    app.add_handler(CallbackQueryHandler(bc_resume_callback, pattern="^bc_resume$"))
    app.add_handler(CallbackQueryHandler(bc_aud_callback, pattern="^bc_aud_"))
    app.add_handler(CallbackQueryHandler(bc_delete_callback, pattern="^bc_(del|delyes|delno)$"))
    app.add_handler(CallbackQueryHandler(edit_callback, pattern="^ed_(open|ovid|menu|home|fl|pg|p|pick|cut|q|clr|sp|sv|pit|or|op|oc)_"))
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
    app.add_handler(CallbackQueryHandler(show_stats_command, pattern="^(refresh_stats|st_pro)$"))

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
