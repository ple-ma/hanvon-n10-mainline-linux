#!/usr/bin/env python3
"""N10 boot镜像重打包（Windows本机Python即可,不用Kali）。
用法: python repack_n10_boot.py <模板boot.img> <kernel Image> <initramfs.gz> <dtb> <输出.img> [cmdline]
关键: id字段在偏移576(boot v2头: cmdline 64~576, id 576~608), 内容=sha1(kernel+ramdisk+second+recovery_dtbo+dtb及各size的LE32)
"""
import struct, hashlib, sys

tpl_path, kpath, rpath, dpath, out_path = sys.argv[1:6]
cmdline = sys.argv[6].encode() + b'\x00' if len(sys.argv) > 6 else None
page = 2048

hdr = bytearray(open(tpl_path, 'rb').read()[:page])
kernel = open(kpath, 'rb').read()
ramdisk = open(rpath, 'rb').read()
dtb = open(dpath, 'rb').read()

struct.pack_into('<I', hdr, 8, len(kernel))
struct.pack_into('<I', hdr, 16, len(ramdisk))
struct.pack_into('<I', hdr, 24, 0)            # second
struct.pack_into('<I', hdr, 1632, 0)          # recovery_dtbo_size
struct.pack_into('<Q', hdr, 1636, 0)
struct.pack_into('<I', hdr, 1648, len(dtb))   # dtb_size
if cmdline:
    hdr[64:64+512] = b'\x00'*512
    hdr[64:64+len(cmdline)] = cmdline

h = hashlib.sha1()
for data in (kernel, ramdisk, b'', b'', dtb):
    h.update(data); h.update(struct.pack('<I', len(data)))
hdr[576:576+32] = h.digest() + b'\x00'*12    # id@576, 别写到72(那是cmdline)

def rnd(n): return -(-n//page)*page
out = bytes(hdr) + kernel + b'\x00'*(rnd(len(kernel))-len(kernel))
out += ramdisk + b'\x00'*(rnd(len(ramdisk))-len(ramdisk))
out += dtb + b'\x00'*(rnd(len(dtb))-len(dtb))
open(out_path, 'wb').write(out)
print(f'{out_path}: {len(out)} bytes, id={h.hexdigest()}')
