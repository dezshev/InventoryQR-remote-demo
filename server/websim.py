#!/usr/bin/env python3
"""Веб-доступ к iOS-симулятору: экран через simctl, касания и ввод через cliclick по окну Simulator.

Запуск: websim.py <UDID> <порт> <пароль>
"""
import base64
import http.server
import io
import json
import subprocess
import sys
import threading
import time

from PIL import Image

UDID, PORT, PASSWORD = sys.argv[1], int(sys.argv[2]), sys.argv[3]
BUNDLE = "by.gstu.itp.InventoryQR"
MAX_HEIGHT = 1100

state = {"jpeg": b"", "px": (1, 1), "stamp": 0.0}
lock = threading.Lock()


DEBUG = []


def run(*args, timeout=15):
    r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if args[0] in ("cliclick", "osascript"):
        DEBUG.append({"cmd": list(args)[:6], "rc": r.returncode, "out": r.stdout[-300:], "err": r.stderr[-300:]})
        del DEBUG[:-30]
    return r


def window_rect():
    """Положение и размер окна Simulator на экране Mac (в точках)."""
    script = 'tell application "System Events" to tell process "Simulator" to get {position, size} of front window'
    out = run("osascript", "-e", script).stdout.strip()
    x, y, w, h = [float(v) for v in out.replace(" ", "").split(",")]
    return x, y, w, h


def to_mac(nx, ny):
    """Нормированные координаты экрана устройства -> координаты на экране Mac."""
    x, y, w, h = window_rect()
    with lock:
        pw, ph = state["px"]
    content_h = w * ph / pw
    top = y + (h - content_h)          # над изображением устройства — заголовок окна
    return round(x + nx * w), round(top + ny * content_h)


def activate():
    run("osascript", "-e", 'tell application "Simulator" to activate')


SETUP_SCRIPT = """
tell application "Simulator" to activate
delay 1
tell application "System Events" to tell process "Simulator"
    try
        set mi to menu item "Show Device Bezels" of menu "Window" of menu bar 1
        if (value of attribute "AXMenuItemMarkChar" of mi) is not missing value then click mi
    end try
    delay 1
    set position of front window to {10, 40}
end tell
"""

DISMISS_SCRIPT = """
tell application "System Events"
    repeat with procName in {"UserNotificationCenter"}
        if exists process procName then
            tell process procName
                repeat with w in windows
                    repeat with b in {"Allow", "OK", "Разрешить"}
                        if exists button b of w then click button b of w
                    end repeat
                end repeat
            end tell
        end if
    end repeat
end tell
"""


def setup_window():
    run("osascript", "-e", SETUP_SCRIPT, timeout=30)


def dismiss_loop():
    while True:
        try:
            run("osascript", "-e", DISMISS_SCRIPT, timeout=20)
        except Exception as exc:  # noqa: BLE001
            print("dismiss error:", exc, flush=True)
        time.sleep(15)


POINTS = (None, None)


def capture_loop():
    path = "/tmp/websim_frame.png"
    while True:
        try:
            r = run("xcrun", "simctl", "io", UDID, "screenshot", "--type=png", path, timeout=10)
            if r.returncode == 0:
                im = Image.open(path).convert("RGB")
                px = im.size
                k = MAX_HEIGHT / im.height
                if k < 1:
                    im = im.resize((int(im.width * k), MAX_HEIGHT), Image.BILINEAR)
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=72)
                with lock:
                    state.update(jpeg=buf.getvalue(), px=px, stamp=time.time())
        except Exception as exc:  # noqa: BLE001
            print("capture error:", exc, flush=True)
        time.sleep(0.25)


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Симулятор iOS — Инвентарь</title>
<style>
body{margin:0;background:#1e1e1e;color:#eee;font:15px system-ui,sans-serif;display:flex;flex-direction:column;align-items:center}
header{padding:10px 16px;text-align:center}
#wrap{position:relative;touch-action:none;user-select:none}
#screen{height:calc(100vh - 150px);max-width:96vw;border-radius:28px;border:6px solid #333;cursor:pointer;display:block}
.bar{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;padding:10px}
button,input{font:inherit;padding:8px 12px;border-radius:8px;border:1px solid #555;background:#2d2d2d;color:#eee}
button:hover{background:#3a3a3a}
#status{font-size:13px;color:#aaa}
</style></head><body>
<header>Приложение «Инвентарь» в симуляторе iOS. Щелчок — касание, перетаскивание — свайп.
<div id="status">подключение…</div></header>
<div id="wrap"><img id="screen" alt="экран симулятора" draggable="false"></div>
<div class="bar">
<input id="text" placeholder="Текст для ввода в поле" size="24">
<button onclick="send('text',{text:document.getElementById('text').value});document.getElementById('text').value=''">Ввести</button>
<button onclick="send('key',{key:'backspace'})">⌫</button>
<button onclick="send('key',{key:'enter'})">Enter</button>
<button onclick="send('home',{})">Домой</button>
<button onclick="send('relaunch',{})">Перезапустить приложение</button>
</div>
<script>
const img=document.getElementById('screen'),st=document.getElementById('status');
let busy=false;
async function refresh(){
  if(busy) return; busy=true;
  try{const r=await fetch('frame.jpg?'+Date.now(),{cache:'no-store'});
      if(r.ok){const b=await r.blob();const u=URL.createObjectURL(b);const old=img.src;img.src=u;if(old.startsWith('blob:'))URL.revokeObjectURL(old);st.textContent='подключено';}
      else st.textContent='ошибка '+r.status;}
  catch(e){st.textContent='нет связи';}
  busy=false;
}
setInterval(refresh,350); refresh();
function rel(e){const r=img.getBoundingClientRect();return {x:(e.clientX-r.left)/r.width,y:(e.clientY-r.top)/r.height};}
let down=null;
img.addEventListener('pointerdown',e=>{down={p:rel(e),t:Date.now()};img.setPointerCapture(e.pointerId);});
img.addEventListener('pointerup',e=>{if(!down)return;const p=rel(e);const d=Math.hypot(p.x-down.p.x,p.y-down.p.y);
  if(d<0.02) send('tap',{x:p.x,y:p.y}); else send('swipe',{x1:down.p.x,y1:down.p.y,x2:p.x,y2:p.y,ms:Date.now()-down.t});
  down=null;});
async function send(action,body){body.action=action;
  await fetch('input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  setTimeout(refresh,150);}
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def authorized(self):
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                if pw == PASSWORD:
                    return True
            except Exception:  # noqa: BLE001
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="simulator", charset="UTF-8"')
        self.end_headers()
        return False

    def do_GET(self):
        if not self.authorized():
            return
        if self.path.startswith("/debug"):
            info = {"log": DEBUG}
            try:
                info["window"] = window_rect()
            except Exception as exc:  # noqa: BLE001
                info["window_error"] = str(exc)
            body = json.dumps(info, ensure_ascii=False, indent=1).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/desktop.jpg"):
            subprocess.run(["screencapture", "-x", "-t", "jpg", "/tmp/websim_desktop.jpg"], timeout=10)
            data = open("/tmp/websim_desktop.jpg", "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path.startswith("/frame.jpg"):
            with lock:
                data = state["jpeg"]
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if not self.authorized():
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send_response(400)
            self.end_headers()
            return
        act = req.get("action")
        try:
            activate()
            if act == "tap":
                X, Y = to_mac(req["x"], req["y"])
                run("cliclick", "c:%d,%d" % (X, Y))
            elif act == "swipe":
                X1, Y1 = to_mac(req["x1"], req["y1"])
                X2, Y2 = to_mac(req["x2"], req["y2"])
                steps = ["dd:%d,%d" % (X1, Y1)]
                for i in range(1, 9):
                    steps += ["w:15", "dm:%d,%d" % (X1 + (X2 - X1) * i / 8, Y1 + (Y2 - Y1) * i / 8)]
                steps += ["du:%d,%d" % (X2, Y2)]
                run("cliclick", *steps)
            elif act == "text" and req.get("text"):
                # текст (в том числе кириллица) передаётся через буфер обмена симулятора и Cmd+V
                subprocess.run(["xcrun", "simctl", "pbcopy", UDID], input=req["text"].encode("utf-8"), timeout=10)
                time.sleep(0.3)
                run("cliclick", "kd:cmd", "t:v", "ku:cmd")
            elif act == "key":
                run("cliclick", "kp:" + {"backspace": "delete", "enter": "return"}[req["key"]])
            elif act == "home":
                run("cliclick", "kd:cmd,shift", "t:h", "ku:cmd,shift")
            elif act == "relaunch":
                run("xcrun", "simctl", "terminate", UDID, BUNDLE)
                run("xcrun", "simctl", "launch", UDID, BUNDLE)
        except Exception as exc:  # noqa: BLE001
            print("input error:", exc, flush=True)
        self.send_response(204)
        self.end_headers()


if __name__ == "__main__":
    setup_window()
    threading.Thread(target=dismiss_loop, daemon=True).start()
    threading.Thread(target=capture_loop, daemon=True).start()
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
