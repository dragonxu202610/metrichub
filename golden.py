# -*- coding: utf-8 -*-
"""
MetricHub 黄金查询集 runner —— 第八道门禁(构建方法论 S6 的第二道关)
====================================================================
python golden.py

职责: 把 golden_queries.yml 的每条"业务问题→语义查询→断言"跑一遍:
  known   窗口单值与已知值比对(容差 tol) —— 固定种子+锚点平移数值不变, 断言值天然稳定
  sanity  以 rows 为作用域的布尔表达式(守恒/排序/符号/行数)
  error   行为断言: 查询必须抛错且报错含指定子串(显式失败也是接口契约)

与 evidence.py 的分工: evidence 管"页面↔产物对账", golden 管"定义↔语义回归"——
改 metrics.yaml 任何一条口径后重跑本文件, FAIL 的条目就是被改动的数字/行为清单。
落盘 out/api/golden_results.json 供语义层页引用(页面不手写结果)。
退出码: 0 全过; 1 有 FAIL。
"""
import json
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def main():
    import duckdb
    from semantic import SemanticLayer

    # 窗口锚取产物自己的锚(与 check.py --data 同法): golden 必须对"这次构建"的语义负责
    dash = ROOT / "out" / "api" / "dashboard.json"
    if not dash.exists():
        print("[!] out/api/dashboard.json 不存在 —— 先 python build.py --fresh")
        return 1
    anchor = date.fromisoformat(json.loads(dash.read_text(encoding="utf-8"))["as_of"])

    queries = yaml.safe_load((ROOT / "golden_queries.yml").read_text(encoding="utf-8"))["queries"]
    con = duckdb.connect(str(ROOT / "data" / "metrichub.duckdb"), read_only=True)
    con.execute("SET threads TO 1")            # 与 build 同口径, 断言不因并行抖动
    sl = SemanticLayer(con=con, anchor=anchor)

    results = []
    for q in queries:
        c, a = q["call"], q.get("assert", {})
        spec = {"name": c["metric"], "dims": c.get("dims"),
                "window": c.get("window"), "granularity": c.get("granularity")}
        spec = {k: v for k, v in spec.items() if v is not None}
        row = {"id": q["id"], "question": q["question"],
               "spec": {"metric": c["metric"], **{k: v for k, v in spec.items() if k != "name"}}}
        try:
            if "error" in a:
                # 行为断言: 必须抛错(错误信息是接口契约的一部分)
                try:
                    sl.query(**spec)
                    row.update(status="FAIL", detail=f"期望报错(含『{a['error']}』)但查询成功了 —— 显式失败防线失效")
                except ValueError as e:
                    ok = a["error"] in str(e)
                    row.update(status="PASS" if ok else "FAIL",
                               detail=f"报错含『{a['error']}』" if ok else f"报错为『{e}』, 未含『{a['error']}』")
            else:
                r = sl.query(**spec)
                rows = r["rows"]
                ok, detail = True, f"{len(rows)} 行"
                if "known" in a:
                    v = rows[0].get("value") if rows else None
                    if v is None or abs(float(v) - a["known"]) > a.get("tol", 0.05):
                        ok, detail = False, f"已知值 {a['known']}±{a.get('tol', 0.05)}, 实测 {v}"
                    else:
                        detail = f"{v} == 已知值 {a['known']}"
                elif "exact_rows" in a and len(rows) != a["exact_rows"]:
                    ok, detail = False, f"期望 {a['exact_rows']} 行, 实得 {len(rows)}"
                elif "min_rows" in a and len(rows) < a["min_rows"]:
                    ok, detail = False, f"期望 ≥{a['min_rows']} 行, 实得 {len(rows)}"
                elif "sanity" in a:
                    env = {"rows": rows, "sum": sum, "len": len, "abs": abs,
                           "any": any, "all": all, "max": max, "min": min}
                    verdict = bool(eval(a["sanity"], {"__builtins__": {}}, env))
                    ok = verdict
                    detail = "sanity 成立" if verdict else f"sanity 不成立: {a['sanity']}"
                row.update(status="PASS" if ok else "FAIL", detail=detail)
        except Exception as e:                                  # noqa: BLE001
            row.update(status="FAIL", detail=f"意外异常 {type(e).__name__}: {e}")
        results.append(row)
    con.close()

    npass = sum(1 for r in results if r["status"] == "PASS")
    out = {"anchor": anchor.isoformat(), "total": len(results), "passed": npass,
           "failed": len(results) - npass, "results": results}
    (ROOT / "out" / "api" / "golden_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("=" * 64)
    for r in results:
        mark = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  [{mark}] {r['id']} {r['question'][:34]}… {r.get('detail', '')[:60]}")
    print("=" * 64)
    print(f"黄金查询集: {npass}/{len(results)} 通过 · 结果已落盘 out/api/golden_results.json")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
