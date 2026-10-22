#!/usr/bin/env python3
"""hanvon_pen: 汉王N10电磁笔守护进程
ttyS0@57600 读7字节包 -> 解析 -> uinput标准指针设备
参数来自原厂dts: screen_max_x=1872 screen_max_y=1404 hw_hmax=7422 hw_wmax=10206
revert_x=0 revert_y=1 exchange=0
"""
import os, struct, termios, fcntl, time, sys

SERIAL_DEV = "/dev/ttyS0"
BAUD = 57600
UINPUT = "/dev/uinput"

SCREEN_MAX_X = 1872
SCREEN_MAX_Y = 1404
HW_HMAX = 7422
HW_WMAX = 10206
REVERT_X = 0
REVERT_Y = 1
EXCHANGE_XY = 0

# 四角校准文件: "rx_lo rx_hi ry_lo ry_hi"(raw坐标在fb_x=0/1871, fb_y=0/1403处的值)
# 视觉方向已验证: packet-X递增=视觉顶(fb_x递增), packet-Y递增=视觉右(fb_y递增) -> 直接线性映射
CALIB_FILE = "/etc/pen-calib"
_calib = None
try:
    with open(CALIB_FILE) as f:
        _calib = tuple(float(v) for v in f.read().split())
except OSError:
    pass

# input event codes
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
BTN_TOUCH = 0x14a
BTN_TOOL_PEN = 0x140
BTN_TOOL_RUBBER = 0x141
BTN_STYLUS = 0x145
ABS_X, ABS_Y, ABS_PRESSURE = 0x00, 0x01, 0x18

UI_SET_EVBIT  = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_CREATE = 0x5501
UI_DEV_SETUP  = 0x405c5503
UI_ABS_SETUP  = 0x401c5504

EVENT_STRUCT = struct.Struct("<qqHHi")   # input_event on 64-bit

def open_uinput():
    fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
    fcntl.ioctl(fd, UI_SET_EVBIT, EV_ABS)
    for k in (BTN_TOUCH, BTN_TOOL_PEN, BTN_TOOL_RUBBER, BTN_STYLUS):
        fcntl.ioctl(fd, UI_SET_KEYBIT, k)
    for a in (ABS_X, ABS_Y, ABS_PRESSURE):
        fcntl.ioctl(fd, UI_SET_ABSBIT, a)
    # uinput_setup: input_id(8B) + name[80] + ff_effects_max(4B) = 92
    name = b"hanvon_pen"
    setup = struct.pack("<HHHH80sI", 0x03, 0x2b50, 0x0868, 1, name, 0)  # BUS_USB, vendor=汉王
    fcntl.ioctl(fd, UI_DEV_SETUP, setup)
    # uinput_abs_setup: code(4B) + input_absinfo(24B)
    def abs_setup(code, lo, hi):
        st = struct.pack("<Iiiiiii", code, 0, lo, hi, 0, 0, 0)
        fcntl.ioctl(fd, UI_ABS_SETUP, st)
    abs_setup(ABS_X, 0, SCREEN_MAX_X - 1)
    abs_setup(ABS_Y, 0, SCREEN_MAX_Y - 1)
    abs_setup(ABS_PRESSURE, 0, 1023)
    fcntl.ioctl(fd, UI_DEV_CREATE)
    return fd

def open_serial():
    fd = os.open(SERIAL_DEV, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[4] = a[5] = getattr(termios, "B%d" % BAUD)
    a[2] |= termios.CREAD | termios.CLOCAL
    a[3] = 0; a[0] = 0; a[1] = 0
    a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd

def emit(fd, ev_type, code, value):
    os.write(fd, EVENT_STRUCT.pack(0, 0, ev_type, code, value))

def transform(rx, ry):
    if _calib and len(_calib) == 4:
        rx_lo, rx_hi, ry_lo, ry_hi = _calib
        x = round((rx - rx_lo) * (SCREEN_MAX_X - 1) / (rx_hi - rx_lo))
        y = round((ry - ry_lo) * (SCREEN_MAX_Y - 1) / (ry_hi - ry_lo))
    else:
        x = rx * (SCREEN_MAX_X - 1) // HW_HMAX
        y = ry * (SCREEN_MAX_Y - 1) // HW_WMAX
    x = max(0, min(SCREEN_MAX_X - 1, x))
    y = max(0, min(SCREEN_MAX_Y - 1, y))
    return x, y

def parse_packet(p):
    b0, b1, b2, b3, b4, b5, b6 = p
    x = (b1 << 9) | (b2 << 2) | ((b6 >> 5) & 3)
    y = (b3 << 9) | (b4 << 2) | ((b6 >> 3) & 3)
    pr = ((b6 & 7) << 7) | (b5 & 0x7f)
    return b0, x, y, pr

def is_hdr(b):
    return (b & 0x80) and (b & 0x0f) <= 5

def gpio_setup():
    """ASIC上电时序: pwr_en(15)=高 update(151)=低 reset(16)=高->低->高脉冲"""
    for g in (15, 151, 16):
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(str(g))
        except OSError:
            pass  # 已导出
    time.sleep(0.1)
    def setv(g, v):
        with open(f"/sys/class/gpio/gpio{g}/value", "w") as f:
            f.write(str(v))
    for g in (15, 151, 16):
        try:
            with open(f"/sys/class/gpio/gpio{g}/direction", "w") as f:
                f.write("out")
        except OSError:
            pass
    setv(15, 1); setv(151, 0); setv(16, 1)
    time.sleep(0.05); setv(16, 0)
    time.sleep(0.05); setv(16, 1)
    time.sleep(0.2)

def main():
    try:
        gpio_setup()
    except OSError as e:
        sys.stderr.write(f"hanvon_pen: gpio init warn: {e}\n")
    ufd = open_uinput()
    sfd = open_serial()
    sys.stderr.write("hanvon_pen: started (ttyS0@57600)\n")
    sys.stderr.flush()
    buf = b""
    tool_state = 0   # 0=none 1=pen 2=rubber
    touch_state = 0
    stylus_state = 0
    while True:
        try:
            data = os.read(sfd, 512)
        except BlockingIOError:
            time.sleep(0.002)
            continue
        buf += data
        while len(buf) >= 7:
            if not is_hdr(buf[0]):
                # 重新对齐: 跳到下一个包头
                j = 1
                while j < len(buf) and not is_hdr(buf[j]):
                    j += 1
                buf = buf[j:]
                continue
            pkt, buf = buf[:7], buf[7:]
            b0, rx, ry, pressure = parse_packet(pkt)
            x, y = transform(rx, ry)
            emit(ufd, EV_ABS, ABS_X, x)
            emit(ufd, EV_ABS, ABS_Y, y)
            emit(ufd, EV_ABS, ABS_PRESSURE, pressure)
            changed = False
            if b0 == 0xa1:      # 悬停/进入感应区
                if tool_state != 1:
                    if tool_state == 2:
                        emit(ufd, EV_KEY, BTN_TOOL_RUBBER, 0); tool_state = 0
                    emit(ufd, EV_KEY, BTN_TOOL_PEN, 1); tool_state = 1; changed = True
                if touch_state:
                    emit(ufd, EV_KEY, BTN_TOUCH, 0); touch_state = 0; changed = True
            elif b0 == 0xa0:    # 书写/按下
                if tool_state != 1:
                    if tool_state == 2:
                        emit(ufd, EV_KEY, BTN_TOOL_RUBBER, 0); tool_state = 0
                    emit(ufd, EV_KEY, BTN_TOOL_PEN, 1); tool_state = 1; changed = True
                t = 1 if pressure > 0 else 0
                if t != touch_state:
                    emit(ufd, EV_KEY, BTN_TOUCH, t); touch_state = t; changed = True
            elif b0 == 0xa2:    # 离开感应区
                if tool_state:
                    emit(ufd, EV_KEY, BTN_TOOL_PEN, 0)
                    emit(ufd, EV_KEY, BTN_TOOL_RUBBER, 0)
                    tool_state = 0; changed = True
                if touch_state:
                    emit(ufd, EV_KEY, BTN_TOUCH, 0); touch_state = 0; changed = True
                if stylus_state:
                    emit(ufd, EV_KEY, BTN_STYLUS, 0); stylus_state = 0; changed = True
            elif b0 == 0xa3:    # 侧键
                if not stylus_state:
                    emit(ufd, EV_KEY, BTN_STYLUS, 1); stylus_state = 1; changed = True
            elif b0 == 0xa5:    # 橡皮擦
                if tool_state != 2:
                    if tool_state == 1:
                        emit(ufd, EV_KEY, BTN_TOOL_PEN, 0); tool_state = 0
                    emit(ufd, EV_KEY, BTN_TOOL_RUBBER, 1); tool_state = 2; changed = True
            # 每个包都发SYN(坐标更新)
            emit(ufd, EV_SYN, SYN_REPORT, 0)

if __name__ == "__main__":
    main()
