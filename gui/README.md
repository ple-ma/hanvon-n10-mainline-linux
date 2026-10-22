# gui/ — N10 墨水屏GUI全家桶

纯 Python（PIL + pyte），直接读写 `/dev/fb0`，无 X11/Wayland，专为10.3寸墨水屏定制。

| 文件 | 说明 |
|---|---|
| `n10gui.py` | 主界面：终端常驻 + 弹出键盘 + WiFi弹窗 + 拼音输入法 + 状态栏(WiFi/键盘/刷新/电池) |
| `pen_daemon.py` | 电磁笔守护进程：uart5@57600 → uinput指针设备`hanvon_pen`（四角校准） |
| `pen_calib.py` | 电磁笔四角校准工具（交互式，写`/etc/pen-calib`） |
| `build_pinyin.py` | 拼音词库构建（jieba词频 + CC-CEDICT + luna-pinyin，繁体过滤；词库本身不分发） |

## 依赖

```bash
apt install python3-pil fonts-wqy-zenhei   # 基础
pip install pyte                            # 终端模拟
```

等宽字体：`gui/n10gui.py` 默认用 Maple Mono NF CN（中英等宽+Nerd图标字形），放在
`/usr/local/share/fonts/MapleMono-NFCN.ttf`；没有的话换成任何"拉丁宽度=汉字一半"的
等宽字体并改 `MONO/CELL_W` 两个常量。

## 部署

```bash
cp n10gui.py pen_daemon.py pen-calib.py /usr/local/bin/
chmod +x /usr/local/bin/*.py
systemctl enable --now hanvon-pen.service    # 服务定义见下
```

`hanvon-pen.service`:
```ini
[Unit]
Description=Hanvon N10 EMR Pen (uart5@57600 -> uinput)
[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/pen_daemon.py
Restart=always
[Install]
WantedBy=multi-user.target
```

GUI 由 tty1 自启动运行（或 `systemctl` 任意方式拉起，需要 root——直写fb0与uinput）。

## 实体按键（gpio-keys → /dev/input/event0）

| 键 | 功能 |
|---|---|
| 1 / 2 | 终端上/下翻页 |
| 3 / 4 | 音量 + / − |
| 5 (HOME) | 全屏刷新 |
| 8 | 休眠 / 唤醒 |
| 6 / 7 | 终端上/下（历史命令） |

## 电磁笔协议（逆向结论）

- 链路：uart5 TTL @57600，**7字节定长包**，连续出流
- 帧头 `b0`：最高位1 + 低4位≤5
- 坐标：`x=(b1<<9)|(b2<<2)|((b6>>5)&3)`，`y=(b3<<9)|(b4<<2)|((b6>>3)&3)`
- 详细分析见 `../docs/journey.md`
