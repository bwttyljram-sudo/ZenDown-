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

def save_stats():
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False)
    except Exception:
        pass

# ================== طبقة التخزين الدائم (ملف zen_store.py المنفصل) ==================
import zen_store
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

    tp_u, tp_n = feat_counts("tpl_done")
    _, tpf_n = feat_counts("tpl_fail")
    done_map = stats.get("feat", {}).get("edit_done", {})
    top = sorted(done_map.items(), key=lambda x: x[1], reverse=True)[:5]
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    top_lines = []
    for i, (u, n) in enumerate(top):
        tag = " 👑" if premium_until(u) else ""
        top_lines.append(f"{medals[i]} <code>{u}</code>{tag} — {n} مقطع")
    top_str = "\n".join(top_lines) if top_lines else "لا يوجد بعد."

    lst = pro_now[:15]
    lst_str = "\n".join(f"• <code>{u}</code> — {PLANS[_pro_plan_of(u)]['label']} — باقي {_remaining_text(e)}" for u, e in lst) or "لا يوجد"
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
        f"🧹 إزالة حقوق النشر : ✅ {tp_n} ({tp_u} مستخدم) • ❌ {tpf_n}\n"
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
BC = {"running": False, "cancel": False}

# ---------- اختيار فئة المستلمين للإذاعة ----------
BC_AUDIENCE = {"v": "all"}      # all / active / pro / custom
BC_CUSTOM = {"ids": []}         # المستلمون المحددون يدوياً (فئة custom)
ACTIVE_HOURS = 24               # تعريف "النشطون": تفاعلوا خلال آخر كم ساعة

def _audience_users(kind=None):
    kind = kind or BC_AUDIENCE["v"]
    if kind == "custom":
        return list(BC_CUSTOM["ids"])
    ids = list(stats["users"].keys())
    if kind == "pro":
        return [u for u in ids if premium_until(u)]
    if kind == "active":
        lim = datetime.now() - timedelta(hours=ACTIVE_HOURS)
        out = []
        for u in ids:
            try:
                if datetime.fromisoformat(stats["users"][u]) >= lim:
                    out.append(u)
            except Exception:
                pass
        return out
    return ids

def _bc_open_markup():
    cur = BC_AUDIENCE["v"]
    def b(k, label):
        return InlineKeyboardButton(("✅ " if cur == k else "") + f"{label} ({len(_audience_users(k))})", callback_data=f"bc_aud_{k}")
    return InlineKeyboardMarkup([
        [b("all", "👥 الكل")],
        [b("active", f"🟢 النشطون {ACTIVE_HOURS}س"), b("pro", "👑 Pro")],
        [b("custom", "🎯 مستخدمون محددون")],
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
        users = _audience_users()
        total = len(users)
        if total == 0:
            await bot.send_message(chat_id=ADMIN_ID, text="⚠️ ما فيه مستلمين محددين. اختر الفئة (🎯 مستخدمون محددون) وأرسل الـ ID أو العدد أولاً، ثم الرسالة.")
            return
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
        BC_AUDIENCE["v"] = "all"   # نرجّع الفئة للكل بعد كل إذاعة (أمان)

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
                exp = base + timedelta(days=days)
                stats.setdefault("premium", {})[tid] = exp.isoformat()
                save_stats()
                await m.reply_text(f"✅ تم منح Pro للمستخدم {tid} لمدة {days} يوم (حتى {exp.strftime('%Y-%m-%d')}).")
                try:
                    await context.bot.send_message(chat_id=int(tid), text=f"🎁 تم منحك اشتراك <b>Pro</b> لمدة {days} يوم! استمتع 👑", parse_mode="HTML")
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
        await _bc_open(msg)
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
        await _ask_subscribe(update.message)
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
    "dream":   ("✨ حالم", "split[da][db];[db]gblur=sigma=12[dbl];[da][dbl]blend=all_mode=screen:all_opacity=0.5"),
    "grain":   ("🎞 حبيبات فيلم", "noise=alls=35:allf=t+u,eq=contrast=1.05"),
    "neg":     ("🌓 نيجاتيف", "negate"),
    "vhs":     ("📺 VHS", "noise=alls=22:allf=t,eq=saturation=1.6:contrast=1.15,gblur=sigma=1.2"),
    "neon":    ("💜 نيون", "eq=contrast=1.25:saturation=2.0:brightness=-0.04,hue=h=15"),
    "fade":    ("🌫 ماتي باهت", "eq=contrast=0.75:brightness=0.08:saturation=0.65"),
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
        f"▫️ الباقة: <b>{PLANS[plan_key]['label']}</b>\n"
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
                      f"باقتك: <b>{plan['label']}</b>\n"
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
    rows.append([InlineKeyboardButton(TPL_BTN_LABEL, callback_data=f"down_tpl_{sid}", style="success")])
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
    if _is_tiktok(url):
        async with TIKTOK_INFO_SEM:
            thumb_url = (await run_isolated("info", url, _tt_info_opts())).get("thumbnail")
    else:
        thumb_url = await asyncio.wait_for(run_blocking(_blocking_get_thumbnail, url), timeout=30)
    if not thumb_url:
        raise Exception("no thumbnail")
    img = await asyncio.wait_for(run_blocking(_blocking_fetch_bytes, thumb_url), timeout=20)
    THUMB_CACHE[sid] = img
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
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", *args,
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

# ================== قالب «لمسة ZenDown»: فلتر ثابت + شعار صغير بظهور تدريجي + تنظيف بيانات الملف ==================
TPL_BTN_LABEL = "إزالة حقوق النشر 🧹"            # غيّر الاسم من هنا لو تبي
TPL_LOOK = ("eq=contrast=1.08:saturation=1.2:brightness=0.02,"
            "colorbalance=rs=.05:bs=-.05:rm=.03:bm=-.03,unsharp=3:3:0.5:3:3:0")
TPL_ZOOM = 0.96                              # قص خفيف 4% من الأطراف (يغيّر الإطار قليلاً)
MARK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zen_mark.png")
MARK_B64 = "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"

def _ensure_mark():
    """صورة الشعار+الاسم جاهزة ومضمّنة داخل الكود؛ تُكتب مرة واحدة على القرص."""
    try:
        if not os.path.exists(MARK_FILE) or os.path.getsize(MARK_FILE) < 1000:
            import base64
            with open(MARK_FILE, "wb") as f:
                f.write(base64.b64decode(MARK_B64))
    except Exception as e:
        logger.error(f"mark write failed: {e}")
    return MARK_FILE

def _tpl_markup(sid):
    return InlineKeyboardMarkup([[InlineKeyboardButton(TPL_BTN_LABEL, callback_data=f"down_tpl_{sid}", style="success")]])

async def _ffprobe_info(src):
    """يرجّع (عرض، ارتفاع، مدة) أو None. خفيف جداً (قراءة ترويسة فقط)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration", "-of", "json", src,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        j = json.loads(out.decode() or "{}")
        st = (j.get("streams") or [{}])[0]
        return int(st["width"]), int(st["height"]), float((j.get("format") or {}).get("duration") or 0)
    except Exception:
        return None

async def _ffmpeg_template(src, dst):
    """يطبّق القالب في مرور واحد. يرجّع (نجح؟، مدة_القص_بالثواني أو None لو ما انقص)."""
    mark = _ensure_mark()
    if not os.path.exists(mark):
        return False, None
    info = await _ffprobe_info(src)
    w, h, dur = info if info else (720, 1280, 0)
    max_d = max(5, int(FILTER_MAX_SECONDS))
    trimmed = max_d if dur and dur > max_d + 0.5 else None
    d_in = min(dur, max_d) if dur else max_d
    cap = 720 if d_in <= 20 else 540
    w1 = max(2, int(w * TPL_ZOOM) // 2 * 2)
    h1 = max(2, int(h * TPL_ZOOM) // 2 * 2)
    if h1 > cap:
        out_h, out_w = cap, max(2, int(w1 * cap / h1) // 2 * 2)
    else:
        out_h, out_w = h1, w1
    lw = max(100, min(240, int(out_w * (0.32 if out_w < out_h else 0.20)))) // 2 * 2
    m = max(8, int(out_w * 0.025))
    fc = (f"[0:v]crop=trunc(iw*{TPL_ZOOM}/2)*2:trunc(ih*{TPL_ZOOM}/2)*2,"
          f"scale=-2:'min({cap},ih)',{TPL_LOOK}[bg];"
          f"[1:v]scale={lw}:-1,format=rgba,fade=t=in:st=0.3:d=0.9:alpha=1[lg];"
          f"[bg][lg]overlay=W-w-{m}:{m}:format=auto:shortest=1[out]")
    args = ["-t", f"{d_in:.2f}", "-i", src, "-loop", "1", "-framerate", "25", "-t", f"{d_in:.2f}", "-i", mark,
            "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
            "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-threads", "1", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", dst]
    ok = await _ffmpeg_exec(args, timeout=180)
    ok = ok and os.path.exists(dst) and os.path.getsize(dst) > 0
    return ok, trimmed

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
    if action == "tpl" and not premium and free_trials_left(uid_now) <= 0:
        await _pro_upsell_apply(q)
        return
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

    if action in ("vid", "edt", "tpl"):
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
    tpl_trim = None
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
                vf = _edit_vf(edit_st)
                ok = await _ffmpeg_edit(cut_src, file_path, edit_st["c"], vf,
                                        speed=edit_st["s"], pitch=edit_st["p"], has_ori=bool(edit_st["o"]))
                if not ok:
                    raise Exception("ffmpeg edit failed")
            if action == "tpl":
                await status_msg.edit_text("🧹 جاري تطبيق القالب (قد ياخذ دقيقة)...")
                cut_src = file_path
                file_path = f"tpl_{sid}.mp4"
                ok, tpl_trim = await _ffmpeg_template(cut_src, file_path)
                if not ok:
                    raise Exception("ffmpeg template failed")
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

            await status_msg.edit_text("📤 جاري إرسال الملف...")
            async with SEND_SEMAPHORE:
                with open(file_path, 'rb') as f:
                    if action == "vid": await q.message.reply_video(video=f, caption="🎬 تم بواسطة @ZenDown_Bot", supports_streaming=True, reply_markup=_tpl_markup(sid))
                    elif action == "tpl":
                        _cap = "🎬 تم بواسطة @ZenDown_Bot" + (f"\n⏱ تم اقتصاص أول {tpl_trim} ثانية" if tpl_trim else "")
                        await q.message.reply_video(video=f, caption=_cap, supports_streaming=True)
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
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                try:
                    if q.message.message_id != status_msg.message_id:
                        await q.message.delete()
                except Exception:
                    pass
                return   # بدون رسالة تبرع هنا (نخلي الشات نظيف)
            elif action == "tpl":
                track_feature("tpl_done", uid_now)
                if not premium:
                    use_free_trial(uid_now)
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                return
            else:
                await status_msg.delete()

            # زر التبرع اختياري وغير حرج - أي فشل فيه (تايم آوت مثلاً) ما يجب يؤثر على نتيجة التحميل
            try:
                donate_markup = InlineKeyboardMarkup([[InlineKeyboardButton("تبرع للبوت بـ 1 ⭐", callback_data="donate_star")]])
                await q.message.reply_text("لو حاب تدعم استمرار البوت، تقدر تتبرع بنجمة ⬇️", reply_markup=donate_markup)
            except Exception as e:
                logger.error(f"Donate button send failed (non-critical): {e}")
        else:
            track_download_status(False, platform)
            if action == "edt": track_feature("edit_fail", uid_now)
            if action == "tpl": track_feature("tpl_fail", uid_now)
            await _fail("❌ حدث خطأ أثناء التحميل، قد يكون المقطع محمي كلياً أو يحتاج تسجيلاً إجبارياً.")
    except Exception as e:
        logger.error(f"Send Error: {e}")
        if action == "edt": track_feature("edit_fail", uid_now)
        if action == "tpl": track_feature("tpl_fail", uid_now)
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
                            await turso_push_now(force=True)
                            os._exit(0)
                        break
        except Exception as e:
            logger.error(f"Memory watchdog check failed: {e}")

async def _post_init(application):
    BOT_REF["bot"] = application.bot
    asyncio.create_task(_memory_watchdog())
    await turso_load_on_startup()
    apply_settings()
    asyncio.create_task(turso_sync_loop())
    asyncio.create_task(backup_loop())
    asyncio.create_task(pro_reminder_loop(application.bot))
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
    await turso_push_now(force=True)

def main():
    zen_store.configure(stats_ref=stats, logger_ref=logger, admin_id=ADMIN_ID, get_setting_fn=get_setting,
                         save_stats_fn=save_stats, url_cache=URL_CACHE, empty_platform_stats_fn=_empty_platform_stats)
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(128).post_init(_post_init).post_shutdown(_post_shutdown).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_capture), group=-1)
    app.add_handler(CallbackQueryHandler(broadcast_cancel_callback, pattern="^bc_cancel$"))
    app.add_handler(MessageHandler(filters.Document.ALL & filters.CaptionRegex(r"(?i)restore|استعادة") & filters.User(ADMIN_ID), restore_from_document))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(mode_callback, pattern="^mode_(qr|ocr|dl)$"))
    app.add_handler(CallbackQueryHandler(ocr_cancel_callback, pattern="^ocr_cancel$"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(إعدادات|اعدادات) (الأدمن|الادمن)$|^لوحة (التحكم|الأدمن|الادمن)$|^(الأدمن|الادمن|ادمن)$"), admin_panel_command))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(bc_stop_callback, pattern="^bc_stop$"))
    app.add_handler(CallbackQueryHandler(bc_aud_callback, pattern="^bc_aud_"))
    app.add_handler(CallbackQueryHandler(bc_delete_callback, pattern="^bc_(del|delyes|delno)$"))
    app.add_handler(CallbackQueryHandler(edit_callback, pattern="^ed_(open|menu|home|fl|pg|p|pick|cut|q|clr|sp|sv|pit|or|op|oc)_"))
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
