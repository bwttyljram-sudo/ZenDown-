"""
ZenDown Mini App — الخلفية (Backend)
====================================
ملف منفصل عن bot.py: يقدّم صفحة التطبيق (webapp.html) + مسارات API صغيرة، على نفس المنفذ
الذي كان يستخدمه خادم الصحة (Render/UptimeRobot) — فلا حاجة لمكتبات جديدة ولا لخدمة ثانية.

الأمان: كل طلب API يجب أن يحمل بيانات تيليجرام الموقّعة (initData) ونتحقق من توقيعها بالتوكن،
فلا يقدر أحد ينتحل حساب غيره أو يدخل لوحة الأدمن.
لا يوجد هنا منطق تحميل/اشتراك خاص: نستدعي نفس دوال bot.py الموجودة.
"""
import os
import re
import json
import time
import gzip
import hmac
import uuid
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

# يُملأ من bot.py عند الإقلاع (configure / set_runtime)
B = None                # وحدة bot.py نفسها (للوصول لدواله وإحصائياته)
TOKEN = None
ADMIN_ID = None
LOOP = None             # حلقة asyncio الخاصة بالبوت
BOT = None              # كائن bot الخاص بمكتبة تيليجرام

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_RATE = {}              # uid -> [timestamps] للحد من الطلبات
_LAST_DL = {}           # uid -> وقت آخر طلب تحميل
_HTML_CACHE = {"mtime": 0, "raw": b"", "gz": b""}


def configure(bot_module, token, admin_id):
    global B, TOKEN, ADMIN_ID
    B, TOKEN, ADMIN_ID = bot_module, token, int(admin_id)


def set_runtime(loop, bot):
    global LOOP, BOT
    LOOP, BOT = loop, bot


# ------------------------------------------------------------------ التحقق من هوية المستخدم
def verify_init_data(init_data, token, max_age=86400):
    """يتحقق من توقيع initData حسب توثيق تيليجرام. يرجع dict المستخدم أو None."""
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


def _rate_ok(uid, limit=40, per=60):
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


# ------------------------------------------------------------------ تنفيذ كوروتين على حلقة البوت
def _run_async(coro, timeout=25):
    if LOOP is None:
        coro.close()
        raise RuntimeError("loop not ready")
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout=timeout)


def _fire(coro):
    """يشغّل مهمة طويلة (تحميل) في الخلفية بدون انتظارها."""
    if LOOP is None:
        coro.close()
        raise RuntimeError("loop not ready")
    asyncio.run_coroutine_threadsafe(coro, LOOP)


# ------------------------------------------------------------------ المسارات
def api_me(uid, user):
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
        "plans": [
            {"key": k, "label": v["label"], "stars": v["stars"], "days": v["days"]}
            for k, v in B.PLANS.items()
        ],
        "channel": getattr(B, "CHANNEL", ""),
    }


async def _download_job(uid, user, url, kind, sid):
    """يحاكي ضغطة الزر في البوت: نفس دالة التحميل الأصلية بالضبط، بدون أي نسخة مكررة من المنطق."""
    try:
        B.URL_CACHE[sid] = url
        B._bg(B.url_put(sid, url))
        anchor = await BOT.send_message(
            chat_id=uid, parse_mode="HTML",
            text="📲 <b>طلب من التطبيق</b>\nجاري التجهيز…")
        q = SimpleNamespace(
            data=f"down_{kind}_{sid}",
            from_user=SimpleNamespace(id=uid, first_name=user.get("first_name", "")),
            message=anchor,
            answer=_noop,
        )
        upd = SimpleNamespace(callback_query=q, effective_user=q.from_user)
        await B.download_action_callback(upd, None)
    except Exception as e:
        logger.error(f"webapp download failed for {uid}: {e}")
        try:
            await BOT.send_message(chat_id=uid, text="❌ تعذر تنفيذ الطلب من التطبيق، أرسل الرابط هنا مباشرة وسأحمّله لك.")
        except Exception:
            pass


async def _noop(*a, **k):
    return None


def api_download(uid, user, body):
    raw = str(body.get("url", "")).strip()[:2000]
    m = URL_RE.search(raw)
    if not m:
        return 400, {"error": "bad_url", "message": "الرابط غير صحيح، تأكد أنه يبدأ بـ http"}
    url = m.group(0).rstrip(").,،")
    kind = body.get("kind", "vid")
    if kind not in ("vid", "aud", "img"):
        kind = "vid"

    if B.get_setting("maint") and uid != ADMIN_ID:
        return 503, {"error": "maint", "message": "البوت تحت الصيانة حالياً، نعود قريباً."}

    if not _run_async(B.check_user_subscription(BOT, uid), timeout=15):
        return 403, {"error": "sub", "message": f"اشترك أولاً في قناة التحديثات {getattr(B, 'CHANNEL', '')} ثم عد للتطبيق."}

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
    _fire(_download_job(uid, user, url, kind, sid))
    return 200, {"ok": True, "platform": platform}


def api_invoice(uid, body):
    key = body.get("plan")
    plan = B.PLANS.get(key)
    if not plan:
        return 400, {"error": "bad_plan"}

    async def _mk():
        return await BOT.create_invoice_link(
            title=f"ZenDown Pro — {plan['label']}",
            description=f"اشتراك Pro لمدة {plan['days']} يوم: تخطي الطابور + تعديل المقطع (فلاتر، قص، سرعة، اتجاه).",
            payload=f"plan_{key}",
            currency="XTR",
            prices=[B.LabeledPrice(f"Pro {plan['label']}", int(plan["stars"]))],
        )
    link = _run_async(_mk())
    return 200, {"link": link}


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
    timeout = 20                  # لا نترك خيوطاً معلقة مع اتصالات بطيئة
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        return

    # ---- أدوات
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

    # ---- GET: الصحة + صفحة التطبيق
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/app", "/app/"):
            c = _load_html()
            if not c:
                return self._send(503, "app not available", "text/plain; charset=utf-8")
            if "gzip" in (self.headers.get("Accept-Encoding") or ""):
                return self._send(200, c["gz"], "text/html; charset=utf-8", {"Content-Encoding": "gzip"})
            return self._send(200, c["raw"], "text/html; charset=utf-8")
        # أي مسار آخر = فحص الصحة كما كان (Render / UptimeRobot)
        self._send(200, b"ZenDown_Bot is Running!", "text/plain; charset=utf-8")

    def do_HEAD(self):
        self._send(200, b"", "text/plain; charset=utf-8")

    # ---- POST: API
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
                B.track_user_activity(uid)
                return self._send(200, api_me(uid, user))
            if path == "/api/download":
                code, data = api_download(uid, user, body)
                return self._send(code, data)
            if path == "/api/invoice":
                code, data = api_invoice(uid, body)
                return self._send(code, data)
            if path == "/api/admin":
                code, data = api_admin(uid)
                return self._send(code, data)
            return self._send(404, {"error": "not_found"})
        except Exception as e:
            logger.error(f"webapp api {path} failed: {e}")
            return self._send(500, {"error": "server", "message": "حدث خطأ مؤقت، حاول مرة ثانية."})


def start_server():
    """يشغّل الخادم في خيط خلفي. يحل محل خادم الصحة القديم على نفس المنفذ."""
    port = int(os.environ.get("PORT", 8080))
    srv = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def app_url():
    """رابط التطبيق: متغير WEBAPP_URL إن وُجد، وإلا رابط Render التلقائي. فارغ = بدون أزرار تطبيق."""
    u = (os.environ.get("WEBAPP_URL") or "").strip()
    if u:
        return u
    r = (os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    return f"{r}/app" if r else ""
