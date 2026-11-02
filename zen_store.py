"""
zen_store.py — طبقة التخزين الدائم لبوت ZenDown (Turso) — معزولة عن ملف البوت.

القواعد:
  • هذا الملف هو الوحيد الذي يتحدث مع قاعدة البيانات.
  • لا يوجد فيه أي DROP أو DELETE على بيانات المستخدمين، ولا أي استبدال للجداول.
  • الإقلاع: CREATE TABLE IF NOT EXISTS فقط. القراءة قبل أي كتابة، والكتابة بـ UPSERT.
  • الحارس يرفض أي حفظ ينقص المستخدمين فجأة.
يجب أن يكون هذا الملف بجانب ZenDown_bot (نفس المجلد في GitHub).
"""
import os, json, time, uuid, asyncio, gzip, base64, logging
from datetime import datetime, timedelta

stats = None
logger = logging.getLogger("ZenStore")
ADMIN_ID = 0
get_setting = lambda k: ""
save_stats = lambda: None
URL_CACHE = {}
_empty_platform_stats = lambda: {}

def configure(*, stats_ref, logger_ref, admin_id, get_setting_fn, save_stats_fn, url_cache, empty_platform_stats_fn):
    """يربط الطبقة بحالة البوت (يُستدعى مرة واحدة عند الإقلاع قبل أي شيء)."""
    global stats, logger, ADMIN_ID, get_setting, save_stats, URL_CACHE, _empty_platform_stats
    stats, logger, ADMIN_ID = stats_ref, logger_ref, admin_id
    get_setting, save_stats, URL_CACHE = get_setting_fn, save_stats_fn, url_cache
    _empty_platform_stats = empty_platform_stats_fn

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

# ================== حماية البيانات (Fail-Safe) ==================
# المبادئ:
#  1) لا نكتب أي شيء في Turso قبل ما نقرأ النسخة المحفوظة بنجاح.
#  2) المستخدمون والمشتركون في جداول مستقلة تُحدَّث بـ UPSERT فقط (لا حذف، لا استبدال شامل).
#  3) حارس: أي حفظ يقلّل المستخدمين فجأة (<70% من أعلى عدد شوهد) يُرفض + تنبيه للأدمن.
#  4) لقطات تاريخية داخل Turso (كل 30 دقيقة + يومية) + نسخة احتياطية تُرسل لتيليجرام كل 12 ساعة.
#  5) الدمج (استعادة/تحميل) إضافي فقط: يأخذ الأكبر ولا ينقص أي شيء.
import gzip, base64
TURSO_LOADED = False
MAX_SEEN_USERS = 0
GUARD_RATIO = 0.7
DIRTY_USERS = set()
BOOT_ID = uuid.uuid4().hex[:6]
BOT_REF = {"bot": None}
_LAST_SNAPSHOT_TS = 0.0
_ALERT_TS = {}
_MULTI_COUNT = 0

def _tclient():
    return libsql_client.create_client(url=TURSO_HTTP_URL, auth_token=TURSO_AUTH_TOKEN)

async def _ensure_tables(client):
    for q in (
        "CREATE TABLE IF NOT EXISTS bot_state (id INTEGER PRIMARY KEY, data TEXT, updated_at TEXT)",
        "CREATE TABLE IF NOT EXISTS bot_users (uid TEXT PRIMARY KEY, last_seen TEXT, joined TEXT)",
        "CREATE TABLE IF NOT EXISTS bot_premium (uid TEXT PRIMARY KEY, expires TEXT)",
        "CREATE TABLE IF NOT EXISTS bot_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, users_count INTEGER, data TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS url_sessions (sid TEXT PRIMARY KEY, url TEXT, created_at TEXT)",
        "CREATE TABLE IF NOT EXISTS bot_instances (boot_id TEXT PRIMARY KEY, started TEXT, last_beat TEXT)",
    ):
        await client.execute(q)

async def _alert_admin(key, text, every=3600):
    """تنبيه للأدمن على تيليجرام (مرة كل ساعة كحد أقصى لكل نوع)."""
    now = time.time()
    if now - _ALERT_TS.get(key, 0) < every:
        return
    _ALERT_TS[key] = now
    bot = BOT_REF.get("bot")
    if bot:
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=text)
        except Exception as e:
            logger.error(f"alert_admin failed: {e}")

def _merge_val(a, b):
    if a is None:
        return b
    if isinstance(a, dict) and isinstance(b, dict):
        for k, v in b.items():
            a[k] = _merge_val(a.get(k), v)
        return a
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num) and not isinstance(a, bool) and not isinstance(b, bool):
        return max(a, b)
    return a

def merge_state(saved: dict) -> int:
    """دمج إضافي فقط: لا يحذف ولا ينقص شيئاً. يرجّع عدد المستخدمين الجدد."""
    added = 0
    users = stats.setdefault("users", {})
    for uid, ts in (saved.get("users") or {}).items():
        cur = users.get(uid)
        if cur is None:
            users[uid] = ts
            added += 1
            DIRTY_USERS.add(uid)
        elif ts and str(ts) > str(cur):
            users[uid] = ts
    prem = stats.setdefault("premium", {})
    for uid, exp in (saved.get("premium") or {}).items():
        if str(exp) > str(prem.get(uid, "")):
            prem[uid] = exp
    for k, v in saved.items():
        if k in ("users", "premium"):
            continue
        stats[k] = _merge_val(stats.get(k), v)
    return added

def _pack_stats() -> str:
    return base64.b64encode(gzip.compress(json.dumps(stats, ensure_ascii=False).encode("utf-8"))).decode()

def _unpack_stats(blob: str) -> dict:
    return json.loads(gzip.decompress(base64.b64decode(blob)).decode("utf-8"))

async def _turso_load_once():
    """يقرأ كل المصادر المحفوظة ويدمجها (إضافياً). لا يضع TURSO_LOADED=True إلا بعد نجاح كامل."""
    global TURSO_LOADED, MAX_SEEN_USERS
    async with _tclient() as client:
        await _ensure_tables(client)
        rs = await client.execute("SELECT data FROM bot_state WHERE id = 1")
        if rs.rows:
            merge_state(json.loads(rs.rows[0][0]))
        known = set()
        rs = await client.execute("SELECT uid, last_seen, joined FROM bot_users")
        for r in rs.rows:
            uid, last_seen, joined = r[0], r[1], r[2]
            known.add(uid)
            cur = stats["users"].get(uid)
            if cur is None or (last_seen and str(last_seen) > str(cur)):
                stats["users"][uid] = last_seen
            profs = stats.setdefault("user_profiles", {})
            if uid not in profs and joined:
                profs[uid] = {"joined": joined, "total_downloads": 0, "platforms": {}}
        rs = await client.execute("SELECT uid, expires FROM bot_premium")
        for r in rs.rows:
            stats.setdefault("premium", {})[r[0]] = r[1]
        now = datetime.now().isoformat()
        await client.execute("INSERT OR REPLACE INTO bot_instances (boot_id, started, last_beat) VALUES (?, ?, ?)", [BOOT_ID, now, now])
    stats.setdefault("platform_stats", _empty_platform_stats())
    DIRTY_USERS.update(set(stats["users"].keys()) - known)   # اللي ناقص من الجدول المستقل نكمّله
    MAX_SEEN_USERS = max(MAX_SEEN_USERS, len(stats["users"]))
    TURSO_LOADED = True
    logger.info(f"✅ Turso: تم تحميل البيانات المحفوظة ({len(stats['users'])} مستخدم) | BOOT={BOOT_ID}")
    return True

async def turso_load_on_startup():
    """يحمّل آخر نسخة محفوظة عند إقلاع البوت (مع إعادة محاولة)."""
    if not TURSO_ENABLED:
        return
    for attempt in range(1, 6):
        try:
            await _turso_load_once()
            return
        except Exception as e:
            logger.error(f"Turso load failed (محاولة {attempt}/5): {e}")
            await asyncio.sleep(3)
    logger.error("🛑 Turso: فشل تحميل البيانات المحفوظة! تم إيقاف الحفظ التلقائي حتى لا تُمسح النسخة القديمة.")

async def turso_push_now(snapshot=False):
    """يحفظ الحالة الحالية. محمي: لا يكتب قبل نجاح التحميل، ويرفض أي نقص مفاجئ في المستخدمين."""
    global MAX_SEEN_USERS, _LAST_SNAPSHOT_TS
    if not TURSO_ENABLED:
        return
    if not TURSO_LOADED:
        try:
            await _turso_load_once()
        except Exception as e:
            logger.error(f"Turso push skipped (البيانات المحفوظة غير مقروءة بعد): {e}")
            return
    n = len(stats.get("users", {}))
    if MAX_SEEN_USERS >= 200 and n < MAX_SEEN_USERS * GUARD_RATIO:
        logger.error(f"🛑 حارس البيانات: المستخدمون {n} أقل بكثير من {MAX_SEEN_USERS} - رُفض الحفظ.")
        await _alert_admin("data_guard",
            f"🛑 حارس البيانات منع حفظاً مشبوهاً: المستخدمون الآن {n} مقابل {MAX_SEEN_USERS}.\n"
            "لم يُكتب شيء في قاعدة البيانات. افتح /admin ← 🗂 اللقطات للاستعادة.")
        return
    try:
        async with _tclient() as client:
            # 1) المستخدمون: UPSERT للمتغيّرين فقط (إضافة/تحديث، لا حذف أبداً)
            batch = list(DIRTY_USERS)[:3000]
            profs = stats.get("user_profiles", {})
            for i in range(0, len(batch), 100):
                chunk = batch[i:i + 100]
                sql = ("INSERT INTO bot_users (uid, last_seen, joined) VALUES " + ",".join(["(?,?,?)"] * len(chunk)) +
                       " ON CONFLICT(uid) DO UPDATE SET last_seen = excluded.last_seen")
                args = []
                for uid in chunk:
                    args += [uid, stats["users"].get(uid), (profs.get(uid) or {}).get("joined")]
                await client.execute(sql, args)
                DIRTY_USERS.difference_update(chunk)
            # 2) المشتركون (كلهم، عددهم صغير)
            prem = list(stats.get("premium", {}).items())
            for i in range(0, len(prem), 100):
                chunk = prem[i:i + 100]
                sql = ("INSERT INTO bot_premium (uid, expires) VALUES " + ",".join(["(?,?)"] * len(chunk)) +
                       " ON CONFLICT(uid) DO UPDATE SET expires = excluded.expires")
                args = []
                for uid, exp in chunk:
                    args += [uid, exp]
                await client.execute(sql, args)
            # 3) الحالة العامة
            await client.execute(
                "INSERT INTO bot_state (id, data, updated_at) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                [json.dumps(stats if DIRTY_USERS else {k: v for k, v in stats.items() if k not in ("users", "premium")}, ensure_ascii=False),
                 datetime.now().isoformat()])
            # 4) لقطات تاريخية
            now_ts = time.time()
            if snapshot or now_ts - _LAST_SNAPSHOT_TS > 1800:
                _LAST_SNAPSHOT_TS = now_ts
                blob = _pack_stats()
                iso = datetime.now().isoformat()
                await client.execute("INSERT INTO bot_snapshots (kind, users_count, data, created_at) VALUES ('auto', ?, ?, ?)", [n, blob, iso])
                await client.execute("DELETE FROM bot_snapshots WHERE kind='auto' AND id NOT IN "
                                     "(SELECT id FROM bot_snapshots WHERE kind='auto' ORDER BY id DESC LIMIT 48)")
                today = iso[:10]
                rs = await client.execute("SELECT count(*) FROM bot_snapshots WHERE kind='daily' AND created_at >= ?", [today])
                if int(rs.rows[0][0]) == 0:
                    await client.execute("INSERT INTO bot_snapshots (kind, users_count, data, created_at) VALUES ('daily', ?, ?, ?)", [n, blob, iso])
                    await client.execute("DELETE FROM bot_snapshots WHERE kind='daily' AND id NOT IN "
                                         "(SELECT id FROM bot_snapshots WHERE kind='daily' ORDER BY id DESC LIMIT 14)")
        MAX_SEEN_USERS = max(MAX_SEEN_USERS, n)
    except Exception as e:
        logger.error(f"Turso sync failed: {e}")

async def _heartbeat():
    """نبض + كشف تشغيل أكثر من نسخة من البوت معاً (سبب شائع لموت الأزرار وتخبط البيانات)."""
    global _MULTI_COUNT
    try:
        async with _tclient() as client:
            now = datetime.now()
            await client.execute("UPDATE bot_instances SET last_beat = ? WHERE boot_id = ?", [now.isoformat(), BOOT_ID])
            rs = await client.execute("SELECT boot_id FROM bot_instances WHERE last_beat > ?", [(now - timedelta(seconds=90)).isoformat()])
            ids = [r[0] for r in rs.rows]
            await client.execute("DELETE FROM bot_instances WHERE last_beat < ?", [(now - timedelta(days=3)).isoformat()])
        if len(ids) > 1:
            _MULTI_COUNT += 1
            if _MULTI_COUNT >= 3:
                logger.error(f"⚠️ تعمل أكثر من نسخة من البوت معاً: {ids}")
                await _alert_admin("multi_instance",
                    f"⚠️ اكتشفت أن أكثر من نسخة من البوت تعمل معاً ({', '.join(ids)}).\n"
                    "هذا يسبب موت الأزرار وتخبط البيانات. أوقف أي خدمة Render أخرى تستخدم نفس التوكن.", every=1800)
        else:
            _MULTI_COUNT = 0
    except Exception as e:
        logger.error(f"heartbeat failed: {e}")

async def count_boots_24h() -> int:
    if not TURSO_ENABLED:
        return -1
    try:
        async with _tclient() as client:
            rs = await client.execute("SELECT count(*) FROM bot_instances WHERE started > ?", [(datetime.now() - timedelta(hours=24)).isoformat()])
            return int(rs.rows[0][0])
    except Exception:
        return -1

async def turso_sync_loop():
    """كل 20 ثانية: حفظ آمن + نبض. كل ساعة: تنظيف جلسات الأزرار القديمة."""
    if not TURSO_ENABLED:
        return
    cycle = 0
    while True:
        await asyncio.sleep(20)
        cycle += 1
        await turso_push_now()
        await _heartbeat()
        if cycle % 180 == 0:
            try:
                async with _tclient() as client:
                    await client.execute("DELETE FROM url_sessions WHERE created_at < ?", [(datetime.now() - timedelta(days=2)).isoformat()])
            except Exception as e:
                logger.error(f"session cleanup failed: {e}")

# ---------- جلسات الأزرار تتحمل إعادة التشغيل ----------
async def url_put(sid, url):
    if not TURSO_ENABLED:
        return
    try:
        async with _tclient() as client:
            await client.execute("INSERT OR REPLACE INTO url_sessions (sid, url, created_at) VALUES (?, ?, ?)", [sid, url, datetime.now().isoformat()])
    except Exception as e:
        logger.error(f"url_put failed: {e}")

async def get_session_url(sid):
    u = URL_CACHE.get(sid)
    if u:
        return u
    if TURSO_ENABLED:
        try:
            async with _tclient() as client:
                rs = await client.execute("SELECT url FROM url_sessions WHERE sid = ?", [sid])
                if rs.rows:
                    u = rs.rows[0][0]
                    URL_CACHE[sid] = u
                    return u
        except Exception as e:
            logger.error(f"url_get failed: {e}")
    return None

# ---------- نسخة احتياطية على تيليجرام + استعادة ----------
async def send_backup(bot, reason="تلقائية"):
    n = len(stats.get("users", {}))
    if MAX_SEEN_USERS >= 200 and n < MAX_SEEN_USERS * GUARD_RATIO:
        await _alert_admin("backup_skip", f"⚠️ تخطيت النسخة الاحتياطية لأن عدد المستخدمين ({n}) أقل بكثير من المعتاد ({MAX_SEEN_USERS}).")
        return False
    import io
    data = gzip.compress(json.dumps(stats, ensure_ascii=False).encode("utf-8"))
    name = f"zendown_backup_{datetime.now():%Y%m%d_%H%M}_{n}users.json.gz"
    caption = (f"💾 نسخة احتياطية ({reason})\n👥 {n} مستخدم\n"
               "للاستعادة: أرسل هذا الملف للبوت في الخاص مع كلمة restore في التعليق.")
    targets = [ADMIN_ID]
    ch = str(get_setting("backup_chat") or "").strip()
    if ch:
        try:
            targets.insert(0, int(ch))
        except ValueError:
            pass
    ok = False
    for t in targets:
        try:
            await bot.send_document(chat_id=t, document=io.BytesIO(data), filename=name, caption=caption)
            ok = True
        except Exception as e:
            logger.error(f"backup send to {t} failed: {e}")
            if t != ADMIN_ID:
                await _alert_admin("bk_chan", f"⚠️ تعذر إرسال النسخة لقناة النسخ ({t}): {str(e)[:150]}\nتأكد أن البوت مشرف في القناة.", every=21600)
    if ok:
        stats["last_backup_ts"] = time.time()
    return ok

async def backup_loop():
    """نسخة كاملة كل 24 ساعة (الوقت الأخير محفوظ، فإعادة تشغيل Render لا تكرر ولا تفوّت)."""
    await asyncio.sleep(120)
    while True:
        try:
            if (TURSO_LOADED or not TURSO_ENABLED) and time.time() - float(stats.get("last_backup_ts", 0)) >= 24 * 3600:
                await send_backup(BOT_REF["bot"], "تلقائية كل 24 ساعة")
        except Exception as e:
            logger.error(f"backup_loop failed: {e}")
        await asyncio.sleep(600)

async def list_snapshots(limit=10):
    async with _tclient() as client:
        rs = await client.execute("SELECT id, kind, users_count, created_at FROM bot_snapshots ORDER BY id DESC LIMIT ?", [limit])
        return [(r[0], r[1], r[2], r[3]) for r in rs.rows]

async def restore_snapshot(snap_id):
    async with _tclient() as client:
        rs = await client.execute("SELECT data FROM bot_snapshots WHERE id = ?", [snap_id])
        if not rs.rows:
            raise Exception("اللقطة غير موجودة")
        saved = _unpack_stats(rs.rows[0][0])
    global MAX_SEEN_USERS
    before = len(stats.get("users", {}))
    added = merge_state(saved)
    MAX_SEEN_USERS = max(MAX_SEEN_USERS, len(stats["users"]))
    save_stats()
    await turso_push_now(snapshot=True)
    return before, added, len(stats["users"])


async def restore_from_bytes(raw: bytes):
    """استعادة من ملف نسخة (gzip أو JSON). دمج إضافي فقط. يرجّع (قبل، جدد، الآن)."""
    global MAX_SEEN_USERS
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    saved = json.loads(raw.decode("utf-8"))
    before = len(stats.get("users", {}))
    added = merge_state(saved)
    MAX_SEEN_USERS = max(MAX_SEEN_USERS, len(stats["users"]))
    save_stats()
    await turso_push_now(snapshot=True)
    return before, added, len(stats["users"])
