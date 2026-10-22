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

## 已知未完

- USB千兆网卡 AX88179A：主线上游驱动在新内核，6.6需backport（`CONFIG_USB_NET_AX8817X`），编到probe阶段后搁置
