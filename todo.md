# TODO

## P0 目标

先完成一个可部署、可演示、功能闭环的最小版本：

- 网页可访问
- 对话可用
- 用户信息可收集和记忆
- 任务 CRUD 可通过自然语言完成
- 文件上传与 RAG 可用
- 搜索与研究模式可用
- 部署到 Cloudflare Worker

## 架构约束

在实施过程中，默认遵守以下约束：

- LLM 上下文不能无限增长，需要在 `core` 层实现上下文滑窗
- Cloudflare Worker 存在请求时长和 CPU 时间限制，研究模式不能假设单请求长时间运行
- Qdrant 检索必须依赖 metadata 过滤，不能做无过滤全量搜索
- 意图识别要前置，否则任务工具调用链路不稳定

## 第一阶段：项目骨架

- [x] 新建 `app/` 目录，拆出 `routes`、`core`、`providers`、`services`、`ui`
- [x] 新建 Worker 入口 `app/entry.py`
- [x] 配置 `wrangler.toml`
- [x] 配置 Python Worker 构建与本地开发命令
- [x] 建立基础环境变量说明
- [x] 设计最小可运行的静态前端首页
- [x] 明确标准 Worker 与 Unbound Worker 的部署策略

## 第二阶段：数据库与存储

- [x] 编写 D1 初始化脚本 `migrations/001_init.sql`
- [x] 创建 `users` 表
- [x] 创建 `assistant_settings` 表
- [x] 创建 `conversations` 表
- [x] 创建 `messages` 表
- [x] 创建 `conversation_summaries` 表
- [x] 创建 `tasks` 表
- [x] 创建 `files` 表
- [x] 创建 `research_jobs` 表
- [x] 接入 R2 文件存储
- [x] 接入 Qdrant Cloud
- [x] 完成本地 `.dev.vars` 示例

## 第三阶段：LLM、Provider 与意图识别

- [x] 建立 `llm_base.py`
- [x] 建立 Gemini Chat Provider
- [x] 建立 Embedding Provider 抽象
- [x] 实现统一的 `chat()` 接口
- [x] 实现统一的 `embed()` 接口
- [x] 封装模型错误处理和超时处理
- [x] 定义意图枚举
- [x] 实现轻量意图识别 Prompt
- [x] 区分 `collect_user_profile`、`task_crud`、`search_web`、`deep_research`、`file_qa`、`general_chat`
- [x] 为不同意图切换 Prompt 模板
- [x] 确保任务类请求优先进入工具调用分支

## 第四阶段：对话主链路与上下文滑窗

- [x] 前端生成并持久化 `client_id`
- [x] 后端根据 `client_id` 查找或创建用户
- [x] 对缺失的 `name/email` 做资料补全流程
- [x] 支持 AI 昵称设置与修改
- [x] 保存会话和消息记录到 D1
- [x] 支持加载最近历史消息
- [x] 在 `core` 层实现 Conversation Context Manager
- [x] 实现 “Summary + Recent Buffer” 上下文模式
- [x] 仅向 Prompt 注入最近 5 到 10 轮 Raw Messages
- [x] 当对话超过阈值时触发旧消息总结
- [x] 将总结结果写入 `conversation_summaries`
- [x] 回答时将 summary 与 recent buffer 统一注入上下文

## 第五阶段：任务管理

- [x] 定义任务工具协议
- [x] 实现 `create_task`
- [x] 实现 `update_task`
- [x] 实现 `list_tasks`
- [x] 实现 `delete_task`
- [x] 实现 `get_task`
- [x] 在聊天主流程中接入任务工具调用
- [x] 为任务操作补充最小错误提示
- [x] 验证任务类自然语言在意图识别后能稳定进入 CRUD 流程

## 第六阶段：搜索与研究

- [x] 接入 Serper.dev
- [x] 实现普通搜索服务
- [x] 实现网页抓取与正文抽取
- [x] 定义研究模式触发规则
- [x] 实现 Planner：将复杂问题拆为 3 到 5 个子问题
- [x] 实现 research worker：搜索、抓取、摘要
- [x] 实现结构化 Markdown 报告输出
- [x] 在前端渲染研究报告
- [x] 设计研究任务的异步执行方案
- [x] 评估使用 Cloudflare Queues 或 Durable Objects 承载长耗时研究任务
- [x] 使用 Cloudflare Queues + D1 持久化研究执行状态，替换进程内后台任务
- [x] 若保持标准 Worker，请实现“提交任务 + 心跳轮询 + 结果回填”模式
- [x] 为研究任务增加状态字段：`pending/running/completed/failed`
- [x] 为前端增加研究进度条或处理中提示
- [x] 避免将 Deep Research 绑定在单个长请求中

## 第七阶段：文件上传与 RAG

- [x] 实现文件上传接口
- [x] 校验文件类型和大小
- [x] 文件原件写入 R2
- [x] 文件元数据写入 D1
- [x] 支持 `txt` 与 `md` 文本提取
- [x] 支持 `pdf` 文本提取
- [x] 支持 `docx` 文本提取
- [x] 实现文本分块
- [x] 实现向量写入 Qdrant
- [x] 写入 Qdrant 时统一附带 `user_id`、`file_id`、`chunk_index`、`source_type` 等 payload
- [x] 为 `user_id` 建立 Qdrant Payload Index
- [x] 评估是否为 `file_id` 增加 Payload Index
- [x] 实现按 `user_id` 过滤的相似检索
- [x] 在需要时追加 `file_id` 过滤
- [x] 将 RAG 结果拼装到聊天上下文
- [x] 实现文件列表接口
- [x] 实现文件删除接口
- [x] 删除文件时同步清理 Qdrant 向量

## 第八阶段：前端工作区

- [x] 完成聊天布局
- [x] 完成消息气泡样式
- [x] 完成任务列表侧栏
- [x] 完成文件列表侧栏
- [x] 完成文件上传进度提示
- [x] 完成文件类型标签
- [x] 完成研究报告渲染区域
- [x] 完成研究任务状态展示
- [x] 适配移动端显示

## 第九阶段：测试与验收

- [x] 测试首次进入时资料补全流程
- [x] 测试 AI 昵称修改
- [x] 测试任务新增、修改、删除、查询
- [x] 测试普通联网搜索
- [x] 测试深度研究模式
- [x] 测试研究任务的异步提交与轮询
- [x] 测试文本文件上传和问答
- [x] 测试 PDF/DOCX 上传和问答
- [x] 测试删除文件后的向量清理
- [x] 测试 Conversation Context 滑窗策略
- [x] 测试 summary 与 recent buffer 的拼装是否正确
- [x] 测试部署后公网访问

## 第十阶段：文档与提交物

- [x] 更新 `README.md`
- [x] 补充部署步骤
- [x] 补充环境变量说明
- [x] 补充公开访问地址
- [x] 补充架构说明图
- [x] 补充 `docs/IMPLEMENTATION.md`
- [x] 在实现文档中说明子代理规划
- [x] 在实现文档中说明异步研究任务设计
- [x] 在实现文档中说明上下文滑窗策略
- [x] 在实现文档中说明 RAG 设计
- [x] 在实现文档中说明文件向量化流程
- [x] 在实现文档中说明挑战与解决方案

## 可选加分项

- [x] 支持图片 OCR 并纳入 RAG
- [x] 为研究模式增加简化版 ToT 展示
- [x] 增加任务优先级可视化
- [x] 增加研究报告导出
- [x] 增加最小单元测试集

## 建议执行顺序

1. 项目骨架
2. D1/R2/Qdrant 接通
3. Provider 与意图识别
4. 对话主链路与上下文滑窗
5. 任务管理
6. 文件上传与 RAG
7. 搜索与异步研究
8. 前端完善
9. 文档与部署

## 当前建议

先按 P0 收口，不要一开始就做多模态和 ToT。  
研究模式默认按异步任务设计，不要把长链路硬塞进单请求。  
上下文管理和意图识别要尽早落地，它们会直接决定后面任务管理和 RAG 的稳定性。

## 当前线上地址

- [x] 已部署公网地址：`https://taskmate-homework.keximing-taskmate.workers.dev/`

## 已上线后整改清单

### P0：直接影响面试评分的缺口

- [x] 资料补全前置到所有主链路，缺少姓名或邮箱时优先追问，不再只在 general chat 中顺带提醒
- [x] AI 昵称从后端返回到前端 UI，并在消息头、欢迎语、工作台标题中一致展示
- [x] 任务 `details`/具体需求纳入自然语言解析、存储、修改与展示
- [x] README 补充公网地址、仓库链接占位、演示路径、已知限制
- [x] `docs/IMPLEMENTATION.md` 更新为“当前真实实现状态”，去掉与代码不一致的旧表述

### P1：提升 Agent 感和研究能力

- [x] 将深度研究改成真正的 `planner -> subtask -> synthesis` 流程，而不是固定模板计划
- [x] 将研究执行逻辑独立成 `research agent`，把聊天入口与研究任务执行解耦
- [x] 研究任务增加更明确的步骤进度、子任务状态和失败信息
- [x] 为研究报告补充结构化章节：背景、发现、对比、建议、参考来源
- [x] 评估 Durable Object / Queue 方案，避免只依赖进程内 `asyncio.create_task`

### P1：提升 RAG 含金量

- [x] 将占位 hash embedding 替换为真实 embedding provider
- [x] 支持对话记忆向量化，将长期会话记忆也纳入语义召回
- [x] 为文件管理补充重命名能力
- [x] 为文件问答补充引用来源展示，明确回答基于哪些文件片段

### P2：前端与演示体验

- [x] 在任务卡片中展示任务详情、更新时间和更明确的状态视觉层级
- [x] 在文件工作区中展示上传中、解析中、向量化完成等阶段状态
- [x] 为研究报告增加复制/导出能力
- [x] 增加更清晰的首次使用引导
- [x] 在聊天区增加研究中的思考气泡与动态省略号反馈

## 本轮执行顺序

1. 资料补全前置
2. AI 昵称前后端透出
3. 任务 details 支持
4. README / IMPLEMENTATION 收口
5. 研究与 RAG 进入下一轮增强
