#!/usr/bin/env python3
"""pen-calib: 电磁笔四角校准
用法: systemctl stop hanvon-pen; python3 /usr/local/bin/pen-calib.py
按提示依次点屏幕四个角(左上->右上->右下->左下), 每角停2秒。
完成后写 /etc/pen-calib 并重启 hanvon-pen 服务。
"""
import os, struct, termios, time, sys, subprocess

SERIAL = "/dev/ttyS0"
BAUD = 57600
CORNERS = ["左上", "右上", "右下", "左下"]
SAMPLE_SECONDS = 3.0

def open_serial():
    fd = os.open(SERIAL, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    a = termios.tcgetattr(fd)
    a[4] = a[5] = getattr(termios, "B%d" % BAUD)
    a[2] |= termios.CREAD | termios.CLOCAL
    a[3] = 0; a[0] = 0; a[1] = 0
    a[6][termios.VMIN] = 0; a[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd

def is_hdr(b):
    return (b & 0x80) and (b & 0x0f) <= 5

def parse_packet(p):
    b0, b1, b2, b3, b4, b5, b6 = p
    x = (b1 << 9) | (b2 << 2) | ((b6 >> 5) & 3)
    y = (b3 << 9) | (b4 << 2) | ((b6 >> 3) & 3)
    return x, y

def sample(fd, seconds):
    buf = b""
    pts = []
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            buf += os.read(fd, 512)
        except BlockingIOError:
            time.sleep(0.005)
            continue
        while len(buf) >= 7:
            if not is_hdr(buf[0]):
                j = 1
                while j < len(buf) and not is_hdr(buf[j]):
                    j += 1
                buf = buf[j:]
                continue
            pkt, buf = buf[:7], buf[7:]
            x, y = parse_packet(pkt)
            pts.append((x, y))
    return pts

def main():
    fd = open_serial()
    corners = []
    for name in CORNERS:
        input(f"\n>>> 请用笔点住屏幕【{name}】角并保持, 然后回车开始采样...")
        pts = sample(fd, SAMPLE_SECONDS)
        if not pts:
            print("!! 没采到数据, 检查笔是否贴在屏幕上, 再来一次")
            return 1
        # 取中位数抗噪
        xs = sorted(p[0] for p in pts); ys = sorted(p[1] for p in pts)
        cx = xs[len(xs)//2]; cy = ys[len(ys)//2]
        corners.append((cx, cy))
        print(f"   {name}: raw=({cx}, {cy})  样本{len(pts)}个")
    # 4角 -> 线性映射
    (xtl, ytl), (xtr, ytr), (xbr, ybr), (xbl, ybl) = corners
    rx_hi = (xtl + xtr) / 2   # fb_x = 1871(视觉顶)
    rx_lo = (xbr + xbl) / 2   # fb_x = 0(视觉底)
    ry_lo = (ytl + ybl) / 2   # fb_y = 0(视觉左)
    ry_hi = (ytr + ybr) / 2   # fb_y = 1403(视觉右)
    if abs(rx_hi - rx_lo) < 100 or abs(ry_hi - ry_lo) < 100:
        print("!! 采样异常(某轴变化太小), 重跑")
        return 1
    with open("/etc/pen-calib", "w") as f:
        f.write(f"{rx_lo:.1f} {rx_hi:.1f} {ry_lo:.1f} {ry_hi:.1f}\n")
    print(f"\n校准写入 /etc/pen-calib: rx {rx_lo:.0f}->{rx_hi:.0f}, ry {ry_lo:.0f}->{ry_hi:.0f}")
    subprocess.run(["systemctl", "restart", "hanvon-pen.service"])
    print("hanvon-pen 已重启, 校准生效")
    return 0

if __name__ == "__main__":
    sys.exit(main())
