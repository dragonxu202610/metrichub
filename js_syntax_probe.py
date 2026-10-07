# -*- coding: utf-8 -*-
"""
轻量 JS/HTML 语法哨兵 —— 无 Node 也能查出自伤的模板字面量/括号错误
=================================================================
python js_syntax_probe.py            # 扫描 site/ 下全部 *.html 的内联 <script>

为什么需要它: 看板脚本大量使用模板字符串拼 HTML(`<div ...>`),
标签里若出现未转义的 </script> 会提前截断脚本; 反引号/括号不配平则会整页白屏。
这两种错误在浏览器里表现为"页面看起来没坏但没有数据", 极难定位 —— 本脚本把它们变成断言。

检查项:
  1. <script> 标签配对(缺失会把 JS 当文本渲染)
  2. 模板字面量里出现裸 </script>(会截断脚本块)
  3. 每个 <script> 体内 (), [], {} 配对平衡
  4. 反引号数量为偶数(未闭合模板字面量)
退出码: 0 = 通过; 1 = 发现问题
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent


def strip_noncode(js):
    """去掉字符串/模板字面量/注释, 只留可计数的代码骨架"""
    out, i, n = [], 0, len(js)
    pairs = {"'": "'", '"': '"', "`": "`"}
    while i < n:
        c = js[i]
        if c == "/" and i + 1 < n and js[i + 1] == "/":
            i = js.find("\n", i)
            if i == -1:
                break
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "*":
            j = js.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c in pairs:
            q = pairs[c]
            i += 1
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == q:
                    i += 1
                    break
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def check_file(p):
    html = p.read_text(encoding="utf-8")
    problems = []
    opens = len(re.findall(r"<script\b[^>]*>", html, re.I))
    closes = len(re.findall(r"</script\s*>", html, re.I))
    if opens != closes:
        problems.append(f"<script> 开闭不配对: {opens} 开 / {closes} 闭")
    for i, body in enumerate(re.findall(r"<script\b[^>]*>(.*?)</script\s*>", html, re.S | re.I), 1):
        if "</script" in body:
            problems.append(f"第 {i} 个脚本体内出现裸 </script>")
        code = strip_noncode(body)
        for open_c, close_c in [("(", ")"), ("[", "]"), ("{", "}")]:
            a, b = code.count(open_c), code.count(close_c)
            if a != b:
                problems.append(f"第 {i} 个脚本体 {open_c}{close_c} 不配平: {a} vs {b}")
        if body.count("`") % 2:
            problems.append(f"第 {i} 个脚本体反引号数量为奇数(模板字面量未闭合)")
    return problems


def main():
    bad = 0
    for p in sorted((ROOT / "site").glob("*.html")):
        problems = check_file(p)
        if problems:
            bad += 1
            print(f"[FAIL] site/{p.name}")
            for x in problems:
                print(f"        - {x}")
        else:
            print(f"[OK]   site/{p.name}")
    print("-" * 56)
    print("全部通过" if not bad else f"{bad} 个文件有问题")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
