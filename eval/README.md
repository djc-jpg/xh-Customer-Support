# 评测说明

本目录包含当前版本的评测资产：

- `customer_support_v1_eval_dataset.json`：40 条结构化评测数据
- `run_eval.py`：对运行中的 `/chat` 服务执行自动评测
- `results/full-run-latest.json`：最新一次全量评测结果

这套评测的定位是：

- 用一组定义明确的输入样例，验证主链路是否稳定
- 检查 `analysis / retrieval / tool / safety` 等关键环节是否符合预期
- 为 bad case 分析提供结构化证据

这套评测**不是**开放式大模型 benchmark，也**不代表**回答质量已经在所有真实场景下达到最优。

## 运行方式

先确保后端服务已经启动：

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

然后执行：

```powershell
.\.venv\Scripts\python eval\run_eval.py
```

## 常用参数

只跑前 5 条：

```powershell
.\.venv\Scripts\python eval\run_eval.py --limit 5
```

只跑订单类：

```powershell
.\.venv\Scripts\python eval\run_eval.py --category order_status --category shipping_delay
```

自定义输出路径：

```powershell
.\.venv\Scripts\python eval\run_eval.py --output eval\results\latest.json
```

## 输出内容

脚本会产出一份 JSON 报告，包含：

- 总样例数
- 自动通过率
- 各类规则指标
- 每条 case 的实际 trace_id、耗时、分析结果、工具调用与检查结果
- bad case 数量与错误层分布
- 每条失败样例的根因摘要与建议修复方向

## 当前评测覆盖范围

当前脚本主要做可规则化判定：

- intent / sentiment / urgency
- need_tool
- tool match
- retrieval topic hit
- literal safety
- request success

覆盖的业务类别主要包括：

- 订单查询
- 退款
- 登录
- 发票
- 地址修改
- 人工升级
- 越界问题
- 隐私与安全请求

## 如何解读结果

如果报告里出现 `40/40` 或 `auto_pass_rate = 1.0`，应理解为：

- 当前定义好的 40 条结构化样例在规则检查下通过
- 系统在这套已知 case 上的主链路表现稳定

不应直接把它理解为：

- 模型回答已经“完美”
- 面对未见输入也一定稳定
- 所有自然度、完整性、客服语气问题都已彻底解决

对于“回答是否足够自然”“是否真正解决问题”“是否适合真实客服语境”这类更偏语义的维度，仍建议结合人工复核和 bad case 分析。
