#!/usr/bin/env python3
"""n10gui5.py - N10墨水屏GUI v4.1 (低延迟版)
- 事件驱动: pty回显立即触发重绘(不再轮询)
- 行级增量: 只重画变化的终端行/键盘区, 局部写fb(免整帧旋转)
- 全量帧仅在浮层开/关时(带GC16全刷)
"""
import os, sys, struct, fcntl, mmap, time, pty, termios, threading, subprocess, queue, socket, glob
import pyte
from PIL import Image, ImageDraw, ImageFont

W, H = 1404, 1872
MONO = "/usr/local/share/fonts/MapleMono-NFCN.ttf"
F_MONO = ImageFont.truetype(MONO, 50)   # Maple NF CN: 拉丁30px/汉字60px/Nerd图标全有
F_TITLE, F_ITEM, F_KEY, F_SMALL = (ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", s)
                                   for s in (48, 40, 52, 32))
IOCTL_REFRESH = 0xC0016440
EVENT = struct.Struct("<qqHHi")

PAD = 8
CELL_W = 30
CELL_H = 66
TOPBAR = 76
KB_H = 450
W_FB, H_FB = 1872, 1404

def fb2vis(fx, fy):
    return fy, W_FB - 1 - fx

def inside(pos, r):
    x, y = pos
    rx, ry, rw, rh = r
    return rx <= x <= rx+rw and ry <= y <= ry+rh

class Display:
    def __init__(self):
        self.fd = os.open("/dev/fb0", os.O_RDWR)
        self.mm = mmap.mmap(self.fd, W_FB * H_FB * 4, mmap.MAP_SHARED, mmap.PROT_WRITE)
    def show(self, img):
        fb = img.rotate(-90, expand=True)
        self.mm.seek(0)
        self.mm.write(fb.convert("RGBX").tobytes())
        self.mm.flush()
    def write_region(self, canvas, x, y, w, h):
        """局部更新: 只旋转该区域, 按映射写fb(免整帧旋转)"""
        y2 = min(y + h, H); x2 = min(x + w, W)
        if y2 <= y or x2 <= x:
            return
        crop = canvas.crop((x, y, x2, y2))       # w x h
        rot = crop.rotate(-90, expand=True)      # h x w
        data = rot.tobytes()
        seg_w = y2 - y
        img_x1 = W_FB - y2
        def expand(seg):
            out = bytearray(len(seg) * 4)
            out[0::4] = seg; out[1::4] = seg; out[2::4] = seg
            return bytes(out)
        for iy in range(x, x2):
            seg = data[(iy - x)*seg_w : (iy - x + 1)*seg_w]
            self.mm.seek((iy * W_FB + img_x1) * 4)
            self.mm.write(expand(seg))
        self.mm.flush()
    def full_refresh(self):
        try:
            fd = os.open("/dev/dri/card0", os.O_RDWR)
            fcntl.ioctl(fd, IOCTL_REFRESH, b"\x01")
            os.close(fd)
        except OSError:
            pass

def wired_connected():
    """有线网状态: 插线(carrier)且拿到IPv4才算连接成功"""
    for p in glob.glob("/sys/class/net/*"):
        name = os.path.basename(p)
        if name in ("lo", "wlan0"):
            continue
        try:
            if open(p + "/carrier").read().strip() != "1":
                continue
        except OSError:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", name.encode()[:15]))   # SIOCGIFADDR
            return True
        except OSError:
            continue
        finally:
            s.close()
    return False

def read_battery():
    try:
        cap = open("/sys/class/power_supply/rk817-battery/capacity").read().strip()
        st = open("/sys/class/power_supply/rk817-battery/status").read().strip()
        return cap, st
    except OSError:
        return None, None

def feed_temp_once():
    """fp9931实测温度 -> ebc驱动temp_override(波形LUT按温度生成, 不喂就死在25°C)"""
    try:
        for i in range(8):
            p = "/sys/class/hwmon/hwmon%d" % i
            if os.path.exists(p + "/name") and open(p + "/name").read().strip() == "fp9931":
                t = int(open(p + "/temp1_input").read()) // 1000
                if t > 0:
                    open("/sys/module/rockchip_ebc/parameters/temp_override", "w").write(str(t))
                    print("temp fed:", t, flush=True)
                return
    except OSError as e:
        print("temp feed fail:", e, flush=True)

def feed_temp_loop():
    while True:
        feed_temp_once()
        time.sleep(60)

def unbind_fbcon():
    try:
        for c in ("vtcon1", "vtcon0", "vtcon2"):
            p = "/sys/class/vtconsole/%s/name" % c
            if os.path.exists(p) and "frame buffer" in open(p).read():
                open("/sys/class/vtconsole/%s/bind" % c, "w").write("0")
                print("fbcon unbound:", c, flush=True)
    except OSError as e:
        print("unbind failed:", e, flush=True)

class Term:
    def __init__(self, cols, rows, on_data=None):
        self.cols, self.rows = cols, rows
        self.screen = pyte.HistoryScreen(cols, rows)   # 带滚动历史(翻页用)
        self.stream = pyte.ByteStream(self.screen)
        self.dirty = True
        self.lock = threading.Lock()
        self.on_data = on_data or (lambda: None)
        self.pid, self.mfd = pty.fork()
        if self.pid == 0:
            os.environ["TERM"] = "xterm"
            os.execv("/bin/bash", ["-bash"])
        threading.Thread(target=self._reader, daemon=True).start()
    def _reader(self):
        while True:
            try:
                data = os.read(self.mfd, 4096)
            except OSError:
                break
            if not data:
                break
            with self.lock:
                self.stream.feed(data)
            self.dirty = True
            self.on_data()
    def resize(self, cols, rows):
        if (cols, rows) == (self.cols, self.rows):
            return
        self.cols, self.rows = cols, rows
        with self.lock:
            self.screen.resize(rows, cols)
        fcntl.ioctl(self.mfd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.dirty = True
    def write(self, data):
        try:
            os.write(self.mfd, data)
        except OSError:
            pass

class Pen(threading.Thread):
    EVIOCGNAME = 0x81004506
    def __init__(self, on_click=None):
        super().__init__(daemon=True)
        self.fbpos = [W_FB//2, H_FB//2]
        self.clicks = queue.Queue()
        self._down = False
        self.on_click = on_click or (lambda: None)
    def _find(self):
        for i in range(8):
            try:
                fd = os.open("/dev/input/event%d" % i, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            buf = bytearray(256)
            try:
                fcntl.ioctl(fd, self.EVIOCGNAME, buf)
            except OSError:
                os.close(fd); continue
            if bytes(buf).split(b"\x00")[0] == b"hanvon_pen":
                return fd
            os.close(fd)
        return None
    def run(self):
        fd = None
        while True:
            if fd is None:
                fd = self._find()
                if fd is None:
                    time.sleep(1); continue
            try:
                data = os.read(fd, 24)
            except BlockingIOError:
                time.sleep(0.01); continue
            except OSError:
                os.close(fd); fd = None; continue
            if len(data) != 24:
                continue
            _, _, t, c, v = EVENT.unpack(data)
            if t == 3 and c == 0:
                self.fbpos[0] = v
            elif t == 3 and c == 1:
                self.fbpos[1] = v
            elif t == 3 and c == 0x18:
                if v > 60 and not self._down:
                    self._down = True
                    self.clicks.put(fb2vis(*self.fbpos))
                    self.on_click()
                elif v < 30 and self._down:
                    self._down = False

class Buttons(threading.Thread):
    """9个实体按键(gpio-keys/event1)
    1=594上翻页 2=595下翻页 3=596音量+ 4=597音量- 5(HOME)=158刷新 6-9=598-601未用"""
    EVIOCGNAME = 0x81004506
    def __init__(self, on_key=None):
        super().__init__(daemon=True)
        self.keys = queue.Queue()
        self.on_key = on_key or (lambda: None)
    def _find(self):
        for i in range(8):
            try:
                fd = os.open("/dev/input/event%d" % i, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            buf = bytearray(256)
            try:
                fcntl.ioctl(fd, self.EVIOCGNAME, buf)
            except OSError:
                os.close(fd); continue
            if bytes(buf).split(b"\x00")[0] == b"gpio-keys":
                return fd
            os.close(fd)
        return None
    def run(self):
        fd = None
        while True:
            if fd is None:
                fd = self._find()
                if fd is None:
                    time.sleep(1); continue
            try:
                data = os.read(fd, 24)
            except BlockingIOError:
                time.sleep(0.01); continue
            except OSError:
                os.close(fd); fd = None; continue
            if len(data) != 24:
                continue
            _, _, t, c, v = EVENT.unpack(data)
            if t == 1 and v == 1:
                self.keys.put(c)
                self.on_key()

class Wifi:
    @staticmethod
    def scan():
        try:
            subprocess.run(["wpa_cli", "-i", "wlan0", "scan"], capture_output=True, timeout=10)
            time.sleep(3)
            out = subprocess.run(["wpa_cli", "-i", "wlan0", "scan_results"],
                                 capture_output=True, text=True, timeout=10).stdout
        except Exception:
            return []
        nets = []
        for line in out.splitlines()[1:]:
            p = line.split("\t")
            if len(p) >= 5 and p[4]:
                nets.append({"signal": int(p[2]), "flags": p[3], "ssid": p[4]})
        nets.sort(key=lambda n: -n["signal"])
        return nets
    @staticmethod
    def connect(ssid, psk):
        conf = ('ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n'
                'update_config=1\n\n'
                'network={\n    ssid="%s"\n    psk="%s"\n    key_mgmt=WPA-PSK\n}\n' % (ssid, psk))
        open("/etc/wpa_supplicant/wpa_supplicant.conf", "w").write(conf)
        subprocess.run(["systemctl", "restart", "wpa_supplicant@wlan0"], capture_output=True)

REV_SHIFT = {"1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^", "7": "&",
             "8": "*", "9": "(", "0": ")", "-": "_", "=": "+", "[": "{", "]": "}",
             "\\": "|", ";": ":", "'": '"', "`": "~", ",": "<", ".": ">", "/": "?"}

# USB实体键盘: Linux键码 -> 基础字符
_KEY_BASE = {}
_A = {"a":30,"b":48,"c":46,"d":32,"e":18,"f":33,"g":34,"h":35,"i":23,"j":36,
      "k":37,"l":38,"m":50,"n":49,"o":24,"p":25,"q":16,"r":19,"s":31,"t":20,
      "u":22,"v":47,"w":17,"x":45,"y":21,"z":44}
for _ch, _code in _A.items():
    _KEY_BASE[_code] = _ch
for _i, _ch in enumerate("1234567890"):
    _KEY_BASE[2 + _i] = _ch
_KEY_BASE.update({41: "`", 12: "-", 13: "=", 26: "[", 27: "]", 43: "\\",
                  39: ";", 40: "'", 51: ",", 52: ".", 53: "/", 57: " "})
_KB_SPECIAL = {1: b"\x1b", 14: b"\x7f", 28: b"\r", 15: b"\t",
               103: b"\x1b[A", 108: b"\x1b[B", 105: b"\x1b[D", 106: b"\x1b[C",
               102: b"\x1b[H", 107: b"\x1b[F", 104: b"\x1b[5~", 109: b"\x1b[6~",
               111: b"\x1b[3~"}
# 未映射的常用F键等忽略; 返回None不发送

def kb_translate(code, shift, ctrl, alt, caps):
    if code in _KB_SPECIAL:
        b = _KB_SPECIAL[code]
        if ctrl and b[:1] == b"\x1b" and len(b) == 1:
            return b"\x00"      # Ctrl+Esc
        return (b"\x1b" + b) if alt and code not in (56, 100) else b
    ch = _KEY_BASE.get(code)
    if ch is None:
        return None
    if ctrl:
        if ch.isalpha():
            return bytes([ord(ch.lower()) - 96])
        if ch == " ":
            return b"\x00"
        return None
    if ch.isalpha():
        out = ch.upper() if (shift or caps) else ch
    else:
        out = REV_SHIFT.get(ch, ch) if shift else ch
    return (b"\x1b" + out.encode()) if alt else out.encode()

class UsbKbd(threading.Thread):
    """USB实体键盘: 独占(EVIOCGRAB)直读HID事件 -> 终端字节流"""
    EVIOCGNAME = 0x81004506
    def __init__(self, on_bytes=None):
        super().__init__(daemon=True)
        self.on_bytes = on_bytes or (lambda b: None)
        self.claimed = set()
    def run(self):
        while True:
            for i in range(8):
                path = "/dev/input/event%d" % i
                if path in self.claimed:
                    continue
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    continue
                buf = bytearray(256)
                try:
                    fcntl.ioctl(fd, self.EVIOCGNAME, buf)
                except OSError:
                    os.close(fd); continue
                name = bytes(buf).split(b"\x00")[0].decode("utf-8", "replace")
                if "keyboard" not in name.lower() or "consumer" in name.lower() or "system" in name.lower():
                    os.close(fd); continue
                try:
                    fcntl.ioctl(fd, 0x40044590, 1)   # EVIOCGRAB 独占(不漏给tty1)
                except OSError:
                    pass
                self.claimed.add(path)
                print("usb kbd claimed:", name, flush=True)
                threading.Thread(target=self._reader, args=(fd, path), daemon=True).start()
            time.sleep(2)
    def _reader(self, fd, path):
        shift = ctrl = alt = caps = False
        while True:
            try:
                data = os.read(fd, 24)
            except BlockingIOError:
                time.sleep(0.01); continue
            except OSError:
                self.claimed.discard(path)   # 设备断开: 释放认领, 等rescan重新接管
                return
            if not data:
                self.claimed.discard(path)
                return
            if len(data) != 24:
                continue
            _, _, t, code, val = EVENT.unpack(data)
            if t != 1:
                continue
            if code in (42, 54):
                shift = val > 0; continue
            if code in (29, 97):
                ctrl = val > 0; continue
            if code in (56, 100):
                alt = val > 0; continue
            if code == 58 and val == 1:
                caps = not caps; continue
            if val in (1, 2):        # 1=按下 2=长按重复
                b = kb_translate(code, shift, ctrl, alt, caps)
                if b:
                    self.on_bytes(b)

class GUI:
    def __init__(self):
        unbind_fbcon()
        self.disp = Display()
        self.canvas = Image.new("L", (W, H), 0)
        self.d = ImageDraw.Draw(self.canvas)
        self.wakeup = threading.Event()
        self.cols = (W - 2*PAD) // CELL_W
        self.term = Term(self.cols, self._rows_for(True), on_data=self.wakeup.set)   # 键盘常驻
        self.pen = Pen(on_click=self.wakeup.set); self.pen.start()
        self.buttons = Buttons(on_key=self.wakeup.set); self.buttons.start()
        self.usbkbd = UsbKbd(on_bytes=lambda b: (self.term.write(b), self.wakeup.set()))
        self.usbkbd.start()
        feed_temp_once()
        threading.Thread(target=feed_temp_loop, daemon=True).start()
        # 实体键/电源键设为唤醒源(休眠后能叫醒)
        for n in ("input0", "input1"):
            try:
                open("/sys/class/input/%s/device/power/wakeup" % n, "w").write("enabled")
            except OSError:
                pass
        self.kb_visible = True
        self.wifi_visible = False
        self.shift = False
        self.caps = False
        self.ctrl = False
        self.alt = False
        self.sym = False
        self.nets = []
        self.sel = None
        self.psk = ""
        self.status = ""
        self.hits = {}
        self.kb_rects = []
        self.wifi_kb = []
        self.last_lines = []
        self.last_cursor = (-1, -1, True)
        self.kb_dirty = True
        # 中文输入法
        import json
        try:
            self.pydict = json.load(open("/usr/local/share/pinyin_dict.json"))
        except Exception:
            self.pydict = {}
        self.ime = False
        self.py_buf = ""
        self.cands = []
        self.cand_page = 0
        self.py_dirty = True
        self.py_hits = {}

    def _rows_for(self, kb):
        area_h = H - TOPBAR - (KB_H if kb else 0) - PAD
        return max(8, area_h // CELL_H)

    def key_bytes(self, ch):
        if ch == "\x08":
            return b"\x7f"
        if ch == "\n":
            return b"\r"
        if ch == "\t":
            return b"\t"
        use = ch
        if ch.isalpha():
            use = ch.upper() if (self.caps or self.shift) else ch
        else:
            use = REV_SHIFT.get(ch, ch) if self.shift else ch
        out = b""
        if self.alt:
            out += b"\x1b"
        if self.ctrl:
            if ch.isalpha():
                return out + bytes([ord(ch.lower()) - 96])
            if ch == " ":
                return out + b"\x00"
        return out + use.encode()

    # ---------- 中文输入法 ----------
    def refresh_cands(self):
        b = self.py_buf
        c = self.pydict.get(b)
        while not c and len(b) > 1:
            b = b[:-1]
            c = self.pydict.get(b)
        self.cands = c or []
        self.cand_page = 0

    def clear_py(self):
        self.py_buf = ""
        self.cands = []
        self.cand_page = 0
        self.py_dirty = True

    def commit(self, word):
        self.term.write(word.encode("utf-8"))
        self.clear_py()

    def draw_pybar(self):
        """拼音候选栏(键盘上方); 返回(hits, region)"""
        if not self.py_buf or self.wifi_visible or not self.kb_visible:
            return {}, None
        y = H - KB_H - 64
        self.d.rectangle([0, y, W, y + 64], fill=255)
        self.d.rectangle([0, y, W, y + 64], outline=0, width=3)
        self.d.text((12, y + 14), self.py_buf, font=F_ITEM, fill=0)
        x = 230
        page = self.cands[self.cand_page*8 : self.cand_page*8 + 8]
        hits = {}
        for i, w in enumerate(page):
            label = "%d%s" % (i + 1, w)
            self.d.text((x, y + 14), label, font=F_ITEM, fill=0)
            bw = int(self.d.textlength(label, font=F_ITEM)) + 24
            hits[("cand", i)] = (x, y, bw, 64)
            x += bw
        self.d.text((W - 176, y + 14), "上页", font=F_ITEM, fill=0)
        hits["cand_prev"] = (W - 190, y, 90, 64)
        self.d.text((W - 86, y + 14), "下页", font=F_ITEM, fill=0)
        hits["cand_next"] = (W - 100, y, 90, 64)
        return hits, (0, y, W, 64)

    # ---------- 绘制 ----------
    def draw_wired(self, on):
        """顶栏WiFi左侧: 有线网状态(连接成功才显示, 否则留空)"""
        self.d.rectangle([W - 770, 0, W - 590, TOPBAR], fill=0)
        if on:
            self.d.text((W - 752, 22), "有线", font=F_ITEM, fill=255)

    def draw_battery(self, cap, st):
        """顶栏电池(最右): 图标 + 电量% + 充放电状态"""
        self.d.rectangle([W - 310, 0, W, TOPBAR], fill=0)   # 清出电池区
        if cap is None:
            return
        bx, by, bw, bh = W - 296, 20, 52, 28
        self.d.rectangle([bx, by, bx + bw, by + bh], outline=255, width=3)
        self.d.rectangle([bx + bw + 2, by + 8, bx + bw + 8, by + bh - 8], fill=255)
        try:
            fillw = max(0, int((bw - 8) * int(cap) / 100))
        except ValueError:
            fillw = 0
        if fillw:
            self.d.rectangle([bx + 4, by + 4, bx + 4 + fillw, by + bh - 4], fill=255)
        self.d.text((W - 230, 14), cap + "%", font=F_ITEM, fill=255)
        label = {"Charging": "充电中", "Full": "已满"}.get(st, "放电中")
        self.d.text((W - 112, 14), label, font=F_SMALL, fill=255)

    def btn(self, d, xy, text, sz=F_ITEM, inv=False):
        x, y, w, h = xy
        d.rectangle([x, y, x+w, y+h], fill=0 if inv else 255, outline=0, width=4)
        bb = d.textbbox((0, 0), text, font=sz)
        d.text((x+(w-(bb[2]-bb[0]))/2 - bb[0], y+(h-(bb[3]-bb[1]))/2 - bb[1]),
               text, font=sz, fill=255 if inv else 0)
        return (x, y, w, h)

    def osk(self, d, top):
        kh, gap = 78, 6
        rects = []
        if self.sym:
            rows = [[(c, c, 1) for c in "1234567890"],
                    [(c, c, 1) for c in "!@#$%^&*()"],
                    [(c, c, 1) for c in "-_=+[]{}|\\"],
                    [(c, c, 1) for c in "':;,.<>/?~"],
                    [("字母", "\x02", 2), ("中英", "\x06", 1.5), ("Shift", "\x01", 1.5), ("Ctrl", "\x03", 1.5),
                     ("空格", " ", 4), ("退格", "\x08", 1.5), ("回车", "\n", 2)]]
        else:
            rows = [
                [(c, c, 1) for c in "`1234567890-="] + [("退格", "\x08", 2)],
                [("Tab", "\t", 1.5)] + [(c.upper(), c, 1) for c in "qwertyuiop"]
                    + [(c, c, 1) for c in "[]"] + [("\\", "\\", 1.5)],
                [("大写", "\x05", 1.75)] + [(c.upper(), c, 1) for c in "asdfghjkl"]
                    + [(c, c, 1) for c in "';"] + [("回车", "\n", 2.25)],
                [("Shift", "\x01", 2.25)] + [(c.upper(), c, 1) for c in "zxcvbnm"]
                    + [(c, c, 1) for c in ",./"] + [("Shift", "\x01", 2.75)],
                [("Ctrl", "\x03", 1.5), ("符号", "\x02", 1.5), ("中英", "\x06", 1.5),
                 ("Alt", "\x04", 1.5), ("空格", " ", 5.5), ("Alt", "\x04", 1.5), ("Ctrl", "\x03", 1.5)],
            ]
        y = top
        for row in rows:
            n = len(row)
            total = sum(wu for _, _, wu in row)
            unit = (W - 40 - gap * (n - 1)) / total
            x = 20
            for label, ch, wu in row:
                wpx = int(unit * wu)
                inv = ((ch == "\x01" and self.shift) or (ch == "\x05" and self.caps)
                       or (ch == "\x03" and self.ctrl) or (ch == "\x06" and self.ime)
                       or (ch == "\x04" and self.alt) or (ch == "\x02" and self.sym))
                self.btn(d, (x, y, wpx, kh), label, F_SMALL, inv=inv)
                rects.append(((x, y, wpx, kh), ch))
                x += wpx + gap
            y += kh + gap
        return rects

    @staticmethod
    def hit(rects, pos):
        for r, val in rects:
            if inside(pos, r):
                return val
        return None

    def draw_term_row(self, y, line, cursor=None):
        """把一行终端文本画进canvas(黑底白字+反显+光标)"""
        ty = TOPBAR + PAD + y * CELL_H
        self.d.rectangle([0, ty - 2, W, ty + CELL_H + 2], fill=0)
        cols = self.term.cols
        self.d.text((PAD, ty), line[:cols], font=F_MONO, fill=255)
        with self.term.lock:
            row = self.term.screen.buffer[y]
        x = 0
        while x < cols:
            c = row[x]
            if c.reverse:
                x2 = x
                while x2 < cols and row[x2].reverse:
                    x2 += 1
                rx = PAD + x * CELL_W
                self.d.rectangle([rx, ty, rx + (x2-x)*CELL_W, ty + CELL_H], fill=255)
                seg = "".join(row[i].data for i in range(x, x2) if row[i].data != "")
                self.d.text((rx, ty), seg, font=F_MONO, fill=0)
                x = x2
            else:
                x += 1
        if cursor is not None and cursor[1] == y:
            cx, cy, hidden = cursor
            if not hidden and 0 <= cx < cols:
                rx = PAD + cx * CELL_W
                self.d.rectangle([rx, ty, rx + CELL_W, ty + CELL_H], fill=255)
                ch = row[cx].data if row[cx].data != "" else " "
                if ch.strip():
                    self.d.text((rx, ty), ch, font=F_MONO, fill=0)

    def compose(self):
        """全量: 顶栏+终端+键盘+WiFi弹窗 -> canvas"""
        self.d.rectangle([0, 0, W, H], fill=0)
        hits = {}
        self.d.rectangle([0, 0, W, TOPBAR], fill=0)
        self.d.text((20, 14), self.status or "N10", font=F_ITEM, fill=255)
        hits["btn_wifi"] = self.btn(self.d, (W-590, 9, 130, 58), "WiFi", F_SMALL)
        hits["btn_refresh"] = self.btn(self.d, (W-450, 9, 130, 58), "刷新", F_SMALL)
        self.last_batt = read_battery()
        self.draw_battery(*self.last_batt)
        self.last_wired = wired_connected()
        self.draw_wired(self.last_wired)
        kb_top = H - KB_H + 10
        if self.wifi_visible:
            # WiFi整页: 白底内容区 + 底部键盘(与终端页同一位置)
            self.d.rectangle([0, TOPBAR, W, kb_top], fill=255)
            self.d.text((66, 96), "WiFi 设置", font=F_TITLE, fill=0)
            y = 190
            for i, n in enumerate(self.nets[:5]):
                label = n["ssid"][:16] + (" [锁]" if "WPA" in n["flags"] or "RSN" in n["flags"] else " [开放]")
                hits[("net", i)] = self.btn(self.d, (66, y, W-132, 72), label, F_ITEM, inv=(self.sel == i))
                y += 80
            if not self.nets:
                self.btn(self.d, (66, y, W-132, 72), "扫描中...", F_ITEM)
            hits["psk_box"] = self.btn(self.d, (66, y+8, W-380, 72), "密码: " + "*" * len(self.psk), F_ITEM)
            hits["scan"] = self.btn(self.d, (W-300, y+8, 230, 72), "扫描", F_ITEM)
            by = kb_top - 160
            hits["connect"] = self.btn(self.d, (W//2-330, by, 310, 94), "连 接", F_TITLE, inv=True)
            hits["close"] = self.btn(self.d, (W//2+20, by, 310, 94), "关 闭", F_TITLE)
            self.kb_rects = self.osk(self.d, kb_top)
            self.wifi_kb = self.kb_rects
        else:
            # 终端页
            term_h = kb_top - 10 - TOPBAR
            self.d.rectangle([0, TOPBAR, W, TOPBAR + term_h], fill=0)
            with self.term.lock:
                display = list(self.term.screen.display)
                cur = (self.term.screen.cursor.x, self.term.screen.cursor.y, self.term.screen.cursor.hidden)
            for y in range(min(self.term.rows, len(display))):
                self.draw_term_row(y, display[y], cur)
            self.last_lines = display
            self.last_cursor = cur
            hits["term_area"] = (0, TOPBAR, W, term_h)
            self.kb_rects = self.osk(self.d, kb_top)
            self.wifi_kb = []
        self.kb_dirty = False
        pyh, pyreg = self.draw_pybar()
        self.py_hits = pyh
        self.py_was_visible = pyreg is not None
        self.py_dirty = False
        return hits

    def render(self, full=False):
        self.term.dirty = False      # 先清: 渲染中到达的新数据会重新置位
        self.hits = self.compose()
        self.disp.show(self.canvas)
        if full:
            self.disp.full_refresh()

    def update_fast(self):
        """行级增量: 只画变化行并局部写fb"""
        self.term.dirty = False      # 先清: 渲染中到达的新数据会重新置位
        if self.wifi_visible:
            self.render(full=False)
            return
        with self.term.lock:
            display = list(self.term.screen.display)
            cur = (self.term.screen.cursor.x, self.term.screen.cursor.y, self.term.screen.cursor.hidden)
        changed = set()
        for y in range(min(self.term.rows, len(display))):
            if y >= len(self.last_lines) or self.last_lines[y] != display[y]:
                changed.add(y)
        if cur != self.last_cursor:
            changed.add(cur[1])
            changed.add(self.last_cursor[1])
        regions = []
        for y in sorted(changed):
            if 0 <= y < self.term.rows and y < len(display):
                self.draw_term_row(y, display[y], cur)
                ty = TOPBAR + PAD + y * CELL_H
                regions.append((0, ty - 2, W, CELL_H + 4))
        self.last_lines = display
        self.last_cursor = cur
        if self.kb_dirty and self.kb_visible and not self.wifi_visible:
            self.d.rectangle([0, H - KB_H, W, H], fill=255)
            self.kb_rects = self.osk(self.d, H - KB_H + 10)
            regions.append((0, H - KB_H, W, KB_H))
            self.kb_dirty = False
        bar_y = H - KB_H - 64
        bar_on = bool(self.py_buf) and self.kb_visible and not self.wifi_visible
        if self.py_dirty or bar_on:
            pyh, pyreg = self.draw_pybar()
            self.py_hits = pyh
            if pyreg is not None:
                regions.append(pyreg)
                self.py_was_visible = True
            elif getattr(self, "py_was_visible", False):
                # 候选栏消失: 整条涂黑(行网格到不了栏底), 再画回终端行
                self.d.rectangle([0, bar_y, W, bar_y + 64], fill=0)
                for y in range(min(self.term.rows, len(display))):
                    ty = TOPBAR + PAD + y * CELL_H
                    if ty + CELL_H > bar_y and ty < bar_y + 64:
                        self.draw_term_row(y, display[y], cur)
                regions.append((0, bar_y, W, 64))
                self.py_was_visible = False
            self.py_dirty = False
        # 状态文字变化时刷新顶栏左侧
        if self.status != getattr(self, "last_status", None):
            self.last_status = self.status
            self.d.rectangle([0, 0, 520, TOPBAR], fill=0)
            self.d.text((20, 14), self.status or "N10", font=F_ITEM, fill=255)
            regions.append((0, 0, 520, TOPBAR))
        # 电池变化时刷新顶栏(每轮都查, 很轻)
        b = read_battery()
        if b != getattr(self, "last_batt", None):
            self.last_batt = b
            self.draw_battery(*b)
            regions.append((0, 0, W, TOPBAR))
        # 有线网状态变化时刷新WiFi左侧
        wn = wired_connected()
        if wn != getattr(self, "last_wired", None):
            self.last_wired = wn
            self.draw_wired(wn)
            regions.append((W - 770, 0, 180, TOPBAR))
        for r in regions:
            self.disp.write_region(self.canvas, *r)

    # ---------- 事件 ----------
    def run(self):
        self.render(full=True)
        while True:
            self.wakeup.wait(1.0)
            self.wakeup.clear()
            full = False
            act = None
            while True:
                try:
                    pos = self.pen.clicks.get_nowait()
                except queue.Empty:
                    break
                print("click at", pos, flush=True)
                try:
                    a = self.handle(pos)
                except Exception as e:
                    import traceback; traceback.print_exc()
                    self.status = "错误: %s" % e
                    a = "full"
                if a == "full":
                    full = True
                elif a:
                    act = a
            while True:
                try:
                    code = self.buttons.keys.get_nowait()
                except queue.Empty:
                    break
                print("button code", code, flush=True)
                try:
                    a = self.handle_btn(code)
                except Exception as e:
                    import traceback; traceback.print_exc()
                    a = "full"
                if a == "full":
                    full = True
                elif a:
                    act = a
            if getattr(self, "need_clear", False):
                self.need_clear = False
                act = "clear"
            if act == "clear":
                self.panel_reset()
            elif full:
                self.render(full=True)
            elif act == "redraw":
                self.render(full=False)
            else:
                self.update_fast()   # 回显/状态变化都走增量

    def handle(self, pos):
        h = self.hits
        if inside(pos, h.get("btn_wifi", (0,0,0,0))):
            self.wifi_visible = not self.wifi_visible
            if self.wifi_visible and not self.nets:
                self.status = "扫描中..."
                self.render(full=False)
                self.nets = Wifi.scan()
                self.status = ""
            return "full"
        if inside(pos, h.get("btn_refresh", (0,0,0,0))):
            return "clear"      # 维护刷新(RESET清泛白)
        # 拼音候选栏
        if self.py_buf and self.kb_visible and not self.wifi_visible:
            for k, r in list(self.py_hits.items()):
                if isinstance(k, tuple) and k[0] == "cand" and inside(pos, r):
                    idx = k[1] + self.cand_page * 8
                    if idx < len(self.cands):
                        self.commit(self.cands[idx])
                    return "fast"
            if inside(pos, self.py_hits.get("cand_prev", (0, 0, 0, 0))):
                self.cand_page = max(0, self.cand_page - 1)
                self.py_dirty = True
                return "fast"
            if inside(pos, self.py_hits.get("cand_next", (0, 0, 0, 0))):
                if (self.cand_page + 1) * 8 < len(self.cands):
                    self.cand_page += 1
                self.py_dirty = True
                return "fast"
        if self.wifi_visible:
            return self.handle_wifi(pos)
        ch = self.hit(self.kb_rects, pos)
        if ch is not None:
            return self.handle_key(ch)
        return None

    def handle_btn(self, code):
        """实体按键: 1上翻页 2下翻页 3音量+ 4音量- 5(HOME)=Esc 9=刷新"""
        if code == 594:
            with self.term.lock:
                self.term.screen.prev_page()
            self.term.dirty = True
            return "fast"
        if code == 595:
            with self.term.lock:
                self.term.screen.next_page()
            self.term.dirty = True
            return "fast"
        if code == 596:
            self.volume(+1)
            return "fast"
        if code == 597:
            self.volume(-1)
            return "fast"
        if code == 158:      # HOME = Esc
            self.term.write(b"\x1b")
            return None
        if code == 598:      # 6 = 命令历史上
            self.term.write(b"\x1b[A")
            return None
        if code == 599:      # 7 = 命令历史下
            self.term.write(b"\x1b[B")
            return None
        if code == 600:      # 8 = 休眠/唤醒(唤醒那下忽略3秒防误触发)
            if time.time() < getattr(self, "suspend_guard", 0):
                return None
            self.suspend_guard = time.time() + 3
            self.status = "休眠中..."
            threading.Thread(target=self._suspend, daemon=True).start()
            return "full"
        if code == 601:      # 9 = 维护刷新(RESET清泛白)
            return "clear"
        return None

    def _suspend(self):
        time.sleep(0.6)          # 留时间把"休眠中"画上屏
        try:
            open("/sys/power/state", "w").write("mem")
        except OSError as e:
            self.status = "休眠失败"
            self.wakeup.set()
            return
        # 唤醒后: 忽略唤醒键, 等屏幕驱动稳定再维护刷新
        self.suspend_guard = time.time() + 3
        time.sleep(1)
        self.status = ""
        self.need_clear = True
        self.wakeup.set()

    def panel_reset(self):
        """维护刷新: RESET波形初始化面板(治泛白/残影), 再GC16画回内容"""
        try:
            open("/sys/module/rockchip_ebc/parameters/refresh_waveform", "w").write("0")
        except OSError:
            pass
        self.disp.full_refresh()          # RESET: 面板初始化
        time.sleep(0.8)
        try:
            open("/sys/module/rockchip_ebc/parameters/refresh_waveform", "w").write("4")
        except OSError:
            pass
        self.render(full=True)            # GC16 画回内容

    def volume(self, d):
        try:
            subprocess.run(["amixer", "-q", "sset", "Master", "5%+" if d > 0 else "5%-"],
                           capture_output=True, timeout=3)
            self.status = "音量" + ("+" if d > 0 else "-")
        except Exception:
            self.status = "无音频设备"

    def toggle_kb(self):
        self.kb_visible = not self.kb_visible
        self.term.resize(self.cols, self._rows_for(self.kb_visible))

    def handle_key(self, ch):
        if ch in ("\x01", "\x05", "\x02", "\x03", "\x04", "\x06"):
            if ch == "\x01":
                self.shift = not self.shift
            elif ch == "\x05":
                self.caps = not self.caps
            elif ch == "\x02":
                self.sym = not self.sym
            elif ch == "\x03":
                self.ctrl = not self.ctrl
            elif ch == "\x04":
                self.alt = not self.alt
            elif ch == "\x06":
                self.ime = not self.ime
                if not self.ime:
                    self.clear_py()
            self.kb_dirty = True
            return "fast"
        if self.ime and not (self.ctrl or self.alt):
            return self.handle_ime(ch)
        self.term.write(self.key_bytes(ch))
        if self.shift:
            self.shift = False
            self.kb_dirty = True
            return "fast"
        if self.ctrl or self.alt:
            self.ctrl = self.alt = False
            self.kb_dirty = True
            return "fast"
        # 长按连发放后台线程(不阻塞画面更新)
        threading.Thread(target=self._repeat, args=(ch,), daemon=True).start()
        return None

    def _repeat(self, ch):
        time.sleep(0.45)      # 按住0.45s后开始连发
        while self.pen._down and self.hit(self.kb_rects, fb2vis(*self.pen.fbpos)) == ch:
            self.term.write(self.key_bytes(ch))
            time.sleep(0.2)

    def handle_ime(self, ch):
        """拼音输入: 字母进缓冲, 数字/空格选词"""
        if ch.isalpha():
            self.py_buf += ch.lower()
            self.refresh_cands()
            self.py_dirty = True
            return "fast"
        if self.py_buf:
            if ch.isdigit() and ch != "0":
                idx = int(ch) - 1 + self.cand_page * 8
                if idx < len(self.cands):
                    self.commit(self.cands[idx])
                return "fast"
            if ch == " ":
                if self.cands:
                    self.commit(self.cands[self.cand_page * 8])
                return "fast"
            if ch == "\x08":
                self.py_buf = self.py_buf[:-1]
                self.refresh_cands()
                self.py_dirty = True
                return "fast"
            if ch == "\n":
                raw = self.py_buf
                self.clear_py()
                self.term.write(raw.encode() + b"\r")
                return "fast"
            # 其他符号: 先上屏首选再发符号
            if self.cands:
                self.commit(self.cands[self.cand_page * 8])
            else:
                self.clear_py()
            self.term.write(self.key_bytes(ch))
            self.shift = False
            return "fast"
        self.term.write(self.key_bytes(ch))
        return None

    def handle_wifi(self, pos):
        h = self.hits
        for k, r in list(h.items()):
            if isinstance(k, tuple) and k[0] == "net" and inside(pos, r):
                self.sel = k[1]
                self.status = "选中 " + self.nets[k[1]]["ssid"]
                return "redraw"
        if inside(pos, h.get("scan", (0,0,0,0))):
            self.status = "扫描中..."
            self.render(full=False)
            self.nets = Wifi.scan()
            self.status = "找到%d个" % len(self.nets)
            return "full"
        if inside(pos, h.get("connect", (0,0,0,0))):
            if self.sel is None:
                self.status = "先选网络"
                return "redraw"
            Wifi.connect(self.nets[self.sel]["ssid"], self.psk)
            self.status = "已连接 " + self.nets[self.sel]["ssid"]
            self.wifi_visible = False
            return "full"
        if inside(pos, h.get("close", (0,0,0,0))):
            self.wifi_visible = False
            self.status = ""
            return "full"
        ch = self.hit(self.wifi_kb, pos) if self.wifi_kb else None
        if ch is not None:
            if ch in ("\x01", "\x05", "\x02", "\x03", "\x04", "\x06"):
                if ch == "\x01":
                    self.shift = not self.shift
                elif ch == "\x05":
                    self.caps = not self.caps
                elif ch == "\x02":
                    self.sym = not self.sym
                elif ch == "\x03":
                    self.ctrl = not self.ctrl
                elif ch == "\x04":
                    self.alt = not self.alt
                elif ch == "\x06":
                    self.ime = not self.ime
                return "redraw"
            if ch == "\x08":
                self.psk = self.psk[:-1]
            elif ch == "\n":
                if self.sel is not None:
                    Wifi.connect(self.nets[self.sel]["ssid"], self.psk)
                    self.status = "已连接 " + self.nets[self.sel]["ssid"]
                    self.wifi_visible = False
                    return "full"
            else:
                use = ch
                if ch.isalpha():
                    use = ch.upper() if (self.caps or self.shift) else ch
                else:
                    use = REV_SHIFT.get(ch, ch) if self.shift else ch
                if len(self.psk) < 32:
                    self.psk += use
            self.shift = False
            return "redraw"
        return None

if __name__ == "__main__":
    GUI().run()
