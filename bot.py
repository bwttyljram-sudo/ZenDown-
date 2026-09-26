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
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, filters
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
    else:
        print("❌ فشل تثبيت yt-dlp[default] فعلياً! الخطأ الحقيقي:")
        print(result.stderr[-3000:])
except Exception as e:
    print(f"⚠️ فشل التحديث التلقائي: {e}")

from yt_dlp import YoutubeDL

# طباعة نسخة yt-dlp الفعلية المثبتة
try:
    import importlib.metadata as _im
    print(f"📦 نسخة yt-dlp المثبتة فعلياً: {_im.version('yt-dlp')}")
except Exception as e:
    print(f"⚠️ تعذر قراءة نسخة yt-dlp: {e}")

# ملاحظة: هذا البوت لا يدعم تيك توك إطلاقاً (مخصص لبوت منفصل @Vdy_bot)
# فلا حاجة لتثبيت Deno أو curl_cffi هنا - هذا يخفف البوت فعلياً (بدون محرك جافاسكريبت).


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
COOKIES_FILE = "/etc/secrets/cookies.txt"
COOKIES_FILE = COOKIES_FILE if os.path.exists(COOKIES_FILE) else None
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

def track_user_activity(user_id):
    stats["users"][str(user_id)] = datetime.now().isoformat()
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

async def show_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض أخطاء المنصات الأخرى فقط (بدون تيك توك ويوتيوب) عشان ما تنطمر بضجيج تيك توك المتكرر."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    text = _format_errors_list("آخر أخطاء المنصات الأخرى (بدون تيك توك/يوتيوب)", RECENT_ERRORS_OTHER)
    await update.message.reply_text(text, parse_mode="HTML")

async def show_all_errors_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض كل الأخطاء المسجلة شامل تيك توك ويوتيوب."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    text = _format_errors_list("كل الأخطاء المسجلة (شامل تيك توك ويوتيوب)", RECENT_ERRORS)
    await update.message.reply_text(text, parse_mode="HTML")

# ================== لوحة الإحصائيات ==================
async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID: return

    msg = update.callback_query.message if update.callback_query else update.message
    now = datetime.now()
    
    total_users = len(stats["users"])
    active_today = 0
    active_7d = 0
    active_30d = 0

    for uid, last_str in stats["users"].items():
        try:
            last_time = datetime.fromisoformat(last_str)
            diff = now - last_time
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
        f"🟢 نشطون (اليوم)  : {active_today}\n"
        f"📅 نشطون (7 أيام) : {active_7d}\n"
        f"🗓 نشطون (30 يوم) : {active_30d}\n"
        "───────────────\n\n"
        "📫 <b>التحميلات</b>\n"
        "───────────────\n"
        f"🔢 إجمالي الطلبات  : {total_req}\n"
        f"✅ ناجحة         : {success_dl}\n"
        f"❌ فاشلة         : {failed_dl}\n"
        f"⚡️ من الكاش       : {cache_hits}\n"
        f"🎬 فيديوهات أُرسلت : {sent_vids}\n"
        f"🛡 حد الطلبات     : {req_limits}\n"
        "───────────────\n\n"
        "🌎 <b>المنصات الأكثر طلباً</b>\n"
        "───────────────\n"
        f"{platforms_str}\n"
        "───────────────\n\n"
        "⚡️ <b>الأداء</b>\n"
        "───────────────\n"
        f"🔗 ضغطات المشاركة : {share_clicks}\n"
        f"💾 Cache Hit Rate : 0.0%\n"
        f"✅ معدل النجاح     : {rate:.1f}%\n"
        f"🌟 تبرعات بالنجوم  : {star_donations}\n"
        "───────────────\n\n"
        f"⏰ <b>وقت التشغيل:</b> {days} يوم {hours} ساعة {minutes} دقيقة\n"
        "🔄 <b>تحديث الإحصائيات:</b> كل 100 حدث أو عند الإيقاف"
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

# ================== الإذاعة ==================
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
        await update.message.reply_text("❌ لا يوجد مستخدمين مسجلين في قاعدة البيانات.")
        return

    msg = await update.message.reply_text(f"🚀 جاري إرسال الرسالة إلى {len(users)} مستخدم...\nيرجى الانتظار لتفادي حظر تيليجرام.")

    success = 0
    failed = 0

    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await msg.edit_text(f"✅ تمت عملية الإذاعة بنجاح!\n\n- نجح الإرسال إلى: {success} مستخدم\n- فشل الإرسال إلى: {failed} مستخدم (قاموا بحظر البوت غالباً)")

# ================== المعالجة والتحميل ==================
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

    await update.message.reply_text(f"أهلاً بك <b>{user.first_name}</b> في محرك @ZenDown_Bot الذكي! 🚀\nأرسل رابطاً للتحميل، أو اكتب نصاً للبحث المباشر.", parse_mode="HTML")

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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        await update.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً.")
        return

    text = update.message.text.strip()
    if text.startswith("http"):
        platform = track_platform_request(text)
        # فحص سريع (بدون أي تحليل أو اتصال بالإنترنت) قبل أي معالجة ثقيلة، عشان ما نضيع
        # وقت ولا موارد على روابط منصات مو مدعومة بهذا البوت
        if platform == "يوتيوب":
            await update.message.reply_text("عذراً، التحميل من YouTube غير متوفر حالياً.")
        elif platform == "تيك توك":
            await update.message.reply_text("للتحميل من تيك توك استخدم هذا البوت @Vdy_bot")
        else:
            await process_link_info(update, context, text)
    else:
        await update.message.reply_text("ميزة البحث قيد التطوير...")

# ================== جلب معلومات الرابط ==================
async def process_link_info(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    # بدون أي تحليل أو استخراج معلومات - نعرض الأزرار فوراً، عشان البوت يكون أسرع وأخف
    # ما يمكن (بدون عنوان الفيديو ولا صورة مصغرة - الثمن مقابل السرعة).
    sid = str(uuid.uuid4())[:8]
    URL_CACHE[sid] = url

    caption = "🎬 <b>رابط جاهز للتحميل</b>"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎥 فيديو MP4", callback_data=f"down_vid_{sid}", style="primary")],
        [InlineKeyboardButton("🎵 صوت MP3", callback_data=f"down_aud_{sid}", style="success"),
         InlineKeyboardButton("🎙 بصمة صوتية", callback_data=f"down_voc_{sid}", style="success")]
    ])

    await update.message.reply_text(caption, parse_mode="HTML", reply_markup=markup)

# ================== التحميل الذكي المحسّن والجدار الأمني ==================
# ================== زر التبرع بنجمة (Telegram Stars) ==================
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
    stats["star_donations"] = stats.get("star_donations", 0) + 1
    save_stats()
    await update.message.reply_text("🌟 شكراً جزيلاً على دعمك! هذا يساعدنا نستمر ونطوّر البوت. 💙")

async def download_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    _, action, sid = q.data.split("_")
    url = URL_CACHE.get(sid)
    
    if not url:
        await q.message.reply_text("❌ انتهت صلاحية هذه الجلسة، أعد إرسال الرابط.")
        return

    # فحص الزحمة: لو عدد الطلبات المنتظرة وصل للحد الأقصى، نرفض فوراً برسالة واضحة
    # بدل ما نضيف الطلب لطابور بلا سقف يتراكم ويصير هو نفسه سبب انفجار الذاكرة.
    global _pending_downloads
    async with _pending_lock:
        if _pending_downloads >= MAX_QUEUE_SIZE:
            await q.message.reply_text(
                "🚧 البوت مزدحم جداً حالياً (عدد كبير من الطلبات بالطابور).\n"
                "حاول مرة ثانية بعد كم دقيقة 🙏"
            )
            return
        _pending_downloads += 1

    platform = detect_platform(url)
    status_msg = await q.message.reply_text("⏳ أضيفت إلى طابور التحميل الذكي...")
    out_tmpl = f"zendown_{sid}.%(ext)s"

    if action == "vid":
        opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
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
                'youtube': {'player_client': ['tv', 'android', 'ios', 'web']},
                'twitter': {'api': ['syndication', 'graphql', 'legacy']}
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
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
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
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }

    file_path = None
    success_download = False

    # === مرحلة التحميل فقط - محاولة واحدة بس (بدون إعادة محاولة) عشان السرعة والخفة ===
    async with DOWNLOAD_SEMAPHORE:
        await status_msg.edit_text("🚀 جاري التحميل...")
        try:
            file_path = await asyncio.wait_for(run_blocking(_blocking_download, url, opts), timeout=90)
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
                if action == "vid": await q.message.reply_video(video=f, caption="🎬 تم بواسطة @ZenDown_Bot", supports_streaming=True)
                elif action == "aud": await q.message.reply_audio(audio=f, caption="🎵 تم بواسطة @ZenDown_Bot")
                elif action == "voc": await q.message.reply_voice(voice=f, caption="🎙 تم بواسطة @ZenDown_Bot")

            # الملف وصل بنجاح - نسجل النجاح فوراً قبل أي خطوة إضافية غير حرجة
            track_download_status(True, platform)
            await status_msg.delete()

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
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
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
                            os._exit(0)
                        break
        except Exception as e:
            logger.error(f"Memory watchdog check failed: {e}")

async def _post_init(application):
    asyncio.create_task(_memory_watchdog())

def main():
    app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).post_init(_post_init).build()
    app.add_error_handler(global_error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    
    app.add_handler(CommandHandler("stats", show_stats_command))
    app.add_handler(CommandHandler("errors", show_errors_command))
    app.add_handler(CommandHandler("all_errors", show_all_errors_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(اخطاء|أخطاء)$"), show_errors_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(كل الأخطاء|جميع الأخطاء)$"), show_all_errors_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(احصائيات|إحصائيات)$"), show_stats_command))
    app.add_handler(CallbackQueryHandler(show_stats_command, pattern="^refresh_stats$"))

    app.add_handler(CallbackQueryHandler(download_action_callback, pattern="^down_"))
    app.add_handler(CallbackQueryHandler(donate_star_callback, pattern="^donate_star$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 تم تشغيل محرك @ZenDown_Bot بنجاح! مزود بحماية الـ OOM والجدار الأمني لتيليجرام.")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()









