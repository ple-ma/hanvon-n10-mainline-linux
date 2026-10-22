# rootfs/ — Ubuntu rootfs 构建

`build_rootfs.sh`：debootstrap 一个 arm64 Ubuntu（含 systemd、wpa_supplicant、
python3-pil、fonts-wqy-zenhei 等 N10 GUI 运行所需），输出可直接 dd 的镜像。

```bash
sudo -S -p '' ./build_rootfs.sh
# 默认root密码为 changeme, 可先 export N10_ROOT_PW=自定义
```

打好的镜像用 tools/repack 的思路写入用户分区，或做成第二个分区随 boot.img 一起刷。
