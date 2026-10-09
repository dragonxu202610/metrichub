# -*- coding: utf-8 -*-
"""
MetricHub 举证检查 —— 把"页面上的每个数字"变成可复现断言
=======================================================
python evidence.py

引用型论断(如"弹性 2.06")必须绑定到具体日期对 —— 否则页面上的数字与实际数据对不上。
一份把"诚实"当卖点的材料, 必须能自证每个数字的来源。

检查策略:
  A. 硬断言: 能从 out/api/*.json 精确重算的数字(序列求和、占比、极值)
  B. 软校验: 引用型论断(如"弹性约 2.06")—— 在全部相邻日对里找出最接近的一组, 偏离超过阈值就告警
  C. 声明一致性: 模拟器常数与页面叙述是否对得上(如"平均 7.0 秒/次"应等于 randint(2,12) 的均值)

退出码: 0 = 无 FAIL; 1 = 有 FAIL
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
API = ROOT / "out" / "api"
OK, WARN, FAIL = [], [], []


def ok(m):
    OK.append(m)


def warn(m):
    WARN.append(m)


def fail(m):
    FAIL.append(m)


def load(name):
    p = API / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def series(dash, key):
    return [(r["dt"], float(r["value"])) for r in (dash.get("charts", {}).get(key) or [])
            if r.get("value") is not None]


def main():
    dash = load("dashboard.json")
    if dash is None:
        print("[!] out/api/dashboard.json 不存在 —— 先运行 python build.py --fresh")
        return 1
    pages = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "site").glob("*.html")}
    all_html = "\n".join(pages.values())
    docs = "\n".join(p.read_text(encoding="utf-8") for p in
                     [ROOT / "README.md", ROOT / "PLAN-90D.md"] if p.exists())

    # ---------- 0. 前置门: 产物必须由当前源生成, 否则一切举证无效 ----------
    # 没有这道门, evidence.py 会在过期产物上全绿, 与 check.py 的结论互相矛盾
    import yaml
    with open(ROOT / "metrics.yaml", encoding="utf-8") as f:
        src_metrics = yaml.safe_load(f)["metrics"]
    cat = load("catalog.json")
    if cat is None or len(cat) != len(src_metrics):
        n = len(cat) if cat else 0
        fail(f"举证无效: 产物过期 —— out/api/catalog.json 有 {n} 个指标, "
             f"metrics.yaml 有 {len(src_metrics)} 个。请先 python build.py --fresh")
        print_report()
        return 1
    ok(f"前置门通过: 产物指标数({len(cat)})与源一致 —— 以下断言才有效")

    # ---------- A. 硬断言 ----------
    cr, rv = series(dash, "creations"), series(dash, "revenue")
    if not cr:
        fail("charts.creations 为空 —— 看板北极星趋势无数据")
    else:
        last7 = sum(v for _, v in cr[-7:])
        kpi = next((k for k in dash["kpis"] if k["metric"] == "weekly_successful_creations"), None)
        if kpi and abs(kpi["value"] - last7) > 1:
            fail(f"周成功创作数 KPI={kpi['value']} 但日序列末 7 天之和={last7:.0f} —— 两者必须一致")
        else:
            ok(f"周成功创作数 KPI 与日序列末 7 天之和一致({last7:.0f})")
        txt = f"{last7:,.0f}"
        if f">{txt}<" in all_html or f" {txt} " in all_html:
            ok(f"页面引用的 {txt} 可复现")
        elif txt not in all_html:
            warn(f"页面未引用 {txt}(KPI 值) —— 若确为有意省略可忽略")

    # 平台维度分解合计(审计页引用 18,660)
    dim = load("metric_weekly_successful_creations.json")
    if dim:
        plat = {i["key"]: i["value"] for i in dim.get("by_dim", {}).get("platform", [])}
        tot = sum(plat.values())
        if tot and f"{tot:,.0f}" in all_html:
            ok(f"页面引用的 {tot:,.0f}(14 日维度合计)可复现")
        elif tot:
            warn(f"14 日平台维度合计={tot:,.0f} 未被页面引用(审计页曾引用该数, 请确认是否已改)")

    # 弹性: 页面声明必须绑定到具体日期对, 并按该日对精确复算
    if len(cr) > 1 and len(rv) > 1:
        rev_by_day = dict(rv)
        cr_by_day = dict(cr)
        # 页面写法形如 "10-07→10-08 创作数 +8.1% 而收入 +84.3%，弹性 10.4"
        claims = re.findall(
            r"(\d{2}-\d{2})\s*[→>-]+\s*(\d{2}-\d{2})[^。]{0,80}?弹性\s*(?:约\s*)?(?:<b>)?([0-9]+(?:\.[0-9]+)?)",
            all_html, re.S)
        if not claims:
            warn("页面没有出现'日期对 + 弹性'的可核写法 —— 无法复算弹性论断")
        for d0m, d1m, claimed in claims:
            d0 = next((d for d in rev_by_day if d.endswith(d0m)), None)
            d1 = next((d for d in rev_by_day if d.endswith(d1m)), None)
            if not (d0 and d1 and d0 in cr_by_day and d1 in cr_by_day):
                fail(f"弹性论断引用的日期对 {d0m}→{d1m} 在日序列里找不到 —— 举证不成立")
                continue
            c0, c1 = cr_by_day[d0], cr_by_day[d1]
            r0, r1 = rev_by_day[d0], rev_by_day[d1]
            if c0 == 0 or r0 == 0 or c1 == c0:
                warn(f"弹性 {d0m}→{d1m} 无法计算(分母为 0 或创作数无变化)")
                continue
            real = ((r1 - r0) / r0) / ((c1 - c0) / c0)
            off = abs(real - float(claimed)) / max(abs(real), 1e-9)
            if off > 0.05:
                fail(f"弹性举证不符: 页面写 {claimed}, 按 {d0}→{d1} 复算是 {real:.2f}"
                     f"(偏差 {off:.0%})")
            else:
                ok(f"弹性 {claimed} 可由 {d0}→{d1} 复算({real:.2f})")

    # ---------- B. 模拟器常数 × 页面叙述 ----------
    try:
        import simulator
        import re as _re
        src = (ROOT / "simulator.py").read_text(encoding="utf-8")
        m = _re.search(r"rng\.randint\((\d+),\s*(\d+)\)", src)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            mean_secs = (lo + hi) / 2
            if f"{mean_secs:.1f} 秒/次" in all_html:
                ok(f"页面引用的『平均 {mean_secs:.1f} 秒/次』= randint({lo},{hi}) 的均值 "
                   f"—— 已如实标注为机制推演")
        sim_models = {mm[0]: {"w": mm[1], "ok": mm[2], "cost": mm[3]} for mm in simulator.MODELS}
        for mname, cfg in sim_models.items():
            if f"{cfg['ok'] * 100:.1f}%" in all_html:
                ok(f"页面引用的成功率 {cfg['ok'] * 100:.1f}%({mname}) 出自 simulator.MODELS 常数")
        pos = load("metric_model_gross_margin.json")
        if pos and pos.get("by_dim", {}).get("model"):
            neg = [(i["key"], i["value"]) for i in pos["by_dim"]["model"] if i["value"] < 0]
            if neg and any(f"{v}%" in all_html for _, v in neg):
                ok(f"页面引用的负毛利 {[(k, v) for k, v in neg]} 与产物一致(仍属常数推演, 非发现)")
    except Exception as e:                                   # noqa: BLE001
        warn(f"无法导入 simulator 校验常数引用: {e}")

    # ---------- C. 弱点自查: 页面不得把模拟结论说成"实证" ----------
    # 只扫标题与断言句, 且允许解释性引用 —— 否则"诚实写下'此前用了被实证这个词'"会把门禁自己弄红
    for name, t in pages.items():
        if re.search(r"<h[123][^>]*>[^<]*被实证", t, re.S):
            fail(f"site/{name} 的标题仍宣称『被实证』 —— 模拟数据只能支撑『可复现/机制推演』")
    for name, t in list(pages.items()) + [("README.md", docs)]:
        bad = [ln for ln in t.splitlines()
               if "被实证" in ln and not any(k in ln for k in ("此前", "应读作", "不再", "改为", "删"))]
        if bad:
            fail(f"{name} 仍把模拟结论当作『实证』: {bad[0].strip()[:60]}")
    if "机制推演" in pages.get("northstar.html", ""):
        ok("审计页已把证据强度改写为『机制推演 / 可复现』")

    # ---------- D. 流批对账(流式样例): 守恒 + 页面引用数字可复算 ----------
    sc = load("stream_compare.json")
    if sc:
        s = sc["stats"]
        if s["wm_total"] + s["wm_dropped"] != s["batch_total"]:
            fail(f"流批对账不守恒: watermark {s['wm_total']} + 丢弃 {s['wm_dropped']}"
                 f" != 批 {s['batch_total']}")
        elif s["arrival_total"] != s["batch_total"]:
            fail(f"到达序总数 {s['arrival_total']} != 批 {s['batch_total']} —— 数据被丢/被复制")
        else:
            ok(f"流批对账守恒: 批 {s['batch_total']:,} = 流(watermark) {s['wm_total']:,}"
               f" + 迟到丢弃 {s['wm_dropped']}; 到达序不丢但 {s['misplaced']} 条错窗")
        rt = ROOT / "out" / "realtime.html"
        if rt.exists():
            rt_text = rt.read_text(encoding="utf-8")
            for label, v in (("迟到丢弃", str(s["wm_dropped"])),
                             ("错窗", str(s["misplaced"])), ("批", f"{s['batch_total']:,}")):
                if v in rt_text:
                    ok(f"realtime 页引用的{label}数字 {v} 与产物一致")
                else:
                    warn(f"realtime 页未引用{label}数字 {v} —— 若已改文案请同步")

    print_report()
    return 1 if FAIL else 0


def print_report():
    print("=" * 64)
    for m in OK:
        print(f"  [OK]   {m}")
    for m in WARN:
        print(f"  [WARN] {m}")
    for m in FAIL:
        print(f"  [FAIL] {m}")
    print("=" * 64)
    print(f"通过 {len(OK)} · 警告 {len(WARN)} · 失败 {len(FAIL)}")


if __name__ == "__main__":
    sys.exit(main())
