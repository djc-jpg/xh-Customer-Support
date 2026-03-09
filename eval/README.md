# 评测说明

本目录包含 V1 的评测资产：

- `customer_support_v1_eval_dataset.json`：40 条结构化评测数据
- `run_eval.py`：对运行中的 `/chat` 服务执行自动评测

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

## 说明

当前脚本主要做可规则化判定：

- intent / sentiment / urgency
- need_tool
- tool match
- retrieval topic hit
- literal safety
- request success

对于“回答是否足够自然”“是否真正解决问题”这类更偏语义的项目，仍建议结合人工复核和 bad case 分析。
