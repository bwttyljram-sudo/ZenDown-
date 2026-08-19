"""
سيرفر وهمي (Dummy HTTP Health Server) لإرضاء منصة الاستضافة (Render/UptimeRobot).
مفصول عن bot.py الأساسي لتنظيم الكود فقط — نفس الوظيفة والسلوك بدون أي تغيير.
"""
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


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


def run_health_server_in_background():
    """يشغّل السيرفر الوهمي في Thread منفصل (daemon) بدون حجب التشغيل الرئيسي."""
    threading.Thread(target=start_dummy_server, daemon=True).start()

