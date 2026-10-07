# -*- coding: utf-8 -*-
"""
MetricHub 数据模拟器(简化版)
生成 14 天「AI 视频平台」业务数据(参考真实形态: SEO/红人渠道、积分订阅、多模型).
输出 data/*.jsonl —— 只做事实记录, 不做任何加工(加工是 build.py 的 ELT 职责).
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent / "data"
DAYS = 14
SEED = 20261008
# 演示窗口锚定到固定日期, 不用 date.today()。
# 为什么: 页面上的日期与数字是**随源码一起提交**的, 数据必须能在任何机器、任何时区、任何一天复现 ——
#   · GitHub runner 用 UTC, 与本机(UTC+8)差一天 → 窗口整体前移, 页面里 "10-07→10-08" 这类日期对
#     在新数据里根本不存在, evidence.py 的举证门禁直接失败(CI 首跑就是这么挂的);
#   · 每日 cron 重放会让已发布的页面数字与产物不再一致, 门禁必然变红。
# 变的应该是"你看它的那一天", 不是数据本身。
ANCHOR = date(2026, 10, 8)

# (渠道, 类型, 注册占比)
CHANNELS = [("google-organic", "seo", .28), ("bing-organic", "seo", .06), ("reddit-organic", "seo", .05),
            ("influencer-tiktok", "influencer", .14), ("influencer-youtube", "influencer", .09),
            ("google-ads", "paid", .07), ("facebook-ads", "paid", .04), ("affiliate", "affiliate", .15),
            ("direct", "direct", .12)]
COUNTRIES = [("US", .42), ("BR", .07), ("GB", .08), ("DE", .05), ("JP", .05), ("SEA", .12), ("OTHER", .21)]
PLATFORMS = [("web", .62), ("app", .38)]
# (模型, 选择权重, 成功率, API成本$/秒·公开定价粗略估算) —— Veo 3.1 质量最好但最贵(负毛利故事点)
MODELS = [("PixVerse V5", .14, .86, .006), ("Wan 2.5", .10, .87, .009),
          ("Vidu Q2", .14, .89, .013), ("Hailuo 02", .18, .90, .017),
          ("Kling 2.5", .20, .92, .022), ("Runway Gen-4", .12, .93, .025),
          ("Sora 2", .07, .95, .030), ("Veo 3.1", .05, .96, .048)]
PAGES = [("generator", .30), ("home", .18), ("effects", .16), ("community", .12), ("pricing", .06), ("dashboard", .18)]
PLANS = {"lite": (15, 300), "pro": (29, 800)}


def _w(rng, pairs):
    """pairs: [(value, weight), ...] → value"""
    r, acc = rng.random(), 0.0
    for v, w in pairs:
        acc += w
        if r <= acc:
            return v
    return pairs[-1][0]


def main():
    rng = random.Random(SEED)
    DATA.mkdir(exist_ok=True)
    ch_w = [(c[0], c[2]) for c in CHANNELS]
    ch_type = {c[0]: c[1] for c in CHANNELS}
    files = {k: open(DATA / f"{k}.jsonl", "w", encoding="utf-8")
             for k in ["users", "events", "tasks", "orders", "credits", "spend", "touch"]}
    pool = []
    today = ANCHOR

    for day_idx in range(DAYS):
        d = today - timedelta(days=DAYS - 1 - day_idx)
        prog = day_idx / (DAYS - 1)
        # ---- 新用户注册 ----
        n_new = int(260 + 340 * prog + rng.uniform(-30, 30))
        for _ in range(n_new):
            ch = _w(rng, ch_w)
            uid = f"u{len(pool) + 1:06d}"
            u = {"user_id": uid, "signup_dt": d.isoformat(), "channel": ch,
                 "channel_type": ch_type[ch], "country": _w(rng, COUNTRIES),
                 "platform": _w(rng, PLATFORMS),
                 "payer": rng.random() < (.06 if ch_type[ch] == "influencer" else .05 if ch_type[ch] == "seo" else .03)}
            # 触点(线性归因用): 注册前接触过的渠道集合
            extras = rng.sample([x for x, _ in ch_w], rng.randint(0, 2))
            touches = {ch} | set(extras)
            for tch in touches:
                files["touch"].write(json.dumps({"user_id": uid, "channel": tch}) + "\n")
            pool.append({**u, "balance": 10, "next_order": None, "touch_cnt": len(touches)})
            files["users"].write(json.dumps(u) + "\n")
            files["credits"].write(json.dumps({"dt": d.isoformat(), "user_id": uid,
                                               "change_type": "signup_grant", "credits": 10}) + "\n")
        # ---- 当日活跃 ----
        actives = [u for u in pool
                   if rng.random() < max(.10, .55 * .5 ** ((d - date.fromisoformat(u["signup_dt"])).days / 5))]
        for u in actives:
            for _ in range(max(2, int(rng.gauss(5.5, 2)))):
                files["events"].write(json.dumps({
                    "dt": d.isoformat(), "user_id": u["user_id"], "page": _w(rng, PAGES),
                    "event_type": "view", "platform": u["platform"], "country": u["country"]}) + "\n")
            files["credits"].write(json.dumps({"dt": d.isoformat(), "user_id": u["user_id"],
                                               "change_type": "grant_daily", "credits": 5}) + "\n")
            u["balance"] += 5
            # ---- 生成任务 ----
            for _ in range(rng.randint(0, 3)):
                mname = _w(rng, [(m[0], m[1]) for m in MODELS])
                _, _, srate, _ = next(m for m in MODELS if m[0] == mname)
                ok = rng.random() < srate
                secs = rng.randint(2, 12)
                cost = min(u["balance"], secs) if ok else 0
                files["tasks"].write(json.dumps({
                    "dt": d.isoformat(), "ts": f"{d.isoformat()}T{rng.randrange(24):02d}:{rng.randrange(60):02d}",
                    "user_id": u["user_id"], "model": mname, "success": ok,
                    "seconds": secs if ok else 0, "credits": cost,
                    "latency": round(max(5, rng.gauss(75, 22)), 1), "platform": u["platform"]}) + "\n")
                if ok and cost > 0:
                    u["balance"] -= cost
                    files["credits"].write(json.dumps({"dt": d.isoformat(), "user_id": u["user_id"],
                                                       "change_type": "consume", "credits": -cost}) + "\n")
            # ---- 订单(首付延迟 + 周期续订, 演示窗内可见续费) ----
            age = (d - date.fromisoformat(u["signup_dt"])).days
            if u["payer"] and u["next_order"] is None and age >= rng.randint(1, 4):
                u["next_order"] = d
            if u["next_order"] == d and rng.random() < .9:
                pname = "lite" if rng.random() < .72 else "pro"
                price, credits = PLANS[pname]
                files["orders"].write(json.dumps({
                    "dt": d.isoformat(), "user_id": u["user_id"], "plan": pname, "amount": price,
                    "refund": rng.random() < .02, "channel": u["channel"], "country": u["country"],
                    "is_first": age <= 5}) + "\n")
                files["credits"].write(json.dumps({"dt": d.isoformat(), "user_id": u["user_id"],
                                                   "change_type": "subscribe_grant", "credits": credits}) + "\n")
                u["balance"] += credits
                u["next_order"] = d + timedelta(days=7)
        # ---- 渠道花费 ----
        for ch, base in [("influencer-tiktok", 380), ("influencer-youtube", 260),
                         ("google-ads", 220), ("facebook-ads", 140), ("affiliate", 120)]:
            files["spend"].write(json.dumps({"dt": d.isoformat(), "channel": ch,
                                             "spend": round(base * (0.8 + 0.4 * prog) * rng.uniform(.85, 1.15), 2)}) + "\n")

    for f in files.values():
        f.close()
    print(f"[sim] {DAYS}天 用户池={len(pool)} 完成 → {DATA}")


if __name__ == "__main__":
    main()
