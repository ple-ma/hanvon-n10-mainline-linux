# tools/ — 刷机与打包工具

| 文件 | 说明 |
|---|---|
| `repack_n10_boot.py` | 把 Image + dtb + initramfs 打包成 Android boot.img（含AB引导的 vendor_boot 拆分） |
| `patch_initramfs.py` | 解包/修改/重打 initramfs（例如把 WiFi 固件 `brcmfmac43456-sdio.*` 和墨水屏波形 `ebc.wbf` 塞进去） |

## 刷机三步（救砖同款流程）

1. 设备进 **loader 模式**：短接测试点或 BCB 写 `boot-recovery`（见 docs/journey.md）
2. `rkdeveloptool` / RKDevTool 连上
3. 刷 `boot` 分区（内核变了才需要）；只换 rootfs 时只刷 `rootfs`/用户分区

刷机有风险。备份原厂 boot 分区再动手；本仓库不提供任何厂商镜像。
刷机有风险。备份原厂 boot 分区再动手；本仓库不提供任何厂商镜像。
刷机有风险。备份原厂 boot 分区再动手；本仓库不提供任何厂商镜像。
