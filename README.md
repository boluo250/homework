# TaskMate Homework

TaskMate 是一个部署在 Cloudflare Workers 上的对话式工作台 Demo。它把用户资料记忆、自然语言任务管理、文件 RAG 问答、网页搜索和异步深度研究放在同一个聊天界面里，目标是完成一个可演示、可部署、可测试的面试作业 MVP。

## Public Demo

- Live URL: [taskmate-homework.keximing-taskmate.workers.dev](https://taskmate-homework.keximing-taskmate.workers.dev/)

## 当前真实功能

- Web 工作台：聊天区、任务侧栏、文件工作区、研究进度卡片、移动端基础适配。
- 用户资料：前端生成并持久化 `client_id`，后端按 `client_id` 创建用户；缺少姓名或邮箱时会优先引导补全。
- 助手昵称：支持通过自然语言修改助手名称，并同步到后端、消息头和页面标题。
- 对话记忆：会话消息落库，使用 summary + recent buffer 控制上下文长度；同时把长程聊天记忆写入向量库用于语义召回。
- 任务管理：通过聊天 Agent 执行任务创建、查询、更新、删除；任务包含标题、详情、状态、优先级、截止时间。`/api/tasks` 当前用于前端读取任务列表。
- 文件工作区：支持上传、列表、详情预览、重命名、删除；删除文件时同步清理原始文件和向量。
- 文件 RAG：上传内容会解析、切块、embedding 并写入 Qdrant；问答时按 `user_id` 和可选 `file_id` 过滤召回，并通过 `EVIDENCE_IDS` 协议给回答追加文件片段引用。
- 支持的文件类型：`txt`、`md`、`docx`、`pdf`、图片、音频、视频；单文件默认最大 10MB。
- 多模态解析：PDF 使用 Mistral OCR；图片优先走 OpenRouter MiMo Omni，未配置时可回退 Mistral OCR；音频和视频依赖 OpenRouter MiMo Omni。
- 视频入库：Cloudflare 队列可把视频处理拆成“转写”和“向量化”两步，降低单次 Worker CPU 压力。
- 搜索：普通实时问题可走 Serper 搜索；未配置 `SERPER_API_KEY` 时返回明确的配置提示。
- 深度研究：复杂调研会创建 research job，走规划、子任务搜索/抓取、证据汇总、Markdown 报告生成；前端轮询进度并支持复制/导出报告。
- 管理重置：前端“清空数据”会调用 `/api/admin/reset`，清理 D1/SQLite、R2/local files 和 Qdrant/local vectors。

## 项目结构

```text
app/
  entry.py                 # Worker 入口、路由分发、队列消费者
  routes/                  # chat/tasks/files/research/admin API
  core/                    # Agent、意图识别、上下文、模型数据结构
  runtime/                 # prompt、tool registry、skills loader
  tools/                   # profile/task/rag/research/admin 工具
  services/                # D1/R2/Qdrant、文件解析、搜索、研究、LLM client
  state/                   # 用户、任务、文件、研究、会话状态封装
  ui/                      # 静态前端
  skills/                  # file_rag、task_os、research_orchestrator 指令
migrations/
  001_init.sql             # D1/SQLite 兼容 schema
tests/                     # 单元与端到端回归测试
docs/                      # 实现说明、验收与演示文档
```

## 运行模式

本地开发和 Cloudflare 线上运行复用同一套接口，`app/entry.py` 会根据绑定自动选择适配器。

| 能力 | 本地模式 | Cloudflare 模式 |
| --- | --- | --- |
| 关系数据库 | `.taskmate/taskmate.db` SQLite | D1 binding `DB` |
| 原始文件 | `.taskmate/r2/` 本地文件 | R2 binding `FILES_BUCKET` |
| 向量库 | `.taskmate/qdrant_document_chunks.json` | Qdrant Cloud REST |
| 异步研究 | 进程内 `asyncio` fallback | Queue binding `RESEARCH_QUEUE` |
| 视频入库 | 同步或本地 fallback | Queue binding `MEDIA_INGEST_QUEUE` |

## 主要 API

| API | 方法 | 用途 |
| --- | --- | --- |
| `/`、`/app.js`、`/styles.css` | GET | 前端页面和静态资源 |
| `/api/chat` | GET | 读取当前用户资料和助手昵称 |
| `/api/chat` | POST | 聊天主入口，触发资料、任务、搜索、文件问答、研究意图 |
| `/api/tasks` | GET | 按 `client_id` 或 `user_id` 返回任务列表 |
| `/api/files` | GET | 文件列表或单文件详情 |
| `/api/files` | POST | base64 文件上传、解析、向量化或入队 |
| `/api/files` | PATCH | 重命名文件，要求扩展名不变 |
| `/api/files` | DELETE | 删除文件、原始对象和向量 |
| `/api/research` | POST | 提交异步研究任务 |
| `/api/research` | GET | 按 `job_id` 轮询研究状态和报告 |
| `/api/admin/reset` | POST | 清空当前环境数据，需 `confirm=RESET_ALL_DATA` |

## 环境变量

本地可从 `.dev.vars.example` 复制：

```bash
cp .dev.vars.example .dev.vars
```

常用配置：

| 变量 | 用途 |
| --- | --- |
| `OPENROUTER_API_KEY` | 聊天模型、工具调用、图片/音频/视频文本抽取 |
| `OPENROUTER_MODEL` | 聊天模型，线上当前配置为 `moonshotai/kimi-k2.6` |
| `OPENROUTER_OMNI_MODEL` | 多模态抽取模型，默认 `xiaomi/mimo-v2-omni` |
| `MISTRAL_API_KEY` | PDF OCR，图片 OCR fallback |
| `MISTRAL_OCR_MODEL` | Mistral OCR 模型，默认 `mistral-ocr-latest` |
| `SERPER_API_KEY` | Google/网页搜索 |
| `QDRANT_URL`、`QDRANT_API_KEY` | Qdrant Cloud 向量库 |
| `EMBEDDING_API_KEY`、`EMBEDDING_API_URL`、`EMBEDDING_MODEL` | 可选远程 embedding；缺失时使用确定性本地向量 fallback |
| `APP_NAME`、`R2_BUCKET_NAME` | OpenRouter 标题和 R2 bucket 名称 |

没有外部密钥时，本地仍可启动并跑大部分纯逻辑测试；但真实聊天质量、搜索、OCR、多模态和远程向量库能力会降级或报出清晰配置错误。

## 本地开发

1. 安装 Node 依赖：

   ```bash
   npm install
   ```

2. 准备本地环境变量：

   ```bash
   cp .dev.vars.example .dev.vars
   ```

3. 启动 Worker 本地开发：

   ```bash
   npx wrangler dev
   ```

4. 打开 Wrangler 输出的本地地址。首次访问会创建本地 `.taskmate/` 数据目录。

## Cloudflare 部署

1. 创建 D1：

   ```bash
   npx wrangler d1 create taskmate-homework-db
   ```

2. 把返回的 `database_id` 写入 `wrangler.toml`。

3. 创建 R2 bucket：

   ```bash
   npx wrangler r2 bucket create taskmate-homework-files
   npx wrangler r2 bucket create taskmate-homework-files-dev
   ```

4. 创建队列：

   ```bash
   npx wrangler queues create taskmate-research-jobs
   npx wrangler queues create taskmate-media-ingest
   ```

5. 设置 secrets：

   ```bash
   npx wrangler secret put OPENROUTER_API_KEY
   npx wrangler secret put MISTRAL_API_KEY
   npx wrangler secret put SERPER_API_KEY
   npx wrangler secret put QDRANT_API_KEY
   ```

6. 应用数据库 schema：

   ```bash
   npx wrangler d1 execute taskmate-homework-db --file migrations/001_init.sql --remote
   ```

7. 部署：

   ```bash
   npx wrangler deploy
   ```

## 测试与验收

推荐回归命令：

```bash
uv run pytest -q
```

如果不用 `uv`，先确保本地有 `pytest`，再运行：

```bash
python3 -m pytest
```

面试演示脚本：

```bash
python3 scripts/run_demo_e2e.py
```

重点测试覆盖：

- `tests/test_demo_e2e_acceptance.py`：对话、资料、任务、搜索、文件 RAG、研究端到端演示。
- `tests/test_agent_task_flow.py`：自然语言任务流程。
- `tests/test_agent_file_qa.py`、`tests/test_file_service_cleanup.py`：文件问答、引用协议和文件生命周期。
- `tests/test_research_service.py`：研究任务提交、状态推进和报告生成。
- `tests/test_context_manager.py`：summary + recent buffer 上下文策略。

## 推荐演示路径

1. 打开公开 Demo 或本地页面。
2. 直接说“帮我创建一个简历优化任务”，展示资料补全优先级。
3. 回复“我叫小李，邮箱是 xiaoli@example.com，以后叫你阿塔”，展示用户资料和助手昵称持久化。
4. 创建任务：“创建一个‘简历优化’任务，要求突出 Agent、RAG 和 Cloudflare Worker 项目经验，下周五前完成，高优先级”。
5. 上传一份 `txt/md/docx/pdf` 或图片文件，选中文件后问“总结这个文档并给出改进建议”。
6. 发起研究：“帮我调研 Cloudflare Worker 上做 RAG 的轻量实现方案”，观察研究进度和最终 Markdown 报告。

## 当前限制

- 任务写操作主要通过聊天 Agent 工具完成，`/api/tasks` 目前只提供列表查询给前端侧栏使用。
- Worker Free 计划下 CPU 时间有限，视频和大文件处理可能失败；仓库已用队列拆分视频处理，但仍建议演示短文件。
- 远程 embedding 只有在同时配置 `EMBEDDING_API_KEY` 和 `EMBEDDING_API_URL` 时启用，否则使用本地确定性向量，适合测试但不代表生产语义效果。
- PDF OCR 依赖 `MISTRAL_API_KEY`；音频和视频解析依赖 `OPENROUTER_API_KEY` 与支持多模态的模型。
- Qdrant Cloud 使用固定集合 `document_chunks`，所有检索必须带 `user_id`，文件问答可进一步带 `file_id`。
- 深度研究依赖 Serper、网页抓取和 LLM 汇总；外部服务不可用时会降级为配置提示或 fallback 报告。
