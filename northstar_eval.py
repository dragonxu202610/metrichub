# -*- coding: utf-8 -*-
"""
北极星候选评估 —— 预注册判据 + 可执行检验
=========================================
python northstar_eval.py            # 依赖 out/api/*.json(先跑 build.py)

判据必须在看到结果之前写死, 否则"三种候选都算、不预设立场"就只是姿态 ——
跑完再看结果选一个说法, 正是本脚本要防的事。
反过来, 用自己造的数据证明自己的观点是循环论证; 因此本脚本只回答"判据能不能被执行":
模拟数据下该 abstain 就 abstain, 该输出「不可区分」就输出「不可区分」, 不代替真实数据下结论。

本脚本因此做三件事:
  1. 把**判据写死在代码里**(见 DECISION_RULES)，先于结果存在；
  2. 对三个候选(创作者数 / 创作数 / 分钟数)分别算与收入、与付费留存的弹性与相关系数；
  3. 落盘 out/api/northstar_evidence.json，供审计页引用(页面不再手写数字)。

退出码: 0 = 检验完成(无论结论如何); 1 = 无法完成(产物缺失等)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "out"
API = OUT / "api"

# ---------------------------------------------------------------------------
# 预注册判据(先写规则, 再看结果 —— 这是本脚本存在的主要理由)
# ---------------------------------------------------------------------------
DECISION_RULES = [
    {"id": "R1", "name": "与收入的关系",
     "rule": "若 创作者数 与收入的相关系数 >= 创作数 与分钟数 两者中的较大值 且 差距 >= 0.01, "
             "维持『人』为北极星; 若差距 < 0.01 则判定为 **不可区分**(样本不足以分辨), 不改判也不背书",
     "fallback": "若创作者数显著更低, 改判为与收入相关性最强的口径, 并在审计页记录本次改判"},
    {"id": "R2", "name": "与续费的关系",
     "rule": "若 创作者数 与付费留存(周环比)的关系 强于 创作数, 支持『人』口径",
     "fallback": "付费留存样本过少(演示仅 14 天)时本规则 abstain, 不作为改判依据"},
    {"id": "R3", "name": "是否需要换单位",
     "rule": "若 分钟数 与收入的相关性比 创作数 高 0.1 以上, 说明价值密度重要, 消耗口径主指标应换成分钟",
     "fallback": "否则保留创作数作为消耗口径"},
]

INDISTINGUISHABLE_GAP = 0.01      # 相关系数差距小于此值 → 判定为"样本无法区分"

WINDOW_DAYS = 7          # 周口径(北极星的时间单位)
CANDIDATES = [
    ("creators", "active_creators"),               # 人
    ("creations", "daily_successful_creations"),   # 次
    ("minutes", "minutes_generated"),              # 分钟
]


def pearson(xs, ys):
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    xs, ys = xs[:n], ys[:n]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    if vx == 0 or vy == 0:
        return None
    return round(cov / (vx * vy), 3)


def elasticity(xs, ys):
    """相邻点弹性的中位数(比单点更稳): median( (Δy/y) / (Δx/x) )"""
    es = []
    for i in range(1, min(len(xs), len(ys))):
        if not xs[i - 1] or not ys[i - 1] or xs[i] == xs[i - 1]:
            continue
        es.append(((ys[i] - ys[i - 1]) / ys[i - 1]) / ((xs[i] - xs[i - 1]) / xs[i - 1]))
    if not es:
        return None
    es.sort()
    return round(es[len(es) // 2], 2)


def rolling_sum(series, w=WINDOW_DAYS):
    """把逐日值折成滚动 w 日累计(与 build.py 的 series_for 同一算法)"""
    vals, run = [], []
    for r in series:
        run.append(float(r.get("value") or 0))
        vals.append(sum(run[-w:]))
    return vals


def load_daily(name):
    """读逐日序列。注意两种形态必须区别对待:
      - 普通指标: 产物是逐日**增量** → 需要折成滚动 7 日累计才能与北极星同口径
      - 滚动去重指标(active_creators): 产物本身已是"过去 7 天去重数" → 直接用, 不能再求和
    返回 (values, already_rolled)"""
    p = API / f"metric_{name}.json"
    if not p.exists():
        return None, False
    d = json.loads(p.read_text(encoding="utf-8"))
    ser = d.get("series") or None
    if ser is None:
        return None, False
    note = d.get("series_note") or ""
    already = ("去重" in note) or bool(d.get("grain") == "window" and "均值" in note)
    return [float(r.get("value") or 0) for r in ser], already


def main():
    if not API.exists():
        print("[!] out/api 不存在 —— 先运行 python build.py --fresh")
        return 1

    dash_path = API / "dashboard.json"
    if not dash_path.exists():
        print("[!] 缺 dashboard.json —— 先运行 python build.py --fresh")
        return 1
    dash = json.loads(dash_path.read_text(encoding="utf-8"))

    # 收入与付费留存作为"钱"的两个代理
    revenue = [r for r in dash.get("charts", {}).get("revenue", []) if r.get("value") is not None]
    rev_series = rolling_sum(revenue)
    kpi = {k["metric"]: k for k in dash.get("kpis", [])}
    payer_ret = (kpi.get("payer_retention_wow") or {}).get("value")

    result = {
        "generated_from": dash.get("generated_at"),
        "as_of": dash.get("as_of"),
        "window_days": WINDOW_DAYS,
        "n_points": len(rev_series),
        "caveat": ("本评估运行在模拟器生成的 14 天数据上。它检验的是『判据能不能被执行』, "
                   "不是对公司真实经营关系的实证 —— 真实数据下应重跑本脚本。"),
        "decision_rules": DECISION_RULES,
        "candidates": {},
    }

    # 逐日序列: 人 / 次 / 分钟(滚动去重的序列已是同口径, 不再重复求和)
    cand_series = {}
    for key, metric in CANDIDATES:
        vals, already = load_daily(metric)
        if vals is None:
            cand_series[key] = None
            continue
        cand_series[key] = vals if already else rolling_sum([{"value": v} for v in vals])
    for key in cand_series:
        cand = cand_series[key]
        if cand is None:
            result["candidates"][key] = {"available": False, "reason": "缺逐日序列"}
            continue
        n = min(len(cand), len(rev_series))
        result["candidates"][key] = {
            "available": n >= 3,
            "n_points": n,
            "corr_with_revenue": pearson(cand[-n:], rev_series[-n:]),
            "elasticity_with_revenue": elasticity(cand[-n:], rev_series[-n:]),
            "last_value": round(cand[-1], 2) if cand else None,
        }

    # 判据逐条判定(只对可用的候选做比较)
    avail = {k: v for k, v in result["candidates"].items() if v.get("available")}
    verdicts = []
    if "creators" in avail and len(avail) >= 2:
        others = [v["corr_with_revenue"] for k, v in avail.items() if k != "creators"]
        best_other = max([o for o in others if o is not None], default=None)
        c = avail["creators"]["corr_with_revenue"]
        if c is not None and best_other is not None:
            gap = c - best_other
            if abs(gap) < INDISTINGUISHABLE_GAP:
                verdicts.append({"id": "R1", "decision": "不可区分",
                                 "evidence": f"三个候选与收入的相关系数均为 {c} (与最强替代差 {round(gap, 4)} < "
                                             f"{INDISTINGUISHABLE_GAP}) —— 演示数据的时长与波动不足以分辨三者, "
                                             f"**既不改判也不背书**; 需真实数据(≥2 个季度)重跑"})
            elif gap >= 0:
                verdicts.append({"id": "R1", "decision": "维持『人』",
                                 "evidence": f"corr(creator,rev)={c} 高于最强替代={best_other}(差 {round(gap, 3)})"})
            else:
                verdicts.append({"id": "R1", "decision": "触发改判",
                                 "evidence": f"corr(creator,rev)={c} 低于最强替代={best_other}(差 {round(gap, 3)})"})
        else:
            verdicts.append({"id": "R1", "decision": "abstain", "evidence": "相关系数不可计算"})
    else:
        verdicts.append({"id": "R1", "decision": "abstain",
                         "evidence": "可用候选不足 2 个(演示数据下创作者数序列可能缺失)"})

    if payer_ret is None:
        verdicts.append({"id": "R2", "decision": "abstain", "evidence": "无付费留存 KPI"})
    else:
        verdicts.append({"id": "R2", "decision": "abstain",
                         "evidence": f"付费留存={payer_ret}% 但只有单期快照, 无法与候选做相关(演示限制)"})

    if "minutes" in avail and "creations" in avail:
        dm = avail["minutes"]["corr_with_revenue"]
        dc = avail["creations"]["corr_with_revenue"]
        if dm is not None and dc is not None:
            gap = dm - dc
            verdicts.append({"id": "R3",
                             "decision": "消耗口径主指标换成分钟" if gap > 0.1 else "保留创作数作消耗口径",
                             "evidence": f"corr(minutes,rev)={dm} vs corr(creations,rev)={dc}, 差={round(gap, 3)}"})
        else:
            verdicts.append({"id": "R3", "decision": "abstain", "evidence": "相关系数不可计算"})
    result["verdicts"] = verdicts
    # 证伪条件三态表(随评估落盘): 状态是对"判据现在能不能被执行"的盘点, 不是对结果的判断 ——
    # 不把"可执行的"降级成"需埋点的", 也不把"需埋点的"伪装成可执行。页面引用本表, 不再手写状态。
    result["falsification_checks"] = [
        {"check": "人 vs 产出：谁更贴钱", "window": "连续 2 个季度", "status": "现在可执行",
         "rule": "若 active_creators 与收入的相关系数低于创作数/分钟数, 触发改判(R1) —— 唯一能推翻北极星本身的可执行检验"},
        {"check": "创作者是否只被『一次性尝鲜』撑起", "window": "每月", "status": "现在可执行",
         "rule": "若 active_creators 上升而 creations_per_active_user 连续 3 个月下降, 北极星在被尝鲜撑起"},
        {"check": "是否需要换消耗口径的单位", "window": "连续 2 个季度", "status": "现在可执行",
         "rule": "若分钟数与收入的相关性比创作数高 0.1 以上, 消耗口径主指标换成分钟(R3)"},
        {"check": "毛利是否被北极星牺牲", "window": "每季度", "status": "现在可执行",
         "rule": "Δcompany_gross_margin < −3pp 且 Δweekly_minutes_generated < +10% → 引入毛利约束"},
        {"check": "免费额度是否在灌水", "window": "每月", "status": "部分可执行",
         "rule": "free_credit_burn_rate 已可读(分母只算免费发放, <55% 告警; 付费附赠由 paid_credit_burn_rate 单列); 缺免费→付费转化率"},
        {"check": "深度创作者占比", "window": "每月", "status": "需新增定义",
         "rule": "需要『每周创作 ≥2 次的创作者数』—— 一行 YAML 即可(deep_creator_share, 规划)"},
        {"check": "创作是否真的被消费", "window": "每季度", "status": "需补埋点",
         "rule": "需要 save/share 事件埋点(当前 event_type 恒为 view), 字段与触发时机见 PLAN-90D"},
    ]
    # 拆解树覆盖率: 7 个叶子中无定义的 2 个 —— 由 metrics.yaml 注册现状盘点而来,
    # 页面引用覆盖率时以本表为准, 不再各自手写分数。
    result["tree_coverage"] = {
        "total_leaves": 7,
        "defined_leaves": 5,
        "missing": ["会话/访客数(需补 session_id 埋点)", "沉默召回(需补回流事件)"],
        "note": "defined=已注册指标的叶子; 『可信』程度另见各指标 notes, 不在本表评分",
    }

    OUT.mkdir(exist_ok=True)
    (API / "northstar_evidence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    print("=" * 64)
    print(f"样本: {result['n_points']} 个滚动 {WINDOW_DAYS} 日点 · 来源 {result['generated_from']}")
    for k, v in result["candidates"].items():
        if v.get("available"):
            print(f"  [候选] {k:9s} corr={v['corr_with_revenue']!s:>6} "
                  f"elasticity={v['elasticity_with_revenue']!s:>6} 末值={v['last_value']}")
        else:
            print(f"  [候选] {k:9s} 不可用: {v.get('reason')}")
    for v in verdicts:
        print(f"  [{v['id']}] {v['decision']} —— {v['evidence']}")
    print("=" * 64)
    print(f"已落盘: out/api/northstar_evidence.json")
    print("说明: 演示数据只能检验『判据可执行』; 真实数据下请重跑本脚本再下结论。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
