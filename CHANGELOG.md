# Changelog

以刷机镜像版本为序。日期是定稿时间。

## v5 — 2026-10-23

- USB 千兆网卡（ASIX AX88179A）驱动内置进内核。用 ASIX 官方开源驱动 ax_usb_nic，从内核自带的 ax88179_178a 那条路走不通，它到主线 master 都不认 179A
- USB 实体键盘拔插后自动重新接管。之前键盘换设备节点后 GUI 还认着旧的不放，按键全漏到 tty1，看起来像键盘坏了
- 顶栏加"有线"状态：插线且拿到 IP 才显示，位置在 WiFi 左侧
- 有线网口默认 DHCP（networkd 管理，热插拔有效）
- 出厂 rootfs 镜像固化全部服务：GUI、电磁笔、开机自启、WiFi/有线配置、输入法词库、Maple 字体、笔校准；并补装了 python3 全家（原镜像没有，GUI 起不来报 203/EXEC）

## v4 — 2026-10-23

- 修充电。插电显示放电的根因是 TypeC connector 缺三个 PD 属性（source-pdos/sink-pdos/op-sink-microwatt），fusb302 的 TCPM 注册失败，供电路径开关卡在放电方向，充电器的电被隔离在门外
- otg_switch 去掉 always-on，交给 TypeC 驱动按角色控制

## v3 — 2026-10-22

- USB 主机模式打通（DWC3 双角色 + TypeC）：Hub、键盘、U 盘可用
- 音频出声。rk8xx-core 给 codec 子设备补 of_node，RK817 声卡才肯出现

## v2 — 2026-10-22

- 墨水屏温度补偿定稿，治泛白。ebc 驱动无温度通道时硬编码 25°C，补丁让 temp_override 生效，GUI 每分钟喂实际温度
- 屏幕左切定稿（panel-simple vtotal 补偿，右移 7px）

## v1 — 2026-10-22

- 显示、电磁笔、输入、电池、按键、休眠的基本盘收齐。屏幕左切临时版（4px）、fp9931 驱动解决唤醒白屏、四角校准

## 更早 — 2026-10-20 ~ 21

- 初次点亮：安卓 boot 镜像直启 Ubuntu、墨水屏驱动（vtotal 左切根因破案）、电磁笔 uart5 协议逆向 + uinput 驱动、GUI（用户态终端 + 常驻键盘 + WiFi 页）、WiFi 固件入 initramfs、拼音输入法
