#!/bin/bash
# N10 Ubuntu rootfs 构建脚本 (在Kali上运行)
set -e
cd /root
IMG=/root/ubuntu-n10.img
MNT=/tmp/n10root

echo "=== 1. 创建2GB ext4镜像 ==="
rm -rf $MNT && mkdir -p $MNT
dd if=/dev/zero of=$IMG bs=1M count=2048 status=none
mkfs.ext4 -q -L ubuntu-n10 $IMG
mount -o loop $IMG $MNT

echo "=== 2. 解包ubuntu-base ==="
tar xzf ubuntu-base.tar.gz -C $MNT

echo "=== 3. 准备chroot ==="
cp /usr/bin/qemu-aarch64 $MNT/usr/bin/
cp /etc/resolv.conf $MNT/etc/
mount -t proc proc $MNT/proc
mount -t sysfs sys $MNT/sys
mount -o bind /dev $MNT/dev

echo "=== 4. chroot内配置 ==="
chroot $MNT /usr/bin/qemu-aarch64 /bin/bash -c '
set -e
# 清华源(arm64 ports)
cat > /etc/apt/sources.list <<EOF
deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ noble main restricted universe multiverse
deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ noble-updates main restricted universe multiverse
deb http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/ noble-security main restricted universe multiverse
EOF
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends openssh-server wpasupplicant linux-firmware vim-tiny sudo net-tools 2>&1 | tail -2

# root密码: n10
echo "root:${N10_ROOT_PW:-changeme}" | chpasswd   # 默认密码占位, 构建前可 export N10_ROOT_PW=...

# hostname
echo "n10" > /etc/hostname
cat > /etc/hosts <<EOF
127.0.0.1 localhost
127.0.1.1 n10
EOF

# ssh允许root登录(调试期)
sed -i "s/#PermitRootLogin.*/PermitRootLogin yes/" /etc/ssh/sshd_config

# 串口console getty (ttyS2, 保持内核设置的1500000波特率)
systemctl enable serial-getty@ttyS2.service

# 时区
ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime

# systemd-networkd: wlan0 DHCP
mkdir -p /etc/systemd/network
cat > /etc/systemd/network/20-wlan0.network <<EOF
[Match]
Name=wlan0
[Network]
DHCP=yes
EOF
systemctl enable systemd-networkd

# wpa_supplicant 模板(用户填自己的WiFi)
mkdir -p /etc/wpa_supplicant
cat > /etc/wpa_supplicant/wpa_supplicant.conf <<EOF
ctrl_interface=/run/wpa_supplicant
update_config=1
country=CN

network={
    ssid="你的WiFi名字"
    psk="你的WiFi密码"
}
EOF
cat > /etc/systemd/system/wpa_supplicant@wlan0.service <<EOF
[Unit]
Description=WPA supplicant for wlan0
[Service]
ExecStart=/sbin/wpa_supplicant -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf
Restart=always
[Install]
WantedBy=multi-user.target
EOF
# 先不enable, 等用户填好WiFi再开: systemctl enable wpa_supplicant@wlan0

# 首次开机提示
cat > /etc/motd <<EOF

  Hanvon N10 - Ubuntu 24.04 (mainline kernel 6.6.30)

  WiFi配置: 编辑 /etc/wpa_supplicant/wpa_supplicant.conf 填SSID密码
            然后 systemctl enable --now wpa_supplicant@wlan0
  串口: ttyS2 @ 1500000
EOF
'
echo "=== 5. 收尾 ==="
umount $MNT/proc $MNT/sys $MNT/dev
rm $MNT/usr/bin/qemu-aarch64
umount $MNT
ls -l $IMG
echo "=== rootfs构建完成 ==="
