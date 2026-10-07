# -*- coding: utf-8 -*-
"""端到端页面断言: 检查 out/ 实际发布的内容里关键事实是否渲染正确。
用法:
  python verify_served.py                 # 默认从本地 HTTP 服务(8898)抓取
  python verify_served.py --dir           # 直接读 out/ 目录(CI 用, 不需要起服务)
"""
import json
import sys
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8898"
OUT = Path(__file__).parent / "out"
USE_DIR = "--dir" in sys.argv
CHECKS = [
    # (路径, 必须出现的字符串, 说明[, 期望存在])
    ("index.html", "个业务指标", "首页指标数文案"),
    ("index.html", "__METRIC_COUNT__", "占位符不得残留", False),
    ("index.html", "北极星审计", "首页入口含北极星审计"),
    ("northstar.html", "不可区分", "实测结论: 三候选不可区分"),
    ("northstar.html", "0.997", "实测相关系数上页"),
    ("northstar.html", "out/api/northstar_evidence.json", "指向举证产物"),
    ("northstar.html", "七道门禁全绿", "交付验证记录"),
    ("dashboard.html", "chCreators", "北极星趋势面板存在"),
    ("dashboard.html", "周活跃创作者", "渠道表新增北极星列"),
    ("dashboard.html", "不可用于预算决策", "线性归因告警"),
    ("layer.html", "series_note", "语义层页渲染序列说明"),
    ("ai.html", "这不是一次现场 LLM 推理", "AI 页诚实标注"),
]


def fetch(path):
    if USE_DIR:
        return (OUT / path).read_text(encoding="utf-8")
    return urllib.request.urlopen(f"{BASE}/{path}", timeout=10).read().decode("utf-8")


def main():
    ok, fail = [], []
    for item in CHECKS:
        path, needle, desc = item[0], item[1], item[2]
        want = item[3] if len(item) > 3 else True
        try:
            html = fetch(path)
        except Exception as e:                                # noqa: BLE001
            fail.append(f"{path}: 读取失败 {e}")
            continue
        has = needle in html
        if has == want:
            ok.append(f"{path}: {desc} {'✓' if want else '（确认不存在）'}")
        else:
            fail.append(f"{path}: {desc} —— 期望{'出现' if want else '不出现'} {needle!r}")

    # 数据契约: dashboard.json 的北极星 KPI 必须是 active_creators
    try:
        dash = json.loads(fetch("api/dashboard.json"))
        star = [k for k in dash["kpis"] if k.get("role") == "北极星"]
        if len(star) == 1 and star[0]["metric"] == "active_creators":
            ok.append(f"dashboard.json: 北极星唯一且为 active_creators = {star[0]['value']}")
        else:
            fail.append(f"dashboard.json: 北极星标注异常 {star}")
        if dash["charts"].get("creators_7d"):
            ok.append(f"dashboard.json: creators_7d 有 {len(dash['charts']['creators_7d'])} 个点")
        else:
            fail.append("dashboard.json: 缺 creators_7d 趋势")
    except Exception as e:                                    # noqa: BLE001
        fail.append(f"dashboard.json 校验失败: {e}")

    print("=" * 60)
    for m in ok:
        print(f"  [OK]   {m}")
    for m in fail:
        print(f"  [FAIL] {m}")
    print("=" * 60)
    print(f"通过 {len(ok)} · 失败 {len(fail)}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
