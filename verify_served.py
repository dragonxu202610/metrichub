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
    ("assets/nav.js", "v1/index.html", "新旧版切换按钮在共享导航里"),
    ("index.html", "数据治理", "总览含治理贯穿叙事"),
    ("domains.html", "总线矩阵", "数据域页核心组件"),
    ("domains.html", "烟囱", "口径冲突叙事"),
    ("domains.html", "完整性", "质量六维映射表"),
    ("semantic.html", "构建流程", "语义层构建流程"),
    ("semantic.html", "dbt-docs/index.html", "血缘图入口"),
    ("metrics.html", "不可区分", "实测结论: 三候选不可区分"),
    ("metrics.html", "0.997", "实测相关系数上页"),
    ("metrics.html", "northstar_evidence.json", "指向举证产物"),
    ("metrics.html", "机制推演", "证据强度标注"),
    ("services.html", "七道门禁", "门禁↔生产监控对应表"),
    ("apps.html", "query_metric", "审计埋点论述"),
    ("dashboard.html", "chCreators", "北极星趋势面板存在"),
    ("dashboard.html", "周活跃创作者", "渠道表新增北极星列"),
    ("dashboard.html", "不可用于预算决策", "线性归因告警"),
    ("layer.html", "series_note", "目录页渲染序列说明"),
    ("layer.html", "dbt-docs/index.html", "目录页血缘图入口"),
    ("ai.html", "这不是一次现场 LLM 推理", "AI 页诚实标注"),
    ("ai.html", "AI 编程提效", "AI 开发章节存在"),
    ("sources.html", "不含任何内部数据", "信源页诚实声明"),
    ("sources.html", "finance.sina.com.cn", "信源页晚点出处可点"),
    ("realtime.html", "演示级", "流式页演示级标注"),
    ("realtime.html", "forBoundedOutOfOrderness", "Flink 原语映射表"),
    ("realtime.html", "stream_compare.json", "流批对账数据源"),
    ("v1/index.html", "v1back", "旧版归档含回切按钮"),
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
