# -*- coding: utf-8 -*-
"""
MetricHub 自检 —— 把"可信"从承诺变成可执行检查
=============================================
python check.py            # 只做静态/契约检查(不需要 duckdb)
python check.py --data     # 额外做数据侧检查(需要 duckdb + 已 build 的 data/metrichub.duckdb)

检查项(每条对应一个真实踩过的坑):
  A. 口径契约: metrics.yaml 的必填字段/命名/单位/窗口/表达式语法
  B. 前端契约: site/*.html 期望的 JSON 字段 与 out/api/*.json 实际提供的是否一致
     (防"改了 build.py 忘了改前端"和"改了前端忘了改 build"两类静默失败)
  C. 跨文件一致性: 模型清单(模拟器/前端成本表/DWS 成本 CASE)、指标数、页面数
  D. 元数据自检: 已知缺陷是否被显式记录(有缺陷不可怕, 悄悄藏起来才可怕)
  E. [--data] 数据侧: 指标可否取数、时间序列是否为空、分母是否为 0、
     以及"队列成熟度/分母退化"这类会被追问的失真
退出码: 0 = 全部通过; 1 = 有 FAIL
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
semantic = None          # check_metrics_yaml 里导入后供 check_data 复用
OK, WARN, FAIL = [], [], []


def ok(msg):
    OK.append(msg)


def warn(msg):
    WARN.append(msg)


def fail(msg):
    FAIL.append(msg)


# ---------------------------------------------------------------- A. 口径契约
def check_metrics_yaml():
    try:
        import yaml
    except ImportError:
        fail("缺少 pyyaml: pip install pyyaml")
        return None
    with open(ROOT / "metrics.yaml", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    metrics = doc["metrics"]
    names = [m["name"] for m in metrics]
    if len(names) != len(set(names)):
        dup = [n for n in names if names.count(n) > 1]
        fail(f"指标名重复: {sorted(set(dup))}")
    else:
        ok(f"指标命名唯一: {len(names)} 个")

    required = ["name", "title", "group", "desc", "owner", "version", "basis", "expr"]
    groups = {"north_star", "growth", "product", "monetization", "model", "attribution"}
    windows = {"1d", "7d", "14d", "30d"}   # 必须与 semantic.WINDOWS 一致
    grains = {"window", "daily"}                 # 输出语义: 窗口内单值 / 逐日值
    series_grains = {"daily", "none"}            # 能否做逐日拆分
    banned = ("median", "percentile", "stddev", "quantile", "mode")
    for m in metrics:
        n = m.get("name", "?")
        for field in required:
            if not m.get(field):
                fail(f"{n}: 缺必填字段 {field}")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", n):
            fail(f"{n}: 命名不合规(小写下划线)")
        if m.get("group") not in groups:
            fail(f"{n}: group={m.get('group')} 不在 {sorted(groups)}")
        if m.get("default_time") not in windows:
            fail(f"{n}: default_time={m.get('default_time')} 不在 {sorted(windows)}")
        # unit 是注入 AI 上下文的字段, 必须能表达"倍数"类指标(如 ROAS = 收入/花费, 不是美元)
        if m.get("unit") not in {"count", "percent", "usd", "min", "ratio"}:
            fail(f"{n}: unit={m.get('unit')} 不在 count/percent/usd/min/ratio")
        # grain 必须显式声明: 同名指标"窗口值 vs 逐日值"是本项目修掉过的真实歧义
        if m.get("grain") not in grains:
            fail(f"{n}: grain={m.get('grain')} 缺失或不合法 {sorted(grains)}")
        if m.get("series_grain", "daily") not in series_grains:
            fail(f"{n}: series_grain={m.get('series_grain')} 不合法 {sorted(series_grains)}")
        # 去重类指标逐日拆分语义错误, 必须显式关闭 —— 除非声明了滚动去重(rolling_distinct_on)
        if (re.search(r"count\s*\(\s*DISTINCT", m.get("expr", ""))
                and m.get("series_grain") != "none" and not m.get("rolling_distinct_on")):
            warn(f"{n}: 表达式含 count(DISTINCT) 且未声明 rolling_distinct_on —— "
                 f"逐日点相加会重复计数, 确认 series_grain 是否为 none")
        for d in m.get("dimensions", []):
            if not re.fullmatch(r"[a-z][a-z0-9_]*", d):
                fail(f"{n}: 维度名不合规 {d}")
        for fn in banned:
            if re.search(rf"\b{fn}\s*\(", m.get("expr", "")):
                warn(f"{n}: expr 使用 {fn}() —— 与 FILTER 组合时易静默退化, "
                     f"确认 {m['basis']} 里有该列且语义是'毫秒/分钟'而非被截断的日期差")
    ok(f"口径契约字段检查完成({len(metrics)} 个指标, 均声明 grain)")
    # 北极星唯一性: 不该让人翻五个文件才搞清"总分是哪一格"
    north = [m["name"] for m in metrics if m.get("north_star_status")]
    approved = [m["name"] for m in metrics if m.get("north_star_status") == "approved"]
    for m in metrics:
        st = m.get("north_star_status")
        if st and st not in {"approved", "proposed", "rejected"}:
            fail(f"{m['name']}: north_star_status={st} 不合法(approved/proposed/rejected)")
    if not north:
        fail("没有任何指标声明 north_star_status —— 全站无法机器判定'当前北极星是哪个'")
    elif len(approved) != 1:
        fail(f"北极星必须唯一, 当前 approved 的有 {len(approved)} 个: {approved or '无'} "
             f"(north_star group 共 {sorted(north)})")
    else:
        ok(f"北极星唯一: {approved[0]}")
        # 全站文案不得把 north_star 组里的其他成员表述成"推荐北极星"。
        # 注意: 页面写的是中文 title(不是指标名), 用 name 拼匹配串会恒真通过 —— 比没有断言更危险。
        star_titles = {m["title"]: m["name"] for m in metrics if m.get("north_star_status")}
        appr_title = next((t for t, n in star_titles.items() if n == approved[0]), None)
        for p in sorted((ROOT / "site").glob("*.html")):
            t = p.read_text(encoding="utf-8")
            for title, name in star_titles.items():
                if name == approved[0]:
                    continue
                for phrase in (f"推荐<b>{title}</b>", f"推荐 {title}（", f"{title} 作为公司北极星",
                               f"推荐<b>{title}（"):
                    if phrase in t:
                        fail(f"site/{p.name} 仍把『{title}』表述为推荐北极星 —— 与 {approved[0]} 冲突")
        if appr_title:
            if f"推荐<b>{appr_title}</b>" in (ROOT / "site" / "business.html").read_text(encoding="utf-8"):
                fail(f"business.html 仍推荐『{appr_title}』为北极星, 但审计页已改判为 {approved[0]}")
    # 窗口字面量在三处重复(build / semantic / check), 必须有断言兜住漂移
    # 注意: 这里用非局部变量保存, 否则 check_data 里引用不到(此前踩过 NameError)
    global semantic
    try:
        sys.path.insert(0, str(ROOT))
        import semantic as _semantic
        semantic = _semantic
        if set(semantic.WINDOWS) != windows:
            fail(f"窗口字面量与 semantic.WINDOWS 不一致: {sorted(semantic.WINDOWS)} vs {sorted(windows)}")
        else:
            ok(f"窗口字面量与 semantic.WINDOWS 一致: {sorted(windows)}")
    except Exception as e:                                   # noqa: BLE001
        warn(f"无法导入 semantic 校验窗口字面量: {e}")
    if not any(m.get("cohort_maturity_days") for m in metrics):
        warn("没有任何指标声明 cohort_maturity_days —— 队列类指标(留存/激活)末日会出假信号")
    return metrics


# ------------------------------------------------- B/C. 前端 × 产物 契约
def check_contracts():
    api = ROOT / "out" / "api"
    if not api.exists():
        warn("out/api 不存在 —— 先跑 python build.py --fresh 才能做产物契约检查")
        return
    # 1) dashboard.json 的字段必须覆盖前端读取(图表键从前端脚本里反向提取, 防止改了一边忘了另一边)
    dash = json.loads((api / "dashboard.json").read_text(encoding="utf-8"))
    for k in ["generated_at", "kpis", "charts", "tables"]:
        if k not in dash:
            fail(f"dashboard.json 缺字段 {k}")
    html = (ROOT / "site" / "dashboard.html").read_text(encoding="utf-8")
    used = set(re.findall(r"S\('([a-z_0-9]+)'\)", html)) | set(re.findall(r"charts\[['\"]([a-z_0-9]+)['\"]\]", html))
    for key in sorted(used):
        if key not in dash.get("charts", {}):
            fail(f"看板脚本读取 charts['{key}'], 但 dashboard.json 没提供 —— 图表会空")
    for k in ["creations", "creations_7d", "creators_7d", "minutes", "minutes_7d",
              "dau", "new_users", "revenue"]:
        if k not in dash.get("charts", {}):
            fail(f"dashboard.json charts 缺 {k} —— 看板对应图表会空白")
    for k in ["model_margin", "model_success", "channels"]:
        if k not in dash.get("tables", {}):
            fail(f"dashboard.json tables 缺 {k}")
    if dash.get("kpis") and not all("unit" in k and "window" in k for k in dash["kpis"]):
        fail("dashboard.json kpis 项缺 unit/window —— 前端无法格式化/标注窗口")
    # 北极星角色标注必须存在, 否则看板分不清"北极星/配对/消耗"
    if dash.get("kpis") and not any(k.get("role") == "北极星" for k in dash["kpis"]):
        fail("dashboard.json 没有任何 KPI 标注 role=北极星 —— 看板失去焦点")
    # 前端读取的 kpi 字段必须至少有一个 KPI 提供(role 是可选标注, 不必每张卡都有)
    for field in ["title", "unit", "value", "window", "metric", "role"]:
        if not any(field in k for k in dash.get("kpis", [])):
            warn(f"看板脚本读取 kpi.{field}, 但没有任何 KPI 项提供该字段(该分支不会渲染)")
    ok("dashboard.json 契约完整(含前端反向提取的图表键与 KPI 字段)")

    # 数据窗口必须锚定在 simulator.ANCHOR。页面上的日期与数字是随源码一起提交的:
    # 产物一旦跟着 runner 的日期/时区走(CI 用 UTC, 比本地少一天), 窗口整体前移,
    # site/northstar.html 里 "10-07→10-08" 这类日期对在新数据里就不存在 ——
    # evidence.py 的举证门禁会直接失败(CI 首跑就是这么挂的), 且每日 cron 会永远红。
    try:
        sys.path.insert(0, str(ROOT))
        import simulator as _sim
        if dash.get("as_of") != _sim.ANCHOR.isoformat():
            fail(f"dashboard.as_of={dash.get('as_of')!r} 与锚定日期 {_sim.ANCHOR} 不一致 —— "
                 f"产物正在跟着系统日期漂移, 页面上的日期对与数字会失效")
        else:
            ok(f"数据窗口锚定在 {_sim.ANCHOR}(不随 runner 日期/时区漂移)")
    except Exception as e:                                   # noqa: BLE001
        warn(f"无法导入 simulator 校验窗口锚定: {e}")

    # 2) 前端硬编码的模型成本表 必须覆盖产物里的全部模型(否则表格出现 $0.000)
    block = re.search(r"const COST=\{(.*?)\};", html, re.S)
    if not block:
        fail("site/dashboard.html 里找不到 COST 成本表")
    else:
        front_models = set(re.findall(r"'([^']+)'\s*:", block.group(1)))
        data_models = {r["model"] for r in dash["tables"]["model_margin"]}
        missing = data_models - front_models
        if missing:
            fail(f"前端成本表缺模型 {sorted(missing)} —— 表格会显示 $0.000")
        else:
            ok(f"前端成本表覆盖全部 {len(data_models)} 个模型")

    # 3) 每指标一个 JSON, 且名称与 catalog 对齐
    catalog = json.loads((api / "catalog.json").read_text(encoding="utf-8"))
    # 产物条数必须等于源定义条数(实际踩过: out/ 停在旧数量而 YAML 已加新指标)
    src_metrics = None
    try:
        import yaml
        with open(ROOT / "metrics.yaml", encoding="utf-8") as f:
            src_metrics = yaml.safe_load(f)["metrics"]
    except Exception as e:                                   # noqa: BLE001
        warn(f"无法读取 metrics.yaml 校验指标数: {e}")
    if src_metrics is not None and len(catalog) != len(src_metrics):
        fail(f"产物过期: catalog.json 有 {len(catalog)} 个指标, metrics.yaml 有 {len(src_metrics)} 个 "
             f"—— 需重跑 python build.py --fresh")
    # 产物必须是合法 JSON: json.dumps 默认允许 inf/nan 并写成 Infinity/NaN, 那不是合法 JSON,
    # 前端 fetch().json() 会直接抛错(整页白屏)。分母为 0 的比率最易命中 —— 索引里每个比率
    # 都该写 nullif(分母, 0); 这里是产物侧的最后一道闸。
    # 用 parse_constant 精确判定, 不用字符串匹配: notes 里出现"Infinity"这个词是合法的文本。
    def _reject_const(c):
        raise ValueError(f"非法 JSON 字面量 {c}(应写 null)")

    for jf in sorted(api.glob("*.json")):
        try:
            json.loads(jf.read_text(encoding="utf-8"), parse_constant=_reject_const)
        except ValueError as e:
            fail(f"{jf.name} 不是合法 JSON: {e} —— 前端 JSON.parse 会抛错; "
                 f"检查对应指标的分母是否漏了 nullif(...,0)")
    for m in catalog:
        if m.get("grain") not in {"window", "daily"}:
            fail(f"{m['name']}: 产物 catalog 缺合法 grain —— 消费端无法判断窗口值还是日值")
        if m.get("series_grain") not in {"daily", "none"}:
            fail(f"{m['name']}: 产物 catalog 缺合法 series_grain")
        p = api / f"metric_{m['name']}.json"
        if not p.exists():
            fail(f"缺产物 metric_{m['name']}.json —— 语义层页展开会 404")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        if "series" not in d or "by_dim" not in d:
            fail(f"metric_{m['name']}.json 结构异常(缺 series/by_dim)")
        elif d.get("grain") is None or d.get("series_grain") is None:
            fail(f"metric_{m['name']}.json 缺 grain/series_grain —— " 
                 f"回避式默认值会让'两边都缺'被判为一致")
        elif d.get("series_grain") == "none":
            # 去重/比率类不提供日序列是设计(见 metrics.yaml 的 series_grain), 但维度分解应当照给
            if not d.get("notice"):
                warn(f"metric_{m['name']}.json 无日序列但没有 notice 说明原因")
            if not d.get("by_dim"):
                warn(f"metric_{m['name']}.json 既无日序列也无维度分解 —— 语义层页展开会是空壳")
        elif not d["series"]:
            fail(f"metric_{m['name']}.json series 为空 —— sparkline 无数据")
        # 产物声明的 grain 必须与定义一致(防止上下游对同一指标理解不同)
        if d.get("grain") != m.get("grain"):
            fail(f"{m['name']}: 产物 grain={d.get('grain')} 与定义 grain={m.get('grain')} 不一致")
        # 可加性: 只有声明 additive 的指标才允许把序列末点当作窗口求和来读。
        # 与 build.py 同一套兜底(默认 non_additive), 否则"检查器比生产者更严"会让门禁无故变红。
        if m.get("additivity", "non_additive") not in {"additive", "non_additive"}:
            fail(f"{m['name']}: additivity={m.get('additivity')} 不合法")
        if not m.get("additivity"):
            warn(f"{m['name']}: 未显式声明 additivity(按 non_additive 处理) —— "
                 f"建议补上, 它是序列画法与维度求和的共同判据")
        if d.get("series_grain") == "daily" and m.get("grain") == "window" \
                and m.get("additivity", "non_additive") == "non_additive":
            note = d.get("series_note") or ""
            # 不可加的窗口指标, 序列只能是"滚动均值"或"滚动去重" —— 求和一定是错的
            if not ("均值" in note or "去重" in note):
                fail(f"{m['name']}: 窗口粒度且不可加的指标, 序列必须是滚动均值/滚动去重"
                     f"(求和无意义), 当前 series_note={note!r}")
    ok(f"语义层目录 {len(catalog)} 个指标的产物齐全且 grain 一致")

    # 5) AI 演示产物: 工具调用必须带粒度, 上下文必须带已知缺陷, 且引用的指标必须存在
    demo_path = api / "ai_demo.json"
    if demo_path.exists():
        demo = json.loads(demo_path.read_text(encoding="utf-8"))
        known = {m["name"] for m in catalog}
        for qa in demo:
            name = qa.get("metric")
            if name not in known:
                fail(f"ai_demo 引用了不存在的指标 {name}")
            args = (qa.get("tool_call") or {}).get("arguments", {})
            if "granularity" not in args:
                fail(f"ai_demo['{name}'] 的 tool_call 缺 granularity —— L2 调用无法声明粒度")
            if "⚠" not in qa.get("context", ""):
                warn(f"ai_demo['{name}'] 的 L1 上下文没有注入已知缺陷/警示 —— 若该指标本身无缺陷可忽略")

    # 6) 旧名残留(典型: 改了模型清单忘了改文案) + 占位符未解析(改了 build 忘了渲染)
    for p in list((ROOT / "out").glob("*.html")) + list((ROOT / "site").glob("*.html")):
        t = p.read_text(encoding="utf-8")
        for ghost in ["titan-x", "titan_x"]:
            if ghost in t:
                fail(f"{p.relative_to(ROOT)} 残留不存在的模型名 {ghost}")
        if p.parent.name == "out" and "__METRIC_COUNT__" in t:
            fail(f"{p.name} 占位符未解析 —— build.py 未渲染该页")
    ok("模型名残留与占位符检查完成")


# ---------------------------------------------------------- C. 跨文件一致性
def check_cross_file(metrics):
    try:
        import simulator
    except Exception as e:                                   # noqa: BLE001
        warn(f"无法导入 simulator({e}), 跳过跨文件一致性检查")
        simulator = None
    if simulator:
        sim_models = {m[0] for m in simulator.MODELS}
        # 单价现在只在 dbt seed(dbt/seeds/dim_model_cost.csv)里写一遍
        # (此前 CASE 与模拟器重复, 属于会漂移的重复; 更早在 build.py 的 VALUES 里)
        seed = ROOT / "dbt" / "seeds" / "dim_model_cost.csv"
        if not seed.exists():
            fail("dbt/seeds/dim_model_cost.csv 不存在 —— 定价的单一来源缺失")
        else:
            import csv
            with open(seed, encoding="utf-8") as f:
                cost_models = {row["model"] for row in csv.DictReader(f) if row.get("model")}
            if cost_models != sim_models:
                fail(f"dim_model_cost seed 与模拟器模型清单不一致: "
                     f"仅模拟器有 {sorted(sim_models - cost_models)}, "
                     f"仅维表有 {sorted(cost_models - sim_models)}")
            else:
                ok(f"dim_model_cost seed 覆盖全部 {len(sim_models)} 个模型")
        # 锚定日期的 dbt 默认值必须与模拟器一致: build.py 每次会用 --vars 覆盖,
        # 但默认值漂移意味着"不传参的裸 dbt run"会算出另一个窗口的口径 —— 必须断言兜住。
        import yaml as _yaml
        proj = _yaml.safe_load((ROOT / "dbt" / "dbt_project.yml").read_text(encoding="utf-8"))
        dbt_anchor = str((proj.get("vars") or {}).get("anchor_date", ""))
        if dbt_anchor != simulator.ANCHOR.isoformat():
            fail(f"dbt_project.yml 的 anchor_date={dbt_anchor!r} 与 simulator.ANCHOR="
                 f"{simulator.ANCHOR} 不一致 —— 裸 dbt run 会算出错窗口的口径")
        else:
            ok(f"dbt 默认锚定日期与 simulator.ANCHOR 一致({dbt_anchor})")
    # 口径描述里的"承诺词"必须有对应实现, 或在 notes 里明确承认未实现
    promises = {"排除测试账号": ("test", "is_test", "NOT is_test"),
                "仅对有花费的渠道": ("spend", "cac"),
                "失败任务成本": ("success", "api_cost")}
    admitted = ("未实现", "待补", "已知缺陷", "已知限制", "修正路径", "TODO")
    for m in metrics:
        desc_all = m.get("desc", "") + m.get("notes", "")
        impl = m.get("expr", "") + json.dumps(m.get("dimensions", []))
        for phrase, hints in promises.items():
            if phrase not in desc_all:
                continue
            if any(h in impl for h in hints):
                continue
            if any(a in m.get("notes", "") for a in admitted):
                ok(f"{m['name']}: '{phrase}' 未实现但已在 notes 中声明(可辩护)")
            else:
                warn(f"{m['name']}: desc/notes 声明'{phrase}', 但 expr/维度里没有对应实现, "
                     f"notes 里也没承认 —— 这句会被追问")
    ok("文案承诺 × 实现一致性检查完成")


# --------------------------------------------------------------- E. 数据侧
def check_data(metrics):
    try:
        import duckdb
    except ImportError:
        warn("未安装 duckdb, 跳过 --data 检查")
        return
    db = ROOT / "data" / "metrichub.duckdb"
    if not db.exists():
        warn("data/metrichub.duckdb 不存在, 跳过 --data 检查(先 python build.py --fresh)")
        return
    sys.path.insert(0, str(ROOT))
    from semantic import SemanticLayer
    import simulator                                    # 窗口锚(见 simulator.ANCHOR)
    con = duckdb.connect(str(db), read_only=True)
    con.execute("SET threads TO 1")     # 与 build.py 同一口径: 并行浮点求和顺序不定, 会让断言抖
    sl = SemanticLayer(con=con, anchor=simulator.ANCHOR)
    wmap = (semantic.WINDOWS if semantic else {"1d": 1, "7d": 7, "14d": 14, "30d": 30})
    # 序列末点必须等于同窗口的窗口聚合(±0.5%): 这一条能拦住"比率被逐日求和"这类画法错误
    for m in metrics:
        n = m["name"]
        if m.get("series_grain", "daily") == "none" or m.get("grain") == "daily":
            continue          # 不自带序列 / 日粒度指标与窗口聚合同量纲不同, 不适用
        if m.get("rolling_distinct_on"):
            # 滚动去重序列(如北极星的周活跃创作者): 每天的"过去7天去重数"本就不可加,
            # 与窗口聚合的对比不成立 —— 交给"序列单调递增且末点=窗口聚合"的专项检查
            continue
        w = m.get("default_time", "14d")
        try:
            rows = sl.query(n, window=w, granularity="daily")["rows"]
            win = sl.scalar(n, w)
        except Exception:                                    # noqa: BLE001
            continue
        seg = [float(r["value"] or 0) for r in rows[-wmap.get(w, 7):]]
        if not seg or not win:
            continue
        series_last = (sum(seg) if m.get("additivity", "non_additive") == "additive"
                       else sum(seg) / len(seg))
        # 容差说明: 日粒度值本身是 round(...,1) 的四舍五入结果, 每天最多 0.05 的误差在 14 天里
        # 会累积; 而"比率被求和"这类真错误会差十几倍。故取 max(5%, 2 个百分点) ——
        # 既能容忍舍入, 又能抓住数量级错误。
        tol = max(abs(win) * 0.05, 2.0)
        if abs(series_last - win) > tol:
            fail(f"{n}: 序列末点 {series_last:.2f} 与窗口聚合 {win:.2f} 相差 "
                 f"{abs(series_last - win):.2f}(容差 {tol:.2f}) —— 画法(求和/均值/去重)与指标可加性不匹配")
    for m in metrics:
        n = m["name"]
        if m.get("series_grain", "daily") == "none":
            continue          # 设计上不提供日序列
        try:
            series = sl.query(n, window="14d", granularity="daily")["rows"]
        except Exception as e:                               # noqa: BLE001
            fail(f"{n}: 时间序列取数失败 {type(e).__name__}: {e}")
            continue
        vals = [r["value"] for r in series if r["value"] is not None]
        # 累计类指标(默认窗口 > 1 天)每天都应有值; 日增量类(1d)出现空日是合法的(当日无人付费)。
        # 例外 1: 订单类指标的观察窗口天然比注册类短(前 1-2 天还没人下单), 空日属数据边界而非缺陷。
        # 例外 2: expr 里显式写了 nullif(分母, 0) —— 作者已声明"该量在该日无定义"(如当天没有现金收入,
        #         毛利率就没有分母; 窗口末日的注册队列还没有次日)。此时空日是**按设计出参 null**,
        #         与"缺数据"是两回事; 反倒是旧写法 greatest(分母,1) 会把无定义伪装成 0 或一个大负数。
        order_based = m.get("basis") in {"dwd_order", "dws_channel_attr", "dws_channel_roas",
                                         "dws_payer_cohort"}
        declares_null = "nullif(" in str(m.get("expr", ""))
        if len(vals) != 14 and m.get("default_time") != "1d":
            if declares_null:
                ok(f"{n}: 14 天里有 {14 - len(vals)} 天无定义(expr 显式 nullif, 分母为 0) —— "
                   f"按设计出参 null, 不得读作 0")
            elif order_based:
                warn(f"{n}: 14 天里有 {14 - len(vals)} 天无数据 —— 订单类指标的窗口天然更短, "
                     f"建议在 desc 里声明实际观察起点(而不是当作缺陷)")
            else:
                fail(f"{n}: 14 天窗口只返回 {len(vals)} 个非空点 —— 累计口径不该出现空日")
        elif len(vals) != 14:
            warn(f"{n}: 14 天里有 {14 - len(vals)} 天无数据(日增量口径下属合法, 但看板会画成断裂)")
        flat = len(vals) == 14 and len(set(vals)) == 1
        if flat:
            fail(f"{n}: 序列恒定不变({vals[0]}) —— 疑似口径退化或数据未重放")
        # 队列类指标: 末点是否为"未成熟"造成的假下跌
        if m.get("cohort_maturity_days") and len(vals) >= 2:
            if vals[-1] < vals[-2] * 0.5:
                warn(f"{n}: 末点 {vals[-1]} 仅为前一日 {vals[-2]} 的 "
                     f"{vals[-1] / max(vals[-2], 1e-9):.0%} —— 队列未成熟导致的日历截断假信号, "
                     f"消费端需显式标注(已加 immature_last_cohort)")
        # TTFC 类: 值域是否只剩 0/整天(说明时间戳被截断成日期, "分钟"口径退化为布尔量)
        if "ttfc" in n:
            suspicious = bool(vals) and all(v in (0, 1440) for v in vals)
            if suspicious:
                fail(f"{n}: 取值只出现 0/1440 —— 时间戳被截断成日期, "
                     f"'分钟'口径已退化为'是否当日'的布尔量")
            elif vals:
                ok(f"{n}: 取值跨越 {min(vals)}~{max(vals)} 分钟 —— 分钟口径未退化")
    con.close()
    ok("数据侧检查完成")


def main():
    metrics = check_metrics_yaml() or []
    check_contracts()
    check_cross_file(metrics)
    if "--data" in sys.argv:
        check_data(metrics)

    print("=" * 64)
    for m in OK:
        print(f"  [OK]   {m}")
    for m in WARN:
        print(f"  [WARN] {m}")
    for m in FAIL:
        print(f"  [FAIL] {m}")
    print("=" * 64)
    print(f"通过 {len(OK)} · 警告 {len(WARN)} · 失败 {len(FAIL)}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
