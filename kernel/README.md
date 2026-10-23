# kernel/ — 内核补丁与板级文件

基线：**Linux 6.6.30**（基于 [PineNote 6.6.30 内核树](https://github.com/PineNote-Devs/linux) 的分支，该树自带 rockchip ebc 墨水屏驱动雏形）

## 内容

| 文件 | 说明 |
|---|---|
| `patches/0001~0005` | 按序应用的补丁系列 |
| `dts/rk3566-hanvon-n10.dts` | 板级设备树（0005里含同样的内容，此目录便于直接查看） |
| `drivers/fp9931.c` | 墨水屏PMIC驱动（0004里含同样的内容） |
| `config-fragment` | 需打开的内核选项 |

## 构建

```bash
# 在内核树根目录
git am /path/to/kernel/patches/*.patch
cat /path/to/kernel/config-fragment >> arch/arm64/configs/<your-defconfig>
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- <your-defconfig>
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc)
```

产物：`arch/arm64/boot/Image` + `arch/arm64/boot/dts/rockchip/rk3566-hanvon-n10.dtb`

## 打包 boot.img

见 `../tools/README.md`（repack_n10_boot.py）。

## 说明

- USB 千兆网卡用的是 ASIX 官方开源驱动（`drivers/ax_usb_nic/`，GPL-2.0），不是内核自带的
  ax88179_178a——那个到 6.6 甚至主线 master 都不认 AX88179A。已按内置(=y)编入 boot 镜像。
