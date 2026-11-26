"""
ZenDown Mini App — الخلفية (Backend)  — النسخة 2
=================================================
ملف منفصل عن bot.py: يقدّم صفحة التطبيق (webapp.html) + مسارات API، على نفس المنفذ الذي كان
يستخدمه خادم الصحة (Render/UptimeRobot) — فلا مكتبات جديدة ولا خدمة ثانية.

الأمان: كل طلب API يحمل بيانات تيليجرام الموقّعة (initData) ونتحقق من توقيعها بالتوكن.
لا يوجد هنا منطق تحميل/تعديل/اشتراك خاص: نستدعي نفس دوال bot.py الموجودة (نفس الطابور، نفس حصة Pro).
"""
import os
import re
import json
import time
import gzip
import hmac
import uuid
import base64
import hashlib
import asyncio
import logging
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qsl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("ZenDown_WebApp")

HERE = os.path.dirname(os.path.abspath(__file__))
HTML_PATH = os.path.join(HERE, "webapp.html")

# يُملأ من bot.py عند الإقلاع
B = None                # وحدة bot.py نفسها
TOKEN = None
ADMIN_ID = None
LOOP = None
BOT = None

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_RATE = {}
_LAST_DL = {}
_LAST_EDIT = {}
_LAST_SAVE = {}
_HTML_CACHE = {"mtime": 0, "raw": b"", "gz": b""}
_INV = {}               # (plan, stars, days) -> رابط فاتورة جاهز (الرابط نفسه يصلح لكل المستخدمين)

# ---------- الدفع بـ TON (معطّل افتراضياً: يُفعَّل بمتغير TON_PAY=1 في Render) ----------
TON_ENABLED = os.environ.get("TON_PAY", "0").strip().lower() in ("1", "true", "yes", "on")
TON_ADDRESS = os.environ.get("TON_ADDRESS", "UQC6eepE4FgPUAmv-4B9RpzlP3NvG-t1BtGZMVjvaRZ8-jUH").strip()


def _env_price(name, default):
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


TON_PRICES = {
    "daily": _env_price("TON_PRICE_DAILY", 0.1),
    "weekly": _env_price("TON_PRICE_WEEKLY", 0.3),
    "monthly": _env_price("TON_PRICE_MONTHLY", 1.5),
}


def configure(bot_module, token, admin_id):
    global B, TOKEN, ADMIN_ID
    B, TOKEN, ADMIN_ID = bot_module, token, int(admin_id)


def set_runtime(loop, bot):
    global LOOP, BOT
    LOOP, BOT = loop, bot
    try:  # نجهّز روابط الفواتير مسبقاً حتى يفتح الدفع فوراً عند الضغط
        asyncio.run_coroutine_threadsafe(_warm_invoices(), loop)
    except Exception:
        pass


# ------------------------------------------------------------------ التحقق من هوية المستخدم
def verify_init_data(init_data, token, max_age=86400):
    if not init_data or not token or len(init_data) > 6000:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except Exception:
        return None
    got = pairs.pop("hash", None)
    if not got:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got):
        return None
    try:
        age = time.time() - int(pairs.get("auth_date", "0"))
        if age > max_age or age < -300:
            return None
        user = json.loads(pairs["user"])
        user["id"] = int(user["id"])
        return user
    except Exception:
        return None


def _rate_ok(uid, limit=60, per=60):
    now = time.time()
    if len(_RATE) > 5000:
        _RATE.clear()
    arr = [t for t in _RATE.get(uid, []) if now - t < per]
    if len(arr) >= limit:
        _RATE[uid] = arr
        return False
    arr.append(now)
    _RATE[uid] = arr
    return True


def _run_async(coro, timeout=25):
    if LOOP is None:
        coro.close()
        raise RuntimeError("loop not ready")
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)


def _fire(coro):
    if LOOP is None:
        coro.close()
        raise RuntimeError("loop not ready")
    asyncio.run_coroutine_threadsafe(coro, LOOP)


async def _noop(*a, **k):
    return None


# ------------------------------------------------------------------ إحصائيات التطبيق المصغر
def _app():
    a = B.stats.setdefault("app", {})
    a.setdefault("users", {})
    for k in ("opens", "edits", "downloads", "ton_orders", "ton_claimed", "ton_done"):
        a.setdefault(k, 0)
    return a


def _touch(uid, opened=False):
    """يسجّل دخول/نشاط المستخدم في التطبيق. الحفظ مجمّع في الخلفية، فالنداء رخيص."""
    a = _app()
    now = datetime.now()
    u = a["users"].setdefault(str(uid), {"f": now.isoformat(), "l": now.isoformat(), "n": 0})
    u["l"] = now.isoformat()
    changed = False
    if opened:
        u["n"] = int(u.get("n", 0)) + 1
        a["opens"] += 1
        changed = True
    if changed or time.time() - _LAST_SAVE.get(uid, 0) > 120:
        _LAST_SAVE[uid] = time.time()
        B.save_stats()


def _bump(key, n=1):
    a = _app()
    a[key] = int(a.get(key, 0)) + n
    B.save_stats()


def app_stats_summary():
    """ملخص إحصائيات التطبيق (يُستخدم في لوحة /stats وفي تبويب الإدارة داخل التطبيق)."""
    a = _app()
    now = datetime.now()
    c5 = c1 = c7 = c30 = 0
    for u in a["users"].values():
        try:
            d = now - datetime.fromisoformat(u.get("l", ""))
        except Exception:
            continue
        if d <= timedelta(minutes=5): c5 += 1
        if d <= timedelta(days=1): c1 += 1
        if d <= timedelta(days=7): c7 += 1
        if d <= timedelta(days=30): c30 += 1
    return {
        "total": len(a["users"]), "now": c5, "day": c1, "d7": c7, "d30": c30,
        "opens": a["opens"], "edits": a["edits"], "downloads": a["downloads"],
        "ton_orders": a["ton_orders"], "ton_claimed": a["ton_claimed"], "ton_done": a["ton_done"],
    }


# ------------------------------------------------------------------ الفواتير بالنجوم (جاهزة مسبقاً)
async def _mk_invoice(key):
    plan = B.PLANS[key]
    return await BOT.create_invoice_link(
        title=f"ZenDown Pro — {plan['label']}",
        description=f"اشتراك Pro لمدة {plan['days']} يوم: تخطي الطابور + تعديل المقطع (فلاتر، قص، سرعة، اتجاه).",
        payload=f"plan_{key}",
        currency="XTR",
        prices=[B.LabeledPrice(f"Pro {plan['label']}", int(plan["stars"]))],
    )


async def _all_invoices():
    out = {}
    if not getattr(B, "STARS_PAY", False):
        return out
    for key, plan in B.PLANS.items():
        ck = (key, int(plan["stars"]), int(plan["days"]))
        if ck not in _INV:
            _INV[ck] = await _mk_invoice(key)
        out[key] = _INV[ck]
    return out


async def _warm_invoices():
    try:
        await _all_invoices()
    except Exception as e:
        logger.info(f"invoice warm-up skipped: {e}")


# ------------------------------------------------------------------ المسارات
def _clean_url(raw):
    m = URL_RE.search(str(raw or "").strip()[:2000])
    return m.group(0).rstrip(").,،") if m else None


def _ton_info():
    if not TON_ENABLED:
        return None
    return {"plans": [{"key": k, "ton": TON_PRICES[k]} for k in B.PLANS if k in TON_PRICES]}


def api_me(uid, user, opened=False):
    _touch(uid, opened)
    now = datetime.now()
    exp = B.premium_until(uid)
    pro = None
    if exp:
        info = B.stats.get("pro_info", {}).get(str(uid)) or {}
        plan_key = B._pro_plan_of(uid)
        total_days = info.get("custom_days") or B.PLANS[plan_key]["days"]
        left_days = max(0.0, (exp - now).total_seconds() / 86400)
        pro = {
            "plan": B._plan_label(uid),
            "until": exp.strftime("%Y-%m-%d %H:%M"),
            "left": B._remaining_text(exp),
            "ratio": round(min(1.0, left_days / max(total_days, 1)), 3),
        }
    elif uid == ADMIN_ID:
        pro = {"plan": "المالك", "until": "", "left": "مفتوح دائماً", "ratio": 1.0}
    return {
        "name": user.get("first_name") or "صديقنا",
        "id": uid,
        "admin": uid == ADMIN_ID,
        "maint": bool(B.get_setting("maint")),
        "is_pro": bool(B.is_premium(uid)),
        "pro": pro,
        "trials": int(B.free_trials_left(uid)),
        "plans": ([{"key": k, "label": v["label"], "stars": v["stars"], "days": v["days"]} for k, v in B.PLANS.items()] if getattr(B, "STARS_PAY", False) else []),
        "stars_off": not getattr(B, "STARS_PAY", False),
        "ton": _ton_info(),
        "channel": getattr(B, "CHANNEL", ""),
    }


def api_invoices(uid):
    return 200, {"links": _run_async(_all_invoices(), timeout=25)}


async def _download_job(uid, user, url, kind, sid):
    """يحاكي ضغطة الزر في البوت: نفس دالة التحميل الأصلية بالضبط."""
    try:
        B.URL_CACHE[sid] = url
        B._bg(B.url_put(sid, url))
        anchor = await BOT.send_message(chat_id=uid, parse_mode="HTML",
                                        text="📲 <b>طلب من التطبيق</b>\nجاري التجهيز…")
        q = SimpleNamespace(data=f"down_{kind}_{sid}",
                            from_user=SimpleNamespace(id=uid, first_name=user.get("first_name", "")),
                            message=anchor, answer=_noop)
        await B.download_action_callback(SimpleNamespace(callback_query=q, effective_user=q.from_user), None)
    except Exception as e:
        logger.error(f"webapp download failed for {uid}: {e}")
        try:
            await BOT.send_message(chat_id=uid, text="❌ تعذر تنفيذ الطلب من التطبيق، أرسل الرابط هنا مباشرة وسأحمّله لك.")
        except Exception:
            pass


def _precheck(uid):
    """فحوص مشتركة قبل أي طلب تحميل/تعديل: صيانة + اشتراك القناة. يرجع (code, dict) عند الرفض."""
    if B.get_setting("maint") and uid != ADMIN_ID:
        return 503, {"error": "maint", "message": "البوت تحت الصيانة حالياً، نعود قريباً."}
    if not _run_async(B.check_user_subscription(BOT, uid), timeout=15):
        return 403, {"error": "sub", "message": f"اشترك أولاً في قناة التحديثات {getattr(B, 'CHANNEL', '')} ثم عد للتطبيق."}
    return None


def api_download(uid, user, body):
    url = _clean_url(body.get("url"))
    if not url:
        return 400, {"error": "bad_url", "message": "الرابط غير صحيح، تأكد أنه يبدأ بـ http"}
    kind = body.get("kind", "vid")
    if kind not in ("vid", "aud", "img"):
        kind = "vid"
    bad = _precheck(uid)
    if bad:
        return bad
    now = time.time()
    if len(_LAST_DL) > 5000:
        _LAST_DL.clear()
    if now - _LAST_DL.get(uid, 0) < 4:
        return 429, {"error": "slow", "message": "انتظر ثواني قبل الطلب التالي."}
    B.track_user_activity(uid)
    platform = B.track_platform_request(url)
    if platform == "يوتيوب":
        return 400, {"error": "yt", "message": "للتحميل من YouTube استخدم هذا البوت @Gozilla_bot"}
    _LAST_DL[uid] = now
    sid = str(uuid.uuid4())[:8]
    _bump("downloads")
    _fire(_download_job(uid, user, url, kind, sid))
    return 200, {"ok": True, "platform": platform}


def api_session(uid, body):
    """ينشئ جلسة لرابط (مثل ما يسوي البوت عند استقبال رابط) لفتح محرّر التعديل عليها."""
    url = _clean_url(body.get("url"))
    if not url:
        return 400, {"error": "bad_url", "message": "الرابط غير صحيح، تأكد أنه يبدأ بـ http"}
    bad = _precheck(uid)
    if bad:
        return bad
    if "youtu" in url.lower():
        return 400, {"error": "yt", "message": "للتحميل من YouTube استخدم هذا البوت @Gozilla_bot"}
    sid = str(uuid.uuid4())[:8]

    async def _mk():
        B.URL_CACHE[sid] = url
        await B.url_put(sid, url)
    _run_async(_mk(), timeout=15)
    return 200, {"sid": sid}


# ---------------- محرّر التعديل ----------------
def _edit_limits():
    return {"trim_max": int(B.TRIM_MAX_SECONDS), "out_max": int(B.FILTER_MAX_SECONDS),
            "speed_min": float(B.SPEED_MIN), "speed_max": float(B.SPEED_MAX)}


def _session_url(sid):
    if not re.fullmatch(r"[A-Za-z0-9]{4,16}", str(sid or "")):
        return None
    return _run_async(B.get_session_url(sid), timeout=10)


def _state_json(st):
    c = st.get("c")
    return {"f": st.get("f"), "c": list(c) if c else None,
            "s": float(st["s"]) if st.get("s") else None,
            "p": bool(st.get("p", True)), "o": st.get("o")}


def api_edit_info(uid, body):
    sid = body.get("sid")
    if not _session_url(sid):
        return 404, {"error": "expired", "message": "انتهت صلاحية الجلسة، أعد إرسال الرابط في البوت."}
    st = B._edit_get(uid, sid)
    return 200, {
        "sid": sid, "state": _state_json(st), "duration": getattr(B, "DUR_CACHE", {}).get(sid),
        "is_pro": bool(B.is_premium(uid)), "trials": int(B.free_trials_left(uid)),
        "limits": _edit_limits(),
        "filters": [{"k": k, "name": v[0]} for k, v in B.FILTERS.items()],
    }


def api_edit_cover(uid, body):
    sid = body.get("sid")
    url = _session_url(sid)
    if not url:
        return 404, {"error": "expired", "message": "انتهت صلاحية الجلسة، أعد إرسال الرابط في البوت."}
    try:
        img = _run_async(B._get_thumb(sid, url), timeout=45)
    except Exception as e:
        logger.info(f"cover failed for {sid}: {e}")
        return 502, {"error": "cover", "message": "تعذر جلب صورة المقطع، تقدر تكمل التعديل بدونها."}
    small = None
    try:   # نصغّرها (480px) لتخفيف الحمل على الشبكة
        small = _run_async(B._filter_preview_image(img, "scale=480:-2", f"app_{uid}_{sid}"), timeout=20)
    except Exception:
        pass
    data = small or img
    return 200, {"img": "data:image/jpeg;base64," + base64.b64encode(data).decode(),
                 "duration": getattr(B, "DUR_CACHE", {}).get(sid)}


async def _edit_job(uid, user, sid):
    try:
        anchor = await BOT.send_message(chat_id=uid, parse_mode="HTML",
                                        text="📲 <b>تعديل من التطبيق</b>\nجاري التجهيز…")
        q = SimpleNamespace(data=f"ed_go_{sid}",
                            from_user=SimpleNamespace(id=uid, first_name=user.get("first_name", "")),
                            message=anchor, answer=_noop)
        await B.download_action_callback(SimpleNamespace(callback_query=q, effective_user=q.from_user), None)
    except Exception as e:
        logger.error(f"webapp edit failed for {uid}: {e}")
        try:
            await BOT.send_message(chat_id=uid, text="❌ تعذر تنفيذ التعديل من التطبيق، جرّبه من زر «تعديل المقطع» في البوت.")
        except Exception:
            pass


def api_edit_apply(uid, user, body):
    sid = body.get("sid")
    url = _session_url(sid)
    if not url:
        return 404, {"error": "expired", "message": "انتهت صلاحية الجلسة، أعد إرسال الرابط في البوت."}
    bad = _precheck(uid)
    if bad:
        return bad
    if not B.is_premium(uid) and B.free_trials_left(uid) <= 0:
        return 402, {"error": "pro", "message": "انتهت تجاربك المجانية. التعديل متاح لمشتركي Pro."}

    # --- تحقق صارم من القيم (لا نثق بالواجهة) ---
    f = body.get("f")
    f = f if f in B.FILTERS else None
    c = None
    raw_c = body.get("c")
    if isinstance(raw_c, (list, tuple)) and len(raw_c) == 2:
        try:
            a, b = int(float(raw_c[0])), int(float(raw_c[1]))
            if a >= 0 and b > a:
                b = min(b, a + int(B.TRIM_MAX_SECONDS))
                c = (a, b)
        except Exception:
            c = None
    s = None
    try:
        v = round(float(body.get("s") or 1), 2)
        if v < B.SPEED_MIN or v > B.SPEED_MAX:
            return 400, {"error": "bad_speed", "message": f"السرعة بين {B.SPEED_MIN:g} و{B.SPEED_MAX:g}"}
        s = None if abs(v - 1) < 0.01 else f"{v:g}"
    except Exception:
        s = None
    o = body.get("o") if body.get("o") in B.ORIENT else None

    st = B._edit_get(uid, sid)
    st["f"], st["c"], st["s"], st["o"] = f, c, s, o
    st["p"] = bool(body.get("p", True))
    if not B._has_edit(st):
        return 400, {"error": "empty", "message": "اختر فلتراً أو قصاً أو سرعة أو اتجاهاً أولاً."}

    now = time.time()
    if len(_LAST_EDIT) > 5000:
        _LAST_EDIT.clear()
    if now - _LAST_EDIT.get(uid, 0) < 4:
        return 429, {"error": "slow", "message": "انتظر ثواني قبل الطلب التالي."}
    _LAST_EDIT[uid] = now
    B.track_user_activity(uid)
    _bump("edits")
    _fire(_edit_job(uid, user, sid))
    return 200, {"ok": True}


# ---------------- الدفع بـ TON (يدوي بمراجعة الأدمن) ----------------
def _ton_links(nano, code):
    q = f"amount={nano}&text={code}"
    return (f"ton://transfer/{TON_ADDRESS}?{q}",
            f"https://app.tonkeeper.com/transfer/{TON_ADDRESS}?{q}")


def api_ton_order(uid, user, body):
    if not TON_ENABLED:
        return 403, {"error": "off", "message": "هذه الطريقة غير متاحة حالياً."}
    plan = body.get("plan")
    if plan not in B.PLANS or plan not in TON_PRICES:
        return 400, {"error": "bad_plan"}
    orders = B.stats.setdefault("ton_orders", {})
    mine = [o for o in orders.values() if o.get("uid") == uid and o.get("st") == "new"]
    if len(mine) >= 6:   # حد أقصى للطلبات المفتوحة لكل مستخدم
        for k in [k for k, o in orders.items() if o.get("uid") == uid and o.get("st") == "new"][:3]:
            orders.pop(k, None)
    oid = uuid.uuid4().hex[:6].upper()
    code = f"ZD{oid}"
    price = TON_PRICES[plan]
    nano = int(round(price * 1e9))
    orders[oid] = {"uid": uid, "plan": plan, "ton": price, "code": code, "t": datetime.now().isoformat(), "st": "new"}
    while len(orders) > 300:
        orders.pop(next(iter(orders)))
    _bump("ton_orders")
    deep, web = _ton_links(nano, code)
    return 200, {"oid": oid, "address": TON_ADDRESS, "amount": price, "comment": code,
                 "link": deep, "web": web, "label": B.PLANS[plan]["label"]}


async def _notify_admin_ton(uid, user, o, oid):
    from html import escape
    plan = B.PLANS.get(o["plan"], {})
    name = escape(str(user.get("first_name", "")))
    uname = f"@{escape(user['username'])}" if user.get("username") else "—"
    text = (
        "💎 <b>طلب دفع بـ TON</b>\n━━━━━━━\n"
        f"👤 <a href=\"tg://user?id={uid}\">{name}</a> ({uname})\n"
        f"🆔 <code>{uid}</code>\n"
        f"📦 الباقة: <b>{escape(str(plan.get('label', o['plan'])))}</b>\n"
        f"💰 المبلغ المطلوب: <b>{o['ton']:g} TON</b>\n"
        f"🏷 التعليق المتوقع: <code>{o['code']}</code>\n\n"
        "قال المستخدم إنه حوّل. تحقق من وصول المبلغ <b>مع التعليق نفسه</b> في المحفظة أو "
        f"<a href=\"https://tonviewer.com/{TON_ADDRESS}\">Tonviewer</a>، ثم فعّل أو ارفض 👇"
    )
    kb = B.InlineKeyboardMarkup([[
        B.InlineKeyboardButton("✅ تفعيل الباقة", callback_data=f"tonok_{oid}"),
        B.InlineKeyboardButton("❌ رفض", callback_data=f"tonno_{oid}"),
    ]])
    await BOT.send_message(chat_id=ADMIN_ID, text=text, parse_mode="HTML", reply_markup=kb,
                           disable_web_page_preview=True)


def api_ton_paid(uid, user, body):
    if not TON_ENABLED:
        return 403, {"error": "off"}
    oid = str(body.get("oid", ""))[:12]
    o = B.stats.get("ton_orders", {}).get(oid)
    if not o or o.get("uid") != uid:
        return 404, {"error": "no_order", "message": "الطلب غير موجود، ابدأ من جديد."}
    if o.get("st") in ("claimed", "done"):
        return 200, {"ok": True, "already": True}
    o["st"] = "claimed"
    _bump("ton_claimed")
    _run_async(_notify_admin_ton(uid, user, o, oid), timeout=15)
    return 200, {"ok": True}


# ---------------- لوحة الأدمن ----------------
def api_admin(uid):
    if uid != ADMIN_ID:
        return 403, {"error": "forbidden"}
    S = B.stats
    now = datetime.now()
    a_now = a_day = a_7 = a_30 = 0
    for last in S.get("users", {}).values():
        try:
            d = now - datetime.fromisoformat(last)
        except Exception:
            continue
        if d <= timedelta(minutes=5): a_now += 1
        if d <= timedelta(days=1): a_day += 1
        if d <= timedelta(days=7): a_7 += 1
        if d <= timedelta(days=30): a_30 += 1
    ok, bad = S.get("successful_downloads", 0), S.get("failed_downloads", 0)
    pro_active = 0
    for iso in S.get("premium", {}).values():
        try:
            if datetime.fromisoformat(iso) > now:
                pro_active += 1
        except Exception:
            pass
    plats = []
    for name, d in S.get("platform_stats", {}).items():
        if d.get("total", 0):
            plats.append({"name": name, "total": d.get("total", 0), "ok": d.get("success", 0), "bad": d.get("failed", 0)})
    plats.sort(key=lambda x: -x["total"])
    try:
        ed_u, ed_n = B.feat_counts("edit_done")
    except Exception:
        ed_u = ed_n = 0
    up = now - B.BOT_START_TIME
    return 200, {
        "users": len(S.get("users", {})), "now": a_now, "day": a_day, "d7": a_7, "d30": a_30,
        "requests": S.get("total_requests", 0), "ok": ok, "bad": bad,
        "rate": round(ok / (ok + bad) * 100, 1) if (ok + bad) else 0.0,
        "videos": S.get("sent_videos", 0),
        "pro_active": pro_active, "pro_sold": len(S.get("pro_info", {})),
        "edits_users": ed_u, "edits": ed_n,
        "platforms": plats[:8],
        "uptime": f"{up.days}ي {up.seconds // 3600}س",
        "app": app_stats_summary(),
    }


# ------------------------------------------------------------------ خادم HTTP
def _load_html():
    try:
        mt = os.path.getmtime(HTML_PATH)
        if mt != _HTML_CACHE["mtime"]:
            raw = open(HTML_PATH, "rb").read()
            _HTML_CACHE.update(mtime=mt, raw=raw, gz=gzip.compress(raw, 6))
        return _HTML_CACHE
    except Exception as e:
        logger.error(f"webapp.html not readable: {e}")
        return None


class AppHandler(BaseHTTPRequestHandler):
    timeout = 60                   # الطلبات الطويلة (جلب صورة المقطع) تأخذ وقتها، والاتصالات الميتة تُقطع
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        return

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/app", "/app/"):
            c = _load_html()
            if not c:
                return self._send(503, "app not available", "text/plain; charset=utf-8")
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                return self._send(200, c["gz"], "text/html; charset=utf-8", {"Content-Encoding": "gzip"})
            return self._send(200, c["raw"], "text/html; charset=utf-8")
        self._send(200, b"ZenDown_Bot is Running!", "text/plain; charset=utf-8")

    def do_HEAD(self):
        self._send(200, b"", "text/plain; charset=utf-8")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/"):
            return self._send(404, {"error": "not_found"})
        if B is None or LOOP is None or BOT is None:
            return self._send(503, {"error": "starting", "message": "البوت يستيقظ… جرّب بعد لحظات"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 8192:
                return self._send(413, {"error": "too_big"})
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if not isinstance(body, dict):
                body = {}
        except Exception:
            return self._send(400, {"error": "bad_json"})

        user = verify_init_data(self.headers.get("X-Init-Data", ""), TOKEN)
        if not user:
            return self._send(401, {"error": "auth", "message": "افتح التطبيق من داخل تيليجرام."})
        uid = user["id"]
        if not _rate_ok(uid):
            return self._send(429, {"error": "rate", "message": "طلبات كثيرة، انتظر قليلاً."})

        try:
            if path == "/api/me":
                return self._send(200, api_me(uid, user, bool(body.get("open"))))
            _touch(uid)
            routes = {
                "/api/invoices": lambda: api_invoices(uid),
                "/api/download": lambda: api_download(uid, user, body),
                "/api/session": lambda: api_session(uid, body),
                "/api/edit/info": lambda: api_edit_info(uid, body),
                "/api/edit/cover": lambda: api_edit_cover(uid, body),
                "/api/edit/apply": lambda: api_edit_apply(uid, user, body),
                "/api/ton/order": lambda: api_ton_order(uid, user, body),
                "/api/ton/paid": lambda: api_ton_paid(uid, user, body),
                "/api/admin": lambda: api_admin(uid),
            }
            fn = routes.get(path)
            if not fn:
                return self._send(404, {"error": "not_found"})
            code, data = fn()
            return self._send(code, data)
        except Exception as e:
            logger.error(f"webapp api {path} failed: {e}")
            return self._send(500, {"error": "server", "message": "حدث خطأ مؤقت، حاول مرة ثانية."})


def start_server():
    port = int(os.environ.get("PORT", 8080))
    srv = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def app_url(sid=None):
    """رابط التطبيق (WEBAPP_URL أو رابط Render). مع sid يفتح المحرّر مباشرة على هذا المقطع."""
    u = (os.environ.get("WEBAPP_URL") or "").strip()
    if not u:
        r = (os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
        u = f"{r}/app" if r else ""
    if u and sid:
        u += ("&" if "?" in u else "?") + f"e={sid}"
    return u
