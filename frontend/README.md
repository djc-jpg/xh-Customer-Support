# 前端演示页面（纯静态，无构建工具）

这是一个可直接打开的客服 Demo 前端，兼容现有 FastAPI 后端：
- `POST /ingest`
- `POST /chat`（`text/event-stream`，使用 `fetch + ReadableStream`）

## 目录说明

- `index.html`：页面结构（语义化布局）
- `styles.css`：视觉系统与组件样式（Design Tokens + 响应式）
- `i18n.js`：中文文案集中管理（所有 UI 文案统一在这里）
- `app.js`：应用入口与状态管理（会话、消息、请求生命周期）
- `ui.js`：纯渲染层（消息气泡、状态条、设置区、调试面板、toast）
- `sse.js`：`/chat` 流式请求封装（POST + AbortController）
- `parser.js`：增量解析器（兼容标准 SSE 与 legacy 标签流）

## 运行方式

### 方式 1：由后端直接托管（推荐）

在项目根目录启动 FastAPI：

```bash
uvicorn app.main:app --reload
```

浏览器访问：

- `http://127.0.0.1:8000/`

### 方式 2：单独静态服务器

在项目根目录执行：

```bash
python -m http.server 5500 --directory frontend
```

浏览器访问：

- `http://127.0.0.1:5500/`

如果采用方式 2，请修改 `frontend/app.js` 顶部常量：

```js
const BASE_URL = "http://127.0.0.1:8000";
```

## 快速联调

1. 点击“导入知识库”，观察设置区导入状态条与右下角提示。
2. 在左侧输入问题后点击“发送”，确认助手气泡按流式增长。
3. 点击“停止”，确认立即中断流并看到“已停止”状态。
4. 点击“重试”，复用同会话最后一条用户消息再次发送。
5. 展开“调试面板”，切换标签查看：
- 执行轨迹（Plan / Steps / ReAct）
- 检索结果（TopK）
- 工具调用
- 原始信息（可复制 JSON）

## 协议兼容说明

`parser.js` 同时兼容两种后端输出：

1. 标准 SSE：
- `event: plan|step|react|token|debug|done`
- `data: ...`

2. 纯文本 `data` 流（legacy）：
- `[PLAN]`
- `[EXECUTE]`
- `[ReAct-x] Thought/Action/Observation`
- `[FINAL_ANSWER]`
- `[DONE]`

## 安全展示说明

前端会对可能的绝对路径做脱敏（只保留文件名），避免在 UI 中泄露本机目录。
