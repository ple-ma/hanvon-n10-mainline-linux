#!/usr/bin/env python3
"""Windows本机改initramfs（不开Kali）：解gz+newc cpio, 对指定文件做文本替换, 重打。
用法: python patch_initramfs.py <in.gz> <out.gz> <cpio内路径> <旧字符串> <新字符串>
注意: 重写时rdev字段清零——含设备节点的cpio别用（本项目的initramfs只有目录和普通文件）。
"""
import gzip, io, sys

inp, outp, target, olds, news = sys.argv[1:6]
data = gzip.open(inp, 'rb').read()
entries = {}
i = 0
while True:
    hdr = data[i:i+110]
    assert hdr[:6] in (b'070701', b'070702')
    namesize = int(hdr[94:102], 16); filesize = int(hdr[54:62], 16); mode = int(hdr[14:22], 16)
    name = data[i+110:i+110+namesize-1].decode()
    i += 110 + namesize; i = (i+3)&~3
    entries[name] = (mode, data[i:i+filesize]); i += filesize; i = (i+3)&~3
    if name == 'TRAILER!!!': break

mode, content = entries[target]
text = content.decode()
assert olds in text, f'{olds!r} not in {target}'
entries[target] = (mode, text.replace(olds, news, 1).encode())

out = io.BytesIO(); ino = 1
for name, (mode, content) in entries.items():
    nb = name.encode() + b'\x00'
    out.write(f'070701{ino:08x}{mode:08x}{0:08x}{0:08x}{1:08x}{0:08x}{len(content):08x}{0:08x}{0:08x}{0:08x}{0:08x}{len(nb):08x}{0:08x}'.encode())
    out.write(nb); out.write(b'\x00' * ((4 - out.tell() % 4) % 4))
    out.write(content); out.write(b'\x00' * ((4 - out.tell() % 4) % 4))
    ino += 1
nb = b'TRAILER!!!\x00'
out.write(f'070701{"0"*8}{"0"*8}{"0"*8}{"0"*8}{1:08x}{"0"*8}{"0"*8}{"0"*8}{"0"*8}{"0"*8}{len(nb):08x}{"0"*8}'.encode())
out.write(nb); out.write(b'\x00' * ((4 - out.tell() % 4) % 4))
gzip.open(outp, 'wb', compresslevel=9, mtime=0).write(out.getvalue())
print(f'{outp}: patched {target}')
