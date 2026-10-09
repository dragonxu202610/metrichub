# MetricHub — 受 AI 消费的指标语义层

> 一次定义，处处一致：31个业务指标以 YAML 声明为唯一事实源，编译成 SQL 供看板取数，
> 同时作为上下文（L1）与工具（L2）提供给 AI 问答——口径歧义在机器层消灭。

面向「多模型聚合 + 积分订阅制」AI 视频平台的业务形态（模拟数据，14 天；每条业务设定的公开出处见站内「信源」页）。
两层引擎：**数仓层 dbt**（16 个模型 + 74 项行级测试 + 口径守恒断言，血缘可点开）与
**语义层 `semantic.py`**（约 116 行，生产对应物 dbt MetricFlow / Cube）。另有演示级流批对账样例（`streaming/`）。

## 快速开始

```bash
pip install duckdb pyyaml dbt-core dbt-duckdb   # 构建期依赖(产物站本身零依赖)
python build.py --fresh          # 模拟数据 → dbt(模型+行级测试) → 语义层查询 → 静态站导出 out/
                                  # 锚点默认=构建当日; 复现历史构建用 --anchor 2026-10-08
python check.py --data           # 自检: 口径契约 / 前端×产物契约 / 跨文件一致性 / 数据侧失真
python evidence.py               # 举证: 页面引用的数字能否从 out/api 复算(可核性)
python northstar_eval.py         # 北极星评估: 预注册判据 + 三候选的相关/弹性, 落盘 northstar_evidence.json
python compare_out.py            # 确认 out/ 已是 site/ 的最新产物(否则线上是旧页面)
python verify_served.py          # 端到端: 断言发布页面里关键事实与北极星标注是否真的渲染出来
python -m http.server 8898 --directory out   # 打开 http://127.0.0.1:8898

# 数仓层单独操作(模型 SQL/测试/血缘都在 dbt/ 目录):
python -m dbt.cli.main build --project-dir dbt --profiles-dir dbt --vars '{"anchor_date":"2026-10-08"}'
python -m streaming.replay       # 流批对账三口径重放(确定性, 守恒断言内置)
```

| 页面 | 内容 |
|------|------|
| 总览 | 为什么需要语义层（口径分裂 / 取数排队 / AI 答数不可信） |
| 业务解构 | 推断画像：业务域结构图 / 团队构成 / 北极星拆解树 / 阶段诊断与处方 |
| 北极星审计 | 把推荐的北极星当假设来审：口径语义 / 拆解树覆盖率 / 可归因性 / 三条在演示数据上可复现的反驳 / 推翻条件 |
| 看板 | 北极星 / 模型毛利 / 双口径渠道归因——每个数字来自一条 YAML |
| 语义层 | 31个指标目录 + [dbt 血缘图](https://dragonxu202610.github.io/metrichub/dbt-docs/index.html)：source→DWD→DWS 的 DAG、行级测试与口径注释 |
| AI 问答 | 五个真实问题的完整链路：L1 注入 → L2 工具调用 → 编译 SQL → 结果 → 裸 SQL 会错在哪 |
| 公开信源 | 每条业务设定的出处可点开核对：事实(有源) / 推断(标注) / 估算(注明时点) / 假设(声明) |
| 流批对账 | 同一条流三种口径（批精确 / watermark / 纯到达序）：丢弃与错配是两种不同的病 + Flink 原语映射 |

> 站点页面与 README 里的指标数由构建期统一渲染（`31` 占位符），加指标不必手改文案。

## 结构

```
metrichub/
├── metrics.yaml        # ★ 语义层: 31指标定义(名称/口径/维度/默认窗口/粒度/可加性/版本/争议)
├── semantic.py         # ★ 引擎: compile(YAML→SQL) / query(query_metric底层) / ai_context(L1注入)
├── dbt/                # ★ 数仓层: sources(JSONL)→staging→DWD→DWS; schema.yml 行级测试;
│                       #   2 项口径守恒断言(现金/分摊); seeds=定价单一来源; 血缘 dbt docs --static
├── streaming/          # ★ 流批对账样例(演示级纯Python): 1h滚动窗口+45min有界乱序+迟到注入
├── simulator.py        # 14天业务模拟(SEO红人渠道/积分订阅/8家真实市场模型, Veo 3.1 旗舰负毛利)
│                       #   锚点默认=构建当日, 固定种子下锚点平移只动日期不动数值
├── build.py            # 一键编排: dbt build(含测试) → dbt docs → 语义层查询 → out/ 静态站
├── check.py            # 自检: 口径契约 / 前端×产物契约 / 跨文件一致性 / 数据侧失真(--data)
├── evidence.py         # 举证检查: 页面引用的每个数字能否从产物复算出来(含流批守恒)
├── northstar_eval.py   # 北极星评估: 判据预注册 + 三候选×收入/续费的相关与弹性落盘
├── compare_out.py      # 产物新鲜度: site/ 改了但没重跑 build 时, 线上就是旧页面
├── verify_served.py    # 端到端断言: 抓发布页面, 查关键事实与北极星标注是否真的渲染出来
├── js_syntax_probe.py  # 前端语法哨兵: 模板字面量/括号/script 配对(无 Node 也能查白屏类错误)
├── PLAN-90D.md         # 90 天落地计划: 数据从哪来、要谁给什么、明确不做什么
├── site/               # 8 页 + CSS(纸白编辑风) + out/dbt-docs 血缘图(构建期生成)
└── .github/workflows/pages.yml
```

## 口径能力与已知限制

**已具备**：`grain`（window/daily）与 `additivity`（可加 / 不可加）都是指标定义的一部分，消费端必须显式
声明 `granularity`；`series_grain=none` 的去重/比率类不会被硬拆成日序列；`ttfc_median` 用带分钟精度的
时间戳计算"注册 → 首次成功生成"的真实间隔；`retention_d1` 只认"注册次日当天"有活动（无界滚动留存会
把 D2 之后才回来的人也算进去，实测 84.2% vs 真值 48.1%）；去重类指标的趋势按输出日**重算窗口去重**，
不是把逐日人头相加（那是"人·天"，会把北极星 4,278 人显示成 7,142）；毛利率用**现金口径**
（实收订单按消耗积分占比分摊），不再把白送额度的燃烧记成收入（旧口径 33.1% vs 现金 12.9%）；所有比率的分母
都写 `nullif(分母, 0)` —— 分母为 0 时出参 `null` 而不是 `inf`（`inf` 会被 `json.dumps` 写成非法 JSON，
前端 `JSON.parse` 直接抛错），`build.py` 写产物前还会再压一道，`check.py` 对全部产物做严格 JSON 校验。

**数仓层（dbt）**：行级测试覆盖 not_null / unique / accepted_values / relationships（如渠道清单、套餐、
模型名单、外键到用户表）；两项口径守恒断言——`dws_cash_day` 必须精确等于订单非退款聚合、
`dws_model_day` 每日分摊收入之和必须回到当日现金（±$0.05 舍入容差）；迁移自旧内联 ELT 时以
**基线逐字节 diff** 验收（等价迁移，语义层零改动）。

| 限制 | 现状 | 修法 |
|---|---|---|
| 看板图表依赖 ECharts CDN | 数据与页面本地零依赖，图表库是唯一外部资源；已做多 CDN 串行兜底 + 全部失败降级 | 彻底解法：内联 ECharts（~350KB，Pages 放得下） |
| `ttfc_median` 注册时刻精度 | 注册时刻按当日 00:00 计（`users` 表只有日期） | 生产需接入带时分的注册事件 |
| 积分台账无资金来源 | `consume` 不记录"这一笔花的是赠送还是购买"，故 `free_credit_burn_rate` / `paid_credit_burn_rate` 只能换分母、不拆分子；毛利率的现金分摊也只能按当日消耗占比 | 台账加资金来源字段，或做 FIFO 消耗顺位 |
| 递延收入未建模 | 现金在当期全额确认，已售未消耗的积分（负债）没有单独口径 | 引入 `dwd_subscription` 事实表 + 递延收入科目 |
| 线性归因的助攻信号 | `touch_cnt` 与渠道类型无关，且表达式结构上只能给注册渠道记账 → 线性合计 $1,693 vs 首触 $2,829，40% 收入不归属任何渠道 | 建订单 × 触点桥接表（weight=1/touch_cnt）后再归因 |
| 窗口比率的趋势 | `company_gross_margin` / `high_cost_exposure` 这类窗口比率**不提供日序列**——逐日比率的均值与窗口比率不是同一个量（实测 3.14 vs 12.90） | 需要趋势时按"窗口内分子和 / 分母和"逐日重算 |
| 北极星树仍有 2 个缺口 | 会话/访客数、沉默召回没有对应指标（叶子节点"有定义"的比例为 5/7，其中口径可信的 4/7） | 需要先补埋点维度，不是加一条 YAML 能解决 |
| AI 问答为构建时预计算 | 五问链路是 `build.py` 落盘的 JSON 快照，页面上不发生模型调用（页面已醒目标注） | 补 `query_metric` 的 MCP / HTTP 出口，接真实 LLM 走同一条编译 |
| 流式样例为演示级 | `streaming/` 是纯 Python 重放，验证的是口径偏差模式（丢弃 vs 错配），不是生产流 | 生产链路 Kafka→Flink→OLAP 的设计在 PLAN-90D；本样例的三口径对账即其验收方法 |

## 设计要点

- **口径即代码**：`paying_users` 的"含不含退款"、激活的 1d/7d 两派、归因的首触/线性——全部显式注册（含 notes 治理痕迹），分歧可见而非互斥
- **粒度也是口径**：每个指标声明 `grain`（窗口内单值 / 逐日值）与 `series_grain`（能否拆日）。同名指标"周值 13,542 vs 日值 2,469"这类歧义，靠消费端显式传 `granularity` 关闭，而不是靠约定
- **数仓与语义层分工**：dbt 管"表怎么来"（分层/测试/血缘，`ref()` 声明显式依赖），语义层管"指标怎么算"（口径/粒度/可加性）——两层各自的治理痕迹（口径注释、守恒断言、notes 争议）都可被机器检查
- **北极星可被证伪**：「北极星审计」页给出拆解树覆盖率、三条在演示数据上可复现的反驳与推翻条件——指标定义错了不可怕，没人能发现它错了才可怕
- **AI 三层递进**：L1 上下文注入（消灭同义词/隐式默认/时间语义，并**显式注入已知缺陷**）→ L2 `query_metric()` 工具调用（AI 不写 SQL，口径错误在编译层被关掉；非 SQL 类错误仍可能出现）→ L3 口径自动治理（路线图）
- **看板与 AI 同源**：两处消费跑同一条编译 SQL——单一事实源不是承诺一致，是结构上无法不一致
- **流批要对账，不是要相信**：流式结论必须与批口径守恒校验（丢弃进侧输出可审计，错配则毫无痕迹）——见「流批对账」页

## 部署 GitHub Pages

```bash
# 本仓库: https://github.com/dragonxu202610/metrichub
# 仓库 Settings → Pages → Source 选 GitHub Actions, push main 即发布; cron 每日重跑
```

工作流每次 push 到 `main` 都会重放数据、跑 dbt 测试与七道门禁、发布快照。
**锚点默认=构建当日**（每日 cron 让窗口真正前滚，站点不"变旧"）；需要逐字节复现某个历史构建时
`python build.py --fresh --anchor 2026-10-08`。固定种子下锚点平移只平移日期标签、全部数值不变
（页面结论不随每日重建失效）。数据均为模拟生成，仅作架构演示；业务设定的公开出处见站内「信源」页。

## License

MIT（见 [LICENSE](LICENSE)）。
