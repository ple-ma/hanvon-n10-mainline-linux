#!/usr/bin/env python3
"""重建拼音输入法字库: jieba词频排序 + 繁体过滤(zhconv) + 合并旧库"""
import json, re, sys

from pypinyin import pinyin, Style
from zhconv import convert

CJK = re.compile(r"^[\u4e00-\u9fff]+$")

def pykey(word):
    try:
        return "".join(x[0] for x in pinyin(word, style=Style.NORMAL, heteronym=False))
    except Exception:
        return ""

def is_simp(word):
    return convert(word, "zh-cn") == word

# 1) jieba: word freq
jb = []
with open(r"C:\Users\Pengle\AppData\Local\Temp\jieba_dict.txt", encoding="utf-8") as f:
    for line in f:
        p = line.split()
        if len(p) < 2:
            continue
        word = p[0]
        if not CJK.match(word):
            continue
        if not is_simp(word):
            continue
        try:
            freq = int(p[1])
        except ValueError:
            continue
        jb.append((word, freq))
jb.sort(key=lambda x: -x[1])
print("jieba usable:", len(jb), flush=True)

out = {}
for i, (word, freq) in enumerate(jb):
    k = pykey(word)
    if not re.fullmatch(r"[a-z]+", k):
        continue
    lst = out.setdefault(k, [])
    if word not in lst:
        lst.append(word)
print("after jieba:", sum(len(v) for v in out.values()), flush=True)

# 2) 旧库(过滤繁体后)补尾
old = json.load(open(r"C:\Users\Pengle\AppData\Local\Temp\pinyin_dict.json", encoding="utf-8"))
added = 0
for k, words in old.items():
    if not re.fullmatch(r"[a-z]+", k):
        continue
    lst = out.setdefault(k, [])
    for w in words:
        if len(w) > 8 or not all(CJK.match(c) for c in w):
            continue
        if not is_simp(w):
            continue
        if w not in lst:
            lst.append(w)
            added += 1
print("old merged:", added, flush=True)

out = {k: v[:20] for k, v in out.items()}
p = r"C:\Users\Pengle\AppData\Local\Temp\pinyin_dict.json"
with open(p, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
import os
print("saved", len(out), "keys,", os.path.getsize(p), "bytes")
for k in ("nihao", "wo", "shuru", "ceshi", "zhongguo", "xian", "shi"):
    print(k, "->", out.get(k, [])[:10])
