# Trace Schema 与错误分类

## 目标

Trace 的目标不是记录所有细节，而是回答三个问题：

- 这次请求是如何被系统理解的？
- 问题出在检索、规划、工具还是回答生成？
- bad case 如何复盘与修复？

## Trace 设计原则

- 尽量结构化，避免只有文本日志
- 一次请求只对应一个 `trace_id`
- 核心阶段固定：analysis / retrieval / plan / tool_calls / final_answer
- 方便人工阅读，也方便后续自动评测

## 推荐 Trace Schema

```json
{
  "trace_id": "trace-uuid",
  "session_id": "demo-001",
  "timestamp": "2026-03-09T10:00:00+08:00",
  "user_input": "我很着急，我的订单 O1001 到哪了？",
  "analysis": {
    "intent": "order_status",
    "sentiment": "negative",
    "urgency": "high",
    "need_tool": true
  },
  "retrieval": {
    "query": "order_status\n我很着急，我的订单 O1001 到哪了？",
    "top_k": 3,
    "hits": [
      {
        "rank": 1,
        "source": "data/faq.md",
        "score": 0.92,
        "snippet": "订单预计送达时间如何查询..."
      }
    ]
  },
  "plan": [
    {
      "step_id": "s1",
      "content": "确认订单号和用户诉求",
      "requires_tool": false
    },
    {
      "step_id": "s2",
      "content": "调用订单查询工具",
      "requires_tool": true
    }
  ],
  "tool_calls": [
    {
      "tool_name": "query_order",
      "arguments": {
        "order_id": "O1001"
      },
      "status": "success",
      "result": {
        "found": true,
        "status": "已发货"
      }
    }
  ],
  "final_answer": "您好，订单 O1001 当前已发货...",
  "latency_ms": 1320,
  "status": "success"
}
```

## 字段说明

### 顶层字段

- `trace_id`: 一次请求的唯一标识
- `session_id`: 会话标识
- `timestamp`: 请求时间
- `user_input`: 用户原始输入
- `final_answer`: 最终输出
- `latency_ms`: 总耗时
- `status`: `success | partial | failed`

### analysis

- `intent`: 意图分类结果
- `sentiment`: 情绪分类结果
- `urgency`: 紧急度
- `need_tool`: 是否需要外部工具

### retrieval

- `query`: 最终检索查询
- `top_k`: 检索数量
- `hits`: 检索命中列表

### plan

- `step_id`: 步骤编号
- `content`: 步骤说明
- `requires_tool`: 是否依赖工具

### tool_calls

- `tool_name`: 工具名
- `arguments`: 调用参数
- `status`: `success | failed | skipped`
- `result`: 工具返回结果

## 错误分类

推荐统一使用以下错误标签：

- `intent_error`
- `retrieval_error`
- `planner_error`
- `tool_decision_error`
- `tool_argument_error`
- `tool_execution_error`
- `response_grounding_error`
- `response_style_error`
- `frontend_stream_error`
- `unknown_error`

## 错误归因说明

### intent_error

用户问题理解错，导致后续流程全部偏离。

### retrieval_error

检索没有命中正确 FAQ，或命中的内容与问题弱相关。

### planner_error

规划步骤不合理，例如简单问题被过度规划，复杂问题缺少关键步骤。

### tool_decision_error

该调用工具时未调用，或不该调用时误调用。

### tool_argument_error

工具参数缺失、格式错误，或没有做参数澄清。

### tool_execution_error

工具本身调用失败、返回异常、结果为空。

### response_grounding_error

最终回答没有基于检索 / 工具事实，出现明显幻觉或错引。

### response_style_error

回答语气不符合客服场景，例如缺少安抚、过于生硬、与用户情绪不匹配。

### frontend_stream_error

流式返回、状态展示、调试信息面板存在异常。

## Bad Case 记录模板

```json
{
  "case_id": "ORDER_007",
  "expected_behavior": "调用 query_order 并结合 FAQ 给出 48 小时无更新建议",
  "actual_behavior": "只返回了 FAQ，未调用工具",
  "error_layer": "tool_decision_error",
  "root_cause": "need_tool 判断过于依赖订单号格式",
  "fix_direction": "增强 shipping 类问题的工具决策规则"
}
```

## V1 最小要求

V1 至少要做到：

- 每次 `/chat` 请求能生成一个 trace 结构
- 能在前端或日志里看到 `analysis / retrieval / plan / tool_calls / final_answer`
- 能根据错误分类做 bad case 归因
