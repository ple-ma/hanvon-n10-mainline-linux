# Hanvon N10 Mainline Linux

把汉王 N10（RK3566 · 10.3寸墨水屏 ED103TC2U2 · EMR电磁笔）跑上 Linux 6.6 的移植项目。

**状态**：日常可用。显示/触控笔/音频/WiFi/实体按键/电池/休眠全套打通，配一套纯 Python 的
墨水屏 GUI（终端+键盘+拼音输入法）就能当日常机用。

> 本项目基于个人购买的设备，与作者雇主无关。不包含任何厂商固件、二进制或反编译产物。
>
> 开发全过程由 AI 完成：分析、逆向、移植、代码、文档。

## 现状

| 功能 | 状态 | 实现方式 |
|---|---|---|
| 10.3" 墨水屏显示 | ✅ | rockchip ebc + 波形文件（自行提取）+ 左切边补偿 |
| EMR 电磁笔 | ✅ | uart5 协议逆向 → uinput 指针 + 四角校准 |
| 声音（扬声器） | ✅ | RK817 codec（修复 of_node 绑定问题） |
| WiFi（brcmfmac43456） | ✅ | 固件入 initramfs 解决 probe 时机问题 |
| 实体按键 ×9 | ✅ | gpio-keys（翻页/音量/刷新/休眠） |
| 电池电量/充放电 | ✅ | rk817 fuel-gauge |
| 休眠/唤醒 | ✅ | + fp9931 PMIC 驱动解决唤醒白屏 |
| 墨水屏温度补偿 | ✅ | ebc temp_override |
| USB（Hub/键盘/U盘） | ✅ | DWC3 双角色 + TypeC |
| USB 千兆网卡 AX88179A | ✅ | ASIX 官方开源驱动(ax_usb_nic)，已内置内核 |
| 充电（TypeC 供电路径） | ✅ | 修复 PD 属性缺失导致的"插电只放电" |
| 墨水屏 GUI | ✅ | gui/：终端 + 键盘 + 拼音输入法 + 状态栏 |

## 仓库结构

```
kernel/    GPL-2.0-only   内核补丁系列 + 设备树 + fp9931驱动 + 配置片段
gui/       MIT            墨水屏GUI全家桶（终端/键盘/拼音/笔守护进程）
tools/     MIT            boot.img 打包、initramfs 修改、刷机流程
rootfs/    MIT            Ubuntu rootfs 构建脚本
docs/      CC-BY-4.0      过程记录(journey.md) + 坑清单(pitfalls.md)
```

## 快速上手

1. **内核**：按 `kernel/README.md` 打补丁编译（基于 PineNote 6.6.30 树）
2. **打包**：`tools/repack_n10_boot.py` 做 boot.img（把 WiFi 固件和 `ebc.wbf` 波形塞进 initramfs）
3. **刷机**：loader 模式 + rkdeveloptool（详见 `tools/README.md`，先备份原厂 boot）
4. **系统**：`rootfs/build_rootfs.sh` 生成 Ubuntu rootfs
5. **GUI**：`gui/README.md` 部署 n10gui + 电磁笔服务

## 那段"破案"过程

墨水屏左右切边、电磁笔7字节协议、唤醒白屏、WiFi固件时机，这些问题怎么定位怎么解决，
写在了 [docs/journey.md](docs/journey.md)；踩过的所有坑单列在 [docs/pitfalls.md](docs/pitfalls.md)。
版本历史在 [CHANGELOG.md](CHANGELOG.md)。

## 致谢

- [PineNote Linux 内核树](https://github.com/PineNote-Devs/linux) — rockchip ebc 驱动的基础
- Andreas Kemnade — fp9931 驱动作者（GPL-2.0-only）
- [rime luna-pinyin](https://github.com/rime/rime-luna-pinyin) / [CC-CEDICT](https://cc-cedict.org) / [jieba](https://github.com/fxsjy/jieba) — 拼音词库来源
- 神说要有光，于是有了光

## 许可

分层许可，见 [LICENSE](LICENSE)。
