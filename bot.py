import subprocess
import sys
import asyncio
import logging
import os
import uuid
import json
import urllib.request
import time
import random
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)
from health_server import run_health_server_in_background

# تحديث تلقائي لمكتبة yt-dlp
try:
    print("🔄 جاري التحقق من تحديثات yt-dlp...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("✅ yt-dlp محدث لأحدث إصدار!")
except Exception as e:
    print(f"⚠️ فشل التحديث التلقائي: {e}")

from yt_dlp import YoutubeDL

# ================== سيرفر الصحة لإرضاء المنصة (Render/UptimeRobot) ==================
# تم نقل الكود الفعلي إلى health_server.py — هذا فقط يشغّله في الخلفية
run_health_server_in_background()


# ================== الإعدادات والتكوين ==================
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("ZenDown_Bot")

TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL = "@ZenoX_Tools"
# نقرأ الآيدي من متغير البيئة ID (نفس المتغير المضاف بلوحة Render) بدل ترقيمه يدوياً بالكود،
# مع الاحتفاظ بقيمة احتياطية لو المتغير غير موجود لأي سبب
try:
    ADMIN_ID = int(os.environ.get("ID", "6043858925"))
except (TypeError, ValueError):
    ADMIN_ID = 6043858925

# أقصى عدد تحميلات متزامنة لحماية الموارد
MAX_CONCURRENT_DOWNLOADS = 1 # تم تقليله لـ 1 لضمان استقرار السيرفر المجاني
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)

# ذاكرة مؤقتة (تُحفظ على القرص لتنجو من إعادة التشغيل: نوم Render التلقائي أو أي Deploy جديد)
CACHE_FILE = "session_cache.json"
MAX_CACHE_ENTRIES = 300  # سقف بسيط لمنع تضخم الملف على المدى الطويل

def _load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("url_cache", {}), data.get("search_cache", {})
        except Exception:
            pass
    return {}, {}

URL_CACHE, SEARCH_CACHE = _load_cache()

def _save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"url_cache": URL_CACHE, "search_cache": SEARCH_CACHE}, f, ensure_ascii=False)
    except Exception:
        pass

def cache_url(sid, url):
    URL_CACHE[sid] = url
    if len(URL_CACHE) > MAX_CACHE_ENTRIES:
        URL_CACHE.pop(next(iter(URL_CACHE)))  # نحذف أقدم إدخال (ترتيب الإدخال محفوظ بالـ dict)
    _save_cache()

def cache_search(sid, data):
    SEARCH_CACHE[sid] = data
    if len(SEARCH_CACHE) > MAX_CACHE_ENTRIES:
        SEARCH_CACHE.pop(next(iter(SEARCH_CACHE)))
    _save_cache()

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
        "users": {},
        "total_requests": 0,
        "successful_downloads": 0,
        "failed_downloads": 0,
        "cache_hits": 0,
        "sent_videos": 0,
        "request_limits": 0,
        "share_clicks": 0,
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

# ================== إدارة الاشتراك والتحقق ==================
async def check_user_subscription(bot, user_id: int) -> bool:
    if user_id == ADMIN_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

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

    total_dl = success_dl + failed_dl
    rate = (success_dl / total_dl * 100) if total_dl > 0 else 0.0

    uptime = datetime.now() - BOT_START_TIME
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds // 60) % 60

    sorted_platforms = sorted(stats["platforms"].items(), key=lambda x: x[1], reverse=True)
    platform_icons = {
        "يوتيوب": "▶️",
        "تويتر/X": "𝕏",
        "سناب شات": "👻",
        "تيك توك": "🎵",
        "إنستغرام": "📸",
        "بينترست": "📌",
        "أخرى": "🌐"
    }

    platform_lines = []
    for idx, (p_name, count) in enumerate(sorted_platforms, 1):
        icon = platform_icons.get(p_name, "▫️")
        platform_lines.append(f"{idx}. {icon} {p_name:<12} : {count}")

    platforms_str = "\n".join(platform_lines)

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
        "───────────────\n\n"
        f"⏰ <b>وقت التشغيل:</b> {days} يوم {hours} ساعة {minutes} دقيقة\n"
        "🔄 <b>تحديث الإحصائيات:</b> كل 100 حدث أو عند الإيقاف"
    )

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("تحديث 🔄", callback_data="refresh_stats")]])
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

# ================== المعالجة والضغط الفائق السرعة ==================

# مجموعة User-Agents حديثة يتم التبديل بينها عشوائياً لتقليل احتمال الحظر من المنصات
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36',
]

# رسائل أخطاء تدل على أن الفيديو محمي/محذوف/خاص بشكل نهائي، لا فائدة من إعادة المحاولة معها
NON_RETRYABLE_MARKERS = [
    "private video", "private account", "this video is unavailable", "video unavailable",
    "sign in to confirm your age", "account has been terminated", "video has been removed",
    "requires payment", "this content isn't available", "content isn't available",
    "login required", "who has restricted", "unable to find video", "no video formats found",
    "unsupported url", "copyright", "not available in your country",
]

def _get_common_ydl_opts():
    """خيارات مشتركة تُستخدم في كل عمليات yt-dlp لتقليل نسبة الفشل والحظر."""
    return {
        'quiet': True,
        'no_warnings': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'noplaylist': True,
        'check_formats': False,
        'socket_timeout': 20,
        'retries': 5,
        'fragment_retries': 5,
        'extractor_retries': 3,
        # تحميل عدة أجزاء (fragments) بالتوازي يسرّع التحميل فعلياً لأنه اختناق شبكة
        # وليس معالج (I/O-bound)، فهذا آمن تماماً ولا يرهق CPU/RAM على السيرفر المجاني
        'concurrent_fragment_downloads': 4,
        'user_agent': random.choice(USER_AGENTS),
        'extractor_args': {
            # ترتيب عملاء يوتيوب يقلل من ظهور رسالة "Sign in to confirm you're not a bot"
            # ملاحظة: بعض المقاطع أصبحت يوتيوب تفرض عليها تسجيل دخول إجباري من جهتها
            # ولا يوجد حل 100% بدون كوكيز لتلك الحالات تحديداً مهما كانت الإعدادات.
            'youtube': {
                'player_client': ['android', 'ios', 'tv_embedded', 'web_safari'],
                'player_skip': ['webpage', 'configs'],
            },
            'tiktok': {'app_info': ['7355728856979712262']},
        },
    }

def _blocking_extract_info(url):
    opts = _get_common_ydl_opts()
    opts['socket_timeout'] = 15
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def _blocking_download(url, opts):
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def _compress_video_sync(input_file, output_file):
    # خوارزمية ضغط مُصممة خصيصاً للسيرفرات الضعيفة لمنع التعليق
    cmd = [
        'ffmpeg', '-y', '-i', input_file, 
        '-c:v', 'libx264', 
        '-preset', 'ultrafast',   # أسرع وضع لعدم خنق المعالج (كان faster وهذا ما سبب التعليق)
        '-threads', '1',          # إجبار الخادم على مسار واحد لمنع انهيار الرام
        '-crf', '35',             # ضغط قاسي لتقليل الحجم
        '-vf', "scale='min(480,iw)':-2", # تصغير إلى 480p لسرعة المعالجة
        '-r', '24',               # تقليل الإطارات لتخفيف العبء
        '-c:a', 'aac', '-b:a', '64k',
        output_file
    ]
    try:
        # مهلة 3 دقائق، لو تأخر أكثر سيتم قتله ليتحرر البوت بدلاً من التعليق الأبدي
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=180)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            return output_file
    except subprocess.TimeoutExpired:
        pass # تم تجاوز الوقت المحدد
    except Exception:
        pass # حدث خطأ أو FFMPEG غير مثبت
    return input_file

def _faststart_remux_sync(input_file, output_file):
    """
    يعيد ترتيب هيكل حاوية mp4 بحيث توضع بيانات moov في البداية (faststart).
    هذا لا يعيد ترميز الفيديو إطلاقاً (-c copy = نسخ سريع جداً بدون أي عبء على المعالج)،
    لكنه يحل مشكلة شائعة جداً: فيديوهات (خصوصاً من إنستغرام) لا تُحفظ بشكل سليم في معرض
    الهاتف أو تظهر "تالفة" لأن بيانات moov موجودة بنهاية الملف بدل بدايته.
    """
    cmd = [
        'ffmpeg', '-y', '-i', input_file,
        '-c', 'copy',
        '-movflags', '+faststart',
        '-threads', '1',
        output_file
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=60)
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            return output_file
    except Exception:
        pass
    return input_file

def _probe_video_metadata_sync(input_file):
    """
    يجلب المدة/العرض/الارتفاع بسرعة عبر ffprobe لتمريرها لتيليجرام مع الفيديو.
    تزويد تيليجرام بهذه البيانات مسبقاً يسرّع عرض المقطع وبدء التشغيل عند المستلم
    بدل ما يضطر تطبيق تيليجرام لتحليلها بنفسه بعد اكتمال الرفع.
    """
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height:format=duration',
            '-of', 'json', input_file
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        data = json.loads(result.stdout.decode())
        width = data.get('streams', [{}])[0].get('width')
        height = data.get('streams', [{}])[0].get('height')
        duration = data.get('format', {}).get('duration')
        return (
            int(float(duration)) if duration else None,
            int(width) if width else None,
            int(height) if height else None,
        )
    except Exception:
        return None, None, None

# ================== استقبال الرسائل والبدء ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("اشترك في القناة 📡", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton("تحقق 🔍", callback_data="check_sub")]
        ])
        await update.message.reply_text("🚧 عذراً، يجب الاشتراك بالقناة أولاً لاستخدام البوت.", reply_markup=markup)
        return

    await update.message.reply_text(f"أهلاً بك <b>{user.first_name}</b> في محرك @ZenDown_Bot الذكي! 🚀\nأرسل رابطاً للتحميل، أو اكتب نصاً للبحث المباشر.", parse_mode="HTML")

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    # ملاحظة: لا يمكن استدعاء q.answer() أكثر من مرة واحدة لكل ضغطة زر،
    # لذلك نتحقق أولاً من حالة الاشتراك ثم نستدعي answer() مرة واحدة فقط بالشكل المناسب.
    if await check_user_subscription(context.bot, q.from_user.id):
        await q.answer("✅ تم التحقق بنجاح!")
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.reply_text("✅ تم التحقق! أرسل رابطك أو كلمة البحث الآن.")
    else:
        # فقط تنبيه منبثق (Popup) بدون أي رسالة إضافية داخل المحادثة
        await q.answer("❌ لم تشترك بالقناة بعد!", show_alert=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    track_user_activity(user.id)

    if not await check_user_subscription(context.bot, user.id):
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("اشترك في القناة 📡", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
            [InlineKeyboardButton("تحقق 🔍", callback_data="check_sub")]
        ])
        await update.message.reply_text("🚧 يرجى الاشتراك في القناة أولاً.", reply_markup=markup)
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
        await perform_youtube_search(update, context, text)

# ================== البحث المباشر ==================
def format_duration(seconds):
    if not seconds: return "0:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0: return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def format_views(views):
    if not views: return "غير معروف"
    if views >= 1_000_000:
        return f"{views/1_000_000:.1f}M".replace('.0M', 'M')
    return str(views)

def build_search_page(sid, page):
    data = SEARCH_CACHE.get(sid)
    if not data:
        return "❌ انتهت صلاحية البحث، الرجاء البحث من جديد.", None
    
    entries = data['entries']
    query = data['query']
    total = len(entries)
    
    start_idx = page * 5
    end_idx = start_idx + 5
    page_entries = entries[start_idx:end_idx]
    
    lines = [f"🔍 نتائج بحث اليوتيوب لـ \"{query}\"\n"]
    for entry in page_entries:
        title = entry.get('title', 'بدون عنوان')
        uploader = entry.get('uploader') or entry.get('channel', 'غير معروف')
        duration = format_duration(entry.get('duration', 0))
        views = format_views(entry.get('view_count'))
        vid = entry.get('id', '')
        
        lines.append(f"🎬 {title}\n👤 {uploader}\n⏱ {duration} - 👁 {views}\n🔗 /dl_{vid}\n")
    
    text = "\n".join(lines)
    
    buttons = []
    if end_idx < total:
        buttons.append(InlineKeyboardButton("التالي »", callback_data=f"page_{sid}_{page+1}"))
    if page > 0:
        buttons.append(InlineKeyboardButton("« السابق", callback_data=f"page_{sid}_{page-1}"))

    markup = InlineKeyboardMarkup([buttons]) if buttons else None
    return text, markup

async def perform_youtube_search(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str):
    msg = await update.message.reply_text(f"🔍 جاري البحث الذكي عن: <b>{query}</b>...", parse_mode="HTML")
    
    def _search():
        opts = {'extract_flat': True, 'quiet': True, 'default_search': 'ytsearch20'}
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(f"ytsearch20:{query}", download=False).get('entries', [])

    try:
        entries = await asyncio.to_thread(_search)
    except Exception:
        await msg.edit_text("❌ حدث خطأ أثناء تنفيذ البحث.")
        return

    if not entries:
        await msg.edit_text("❌ لم يتم العثور على نتائج.")
        return

    sid = str(uuid.uuid4())[:8]
    cache_search(sid, {'query': query, 'entries': entries})
    
    text, markup = build_search_page(sid, 0)
    await msg.edit_text(text, parse_mode="HTML", reply_markup=markup)

async def search_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    parts = q.data.split("_")
    sid = parts[1]
    page = int(parts[2])
    
    text, markup = build_search_page(sid, page)
    if "انتهت صلاحية" in text:
        await q.message.edit_text(text)
        return
        
    await q.message.edit_text(text, parse_mode="HTML", reply_markup=markup)

# ================== جلب معلومات الرابط ==================
async def process_link_info(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    msg = await update.message.reply_text("⚡️ جاري تحليل الرابط...")
    
    title = None
    uploader = 'غير معروف'
    thumbnail = None

    try:
        info = await asyncio.to_thread(_blocking_extract_info, url)
        title = info.get('title')
        uploader = info.get('uploader', 'غير معروف')
        thumbnail = info.get('thumbnail')
    except Exception as e:
        try:
            req = urllib.request.Request(f"https://www.youtube.com/oembed?url={url}&format=json", headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
                title = data.get('title')
                uploader = data.get('author_name', 'غير معروف')
                thumbnail = data.get('thumbnail_url')
        except Exception:
            pass

    if not title:
        title = "مقطع وسائط (جاهز للتحميل)"
        uploader = "الرابط المرفق"

    sid = str(uuid.uuid4())[:8]
    cache_url(sid, url)

    caption = f"🎬 <b>{title}</b>\n👤 المصدر: {uploader}"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎥 فيديو MP4", callback_data=f"down_vid_{sid}")],
        [InlineKeyboardButton("🎵 صوت MP3", callback_data=f"down_aud_{sid}"),
         InlineKeyboardButton("🎙 بصمة صوتية", callback_data=f"down_voc_{sid}")]
    ])

    await msg.delete()
    if thumbnail:
        try:
            await update.message.reply_photo(photo=thumbnail, caption=caption, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await update.message.reply_text(caption, parse_mode="HTML", reply_markup=markup)
    else:
        await update.message.reply_text(caption, parse_mode="HTML", reply_markup=markup)

# ================== التحميل الذكي المحسّن والجدار الأمني ==================
async def download_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    
    _, action, sid = q.data.split("_")
    url = URL_CACHE.get(sid)
    
    if not url:
        await q.message.reply_text("❌ انتهت صلاحية هذه الجلسة، أعد إرسال الرابط.")
        return

    status_msg = await q.message.reply_text("⏳ أضيفت إلى طابور التحميل الذكي...")
    
    async with DOWNLOAD_SEMAPHORE:
        await status_msg.edit_text("🚀 جاري التحميل والمعالجة السريعة...")
        out_tmpl = f"zendown_{sid}.%(ext)s"
        
        if action == "vid":
            opts = _get_common_ydl_opts()
            opts.update({
                # الأولوية دائماً لترميز H.264 (avc1) + AAC (m4a) لأنه المتوافق 100% مع
                # معارض الصور بكل أنواع الهواتف. الخيارات الأخيرة (bv*+ba/b) احتياطية فقط
                # لحالات نادرة مثل سلايدشو تيك توك، لتفادي الكراش بدون التضحية بالتوافقية.
                'format': (
                    'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[acodec^=mp4a][ext=m4a]/'
                    'best[vcodec^=avc1][ext=mp4]/'
                    'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/'
                    'bv*+ba/b'
                ),
                'outtmpl': out_tmpl,
                'merge_output_format': 'mp4',
            })
        elif action == "aud":
            opts = _get_common_ydl_opts()
            opts.update({
                'format': 'bestaudio/best',
                'outtmpl': out_tmpl,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            })
        else:
            opts = _get_common_ydl_opts()
            opts.update({
                'format': 'bestaudio/best',
                'outtmpl': out_tmpl,
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'vorbis'}],
            })

        file_path = None
        downloaded_path = None  # يحتفظ بمسار الملف الأصلي كما هو حتى لو تغيّر file_path لاحقاً بعد الضغط
        temp_paths = set()  # كل نسخة وسيطة (مضغوطة/معاد ترتيبها) تُسجّل هنا لضمان حذفها لاحقاً
        max_retries = 3
        success_download = False
        last_error = None

        for attempt in range(max_retries):
            try:
                file_path = await asyncio.to_thread(_blocking_download, url, opts)
                if action == "aud": file_path = file_path.rsplit('.', 1)[0] + '.mp3'
                if action == "voc": file_path = file_path.rsplit('.', 1)[0] + '.ogg'
                
                if os.path.exists(file_path):
                    downloaded_path = file_path
                    success_download = True
                    break
            except Exception as e:
                last_error = str(e)
                err_str = last_error.lower()
                logger.error(f"Attempt {attempt + 1} failed: {e}")

                # لو الخطأ يدل على أن الفيديو محمي/خاص/محذوف نهائياً، لا فائدة من إعادة المحاولة
                if any(marker in err_str for marker in NON_RETRYABLE_MARKERS):
                    break

                if attempt < max_retries - 1:
                    await status_msg.edit_text(f"⚠️ جاري المحاولة مرة أخرى ({attempt + 2}/{max_retries})...")
                    await asyncio.sleep(2) 
                else:
                    pass

        duration = width = height = None

        try:
            if success_download and file_path and os.path.exists(file_path):
                
                # إعادة ترتيب حاوية mp4 (faststart) لكل فيديو — نسخ سريع بدون إعادة ترميز،
                # يحل مشكلة عدم حفظ المقطع بشكل سليم في معرض الهاتف (خصوصاً إنستغرام)
                if action == "vid":
                    fs_path = file_path.rsplit('.', 1)[0] + '_fs.mp4'
                    remuxed = await asyncio.to_thread(_faststart_remux_sync, file_path, fs_path)
                    if remuxed != file_path:
                        temp_paths.add(remuxed)
                        file_path = remuxed

                # مرحلة الضغط
                if action == "vid" and (os.path.getsize(file_path) / (1024*1024)) > 45:
                    await status_msg.edit_text("🗜 حجم المقطع كبير.. جاري الضغط السريع (قد يستغرق دقيقتين)...")
                    comp_path = file_path.rsplit('.', 1)[0] + '_c.mp4'
                    compressed = await asyncio.to_thread(_compress_video_sync, file_path, comp_path)
                    if compressed != file_path:
                        temp_paths.add(compressed)
                        file_path = compressed

                # جدار حماية تيليجرام: فحص الحجم النهائي لمنع التعليق الوهمي أثناء الرفع
                final_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                if final_size_mb >= 49.5:
                    await status_msg.edit_text(f"❌ عذراً، المقطع كبير جداً ({final_size_mb:.1f} ميجا). الحد الأقصى للبوتات هو 50 ميجا.")
                    track_download_status(False)
                    return # نخرج من العملية فوراً

                # جلب المدة/الأبعاد لتسريع عرض المقطع عند المستلم (اختياري، بدون تعطيل الإرسال لو فشل)
                if action == "vid":
                    duration, width, height = await asyncio.to_thread(_probe_video_metadata_sync, file_path)

                await status_msg.edit_text("📤 جاري إرسال الملف...")
                with open(file_path, 'rb') as f:
                    if action == "vid":
                        await q.message.reply_video(
                            video=f, caption="🎬 تم بواسطة @ZenDown_Bot", supports_streaming=True,
                            duration=duration, width=width, height=height,
                        )
                    elif action == "aud": await q.message.reply_audio(audio=f, caption="🎵 تم بواسطة @ZenDown_Bot")
                    elif action == "voc": await q.message.reply_voice(voice=f, caption="🎙 تم بواسطة @ZenDown_Bot")

                track_download_status(True)
                await status_msg.delete()
            else:
                track_download_status(False)
                if q.from_user.id == ADMIN_ID and last_error:
                    # للأدمن فقط: نعرض نص الخطأ الحقيقي القادم من yt-dlp عشان نشخص بدقة بدل التخمين
                    short_err = last_error[:350]
                    await status_msg.edit_text(f"❌ فشل التحميل.\n\n🔧 تفاصيل تقنية (للأدمن فقط):\n<code>{short_err}</code>", parse_mode="HTML")
                else:
                    await status_msg.edit_text("❌ حدث خطأ أثناء التحميل، قد يكون المقطع محمي كلياً أو يحتاج تسجيلاً إجبارياً.")
        except Exception as e:
            logger.error(f"Send Error: {e}")
            track_download_status(False)
            await status_msg.edit_text("❌ حدث خطأ أثناء معالجة وإرسال الملف.")
        finally:
            # نحذف الملف الأصلي وكل نسخة وسيطة (معاد ترتيبها/مضغوطة) لمنع تراكم الملفات على القرص
            paths_to_clean = {p for p in ({file_path, downloaded_path} | temp_paths) if p}
            for p in paths_to_clean:
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass

# ================== التشغيل الرئيسي ==================
def main():
    # مهلات أطول من الافتراضي لضمان اكتمال رفع الفيديوهات الكبيرة دون فشل/انقطاع مبكر
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .concurrent_updates(True)
        .connect_timeout(20)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(20)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(search_page_callback, pattern="^page_")) 
    
    app.add_handler(CommandHandler("stats", show_stats_command))
    app.add_handler(MessageHandler(filters.Regex(r"^(احصائيات|إحصائيات)$"), show_stats_command))
    app.add_handler(CallbackQueryHandler(show_stats_command, pattern="^refresh_stats$"))

    app.add_handler(CallbackQueryHandler(download_action_callback, pattern="^down_"))
    app.add_handler(MessageHandler(filters.Regex(r"^/dl_"), handle_message))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    print("🚀 تم تشغيل محرك @ZenDown_Bot بنجاح! مزود بحماية الـ OOM والجدار الأمني لتيليجرام.")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()








