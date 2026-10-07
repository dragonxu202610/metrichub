# -*- coding: utf-8 -*-
"""
MetricHub 产物新鲜度检查
=======================
python compare_out.py

用途: `site/` 是源, `out/` 是 build 产物(Pages 实际发布的目录)。
改了 site/ 却没重跑 build.py, 线上就是旧页面 —— 这类静默不同步最伤 demo 可信度。
本脚本逐文件比对 site/ 与 out/, 列出需要重新 build 的文件。

退出码: 0 = 完全同步; 1 = 存在不同步(需要 python build.py --fresh)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SITE, OUT = ROOT / "site", ROOT / "out"
# 构建期渲染的占位符: 比对前先"预渲染"一遍源文件, 否则 out/ 永远与 site/ 不同
TOKENS = ("__METRIC_COUNT__",)


def render(text, values):
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def token_values():
    """占位符的"真值"必须来自源(metrics.yaml), 不能取自产物 ——
    否则加了指标但没重跑 build 时, 比对会自证同步, 正是要防的漂移。"""
    n = "?"
    try:
        import yaml
        with open(ROOT / "metrics.yaml", encoding="utf-8") as f:
            n = str(len(yaml.safe_load(f)["metrics"]))
    except Exception as e:                                   # noqa: BLE001
        print(f"[!] 无法读取 metrics.yaml 的指标数({e}), 占位符比对降级")
    return {t: (n if t == "__METRIC_COUNT__" else "") for t in TOKENS}


def main():
    if not OUT.exists():
        print("[!] out/ 不存在 —— 先运行 python build.py --fresh")
        return 1
    values = token_values()

    stale, missing = [], []
    for src in sorted(SITE.rglob("*")):
        if not src.is_file():
            continue
        dst = OUT / src.relative_to(SITE)
        if not dst.exists():
            missing.append(src.relative_to(SITE))
            continue
        # 两侧都按文本(通用换行)读取: build 在 Windows 上会写出 CRLF, 逐字节比会永远判为过期
        want = render(src.read_text(encoding="utf-8"), values)
        if want != dst.read_text(encoding="utf-8"):
            stale.append(src.relative_to(SITE))

    print(f"[i] site/ {len(list(SITE.rglob('*')))} 项 vs out/ {len(list(OUT.rglob('*')))} 项"
          f"（比对时已按实际指标数预渲染占位符）")
    for p in stale:
        print(f"  [STALE]   site/{p}  ≠  out/{p}")
    for p in missing:
        print(f"  [MISSING] out/{p}")
    if not stale and not missing:
        print("  [OK]      out/ 与 site/ 完全同步")
        return 0
    print(f"\n结论: {len(stale)} 个文件已过期, {len(missing)} 个缺失。"
          f"\n执行: python build.py --fresh   # 会重建 data/ 与 out/, 再 python check.py --data 复核口径")
    return 1


if __name__ == "__main__":
    sys.exit(main())
