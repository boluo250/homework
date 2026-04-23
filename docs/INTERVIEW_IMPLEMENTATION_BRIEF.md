# TaskMate 实现说明

## 整体架构

TaskMate 是一个部署在 Cloudflare Worker 上的轻量级任务助理 MVP，采用分层架构：前端 UI 负责对话、任务栏、文件工作区和研究报告展示；Worker API 负责路由请求；主 Agent 负责意图识别、上下文组装和工具调度；服务层负责任务、搜索、研究、文件解析、RAG 和记忆管理。

数据层按职责拆分：D1/SQLite 存用户、对话、任务、文件元数据和研究任务状态；R2/本地文件系统存原始上传文件；Qdrant/本地 JSON 向量库存文件分块向量和长期对话记忆。项目保留本地适配器和 Cloudflare 适配器两套实现，运行时根据绑定和环境变量自动切换，方便本地开发与云端部署保持同一套业务逻辑。

## 子代理规划的具体实现

深度研究不是直接让一个模型一次性回答，而是进入 Research Mode。系统先由 `ResearchAgent` 根据问题类型生成 3 到 5 个研究步骤，每个步骤包含标题、目标、检索词、来源偏好和最大来源数。

每个步骤被视为一个“逻辑子代理”：它独立执行 `搜索 -> 抓取网页 -> 提取证据 -> 生成阶段结论`。`ResearchService` 将主研究任务、子任务、进度和事件持久化到 D1；在 Cloudflare 环境中通过 Queue 分发执行，在本地则用异步任务模拟。所有子代理完成后，主 Agent 汇总 evidence、gaps、references，生成结构化 Markdown 报告。

这个设计没有引入真正复杂的多进程 Agent 框架，但保留了面试中重点关注的 Planner、Sub-task、Tool Use、Progress Tracking 和 Final Synthesis。

## 记忆召回（RAG）的设计与流程

系统使用两类可召回上下文：短期上下文和长期语义记忆。短期上下文来自最近对话，并由 `ConversationContextManager` 在消息过多时压缩成摘要；长期记忆由 `MemoryService` 将用户和助手消息向量化后写入 Qdrant，payload 中包含 `user_id`、`conversation_id`、`message_id`、`role` 和 `source_type=chat_memory`。

用户发起新问题时，主 Agent 会读取用户档案、最近对话、摘要、任务列表，并按需召回长期记忆或文件片段。记忆检索始终按 `user_id` 过滤，避免多用户数据串扰；文件问答则额外按 `file_id` 过滤，确保回答只来自用户选择或相关的文件。

## 提示词的动态调整设计

提示词没有写死成一个大 Prompt，而是由 `PromptBundleRegistry` 动态组装。系统先区分 Router Prompt、Intent Response Prompt 和 File QA Prompt：Router Prompt 负责判断是否调用工具；Response Prompt 根据 `collect_user_profile`、`task_crud`、`deep_research`、`file_qa` 等意图追加不同规则；File QA Prompt 再根据 `summary`、`compare`、`extract`、`qa` 等问答模式切换模板。

Prompt 还会注入运行时上下文，包括用户姓名/邮箱、助手昵称、最近对话摘要、最近消息、任务列表、已选文件 ID、长期记忆召回结果和文件证据片段。`SkillsLoader` 会按场景追加操作指令：默认加载任务技能，选中文件时加载 `file_rag`，出现“研究/调研/方案/tradeoff/compare”等关键词时加载 `research_orchestrator`。这样可以做到不同场景只给模型必要规则，减少无关指令干扰。

## 文件处理与向量化细节

文件上传流程为：校验后缀和大小，保存原始文件到 R2，写入文件元数据到 D1，解析文本，按结构化规则切块，调用 Embedding Provider 生成向量，最后写入 Qdrant。每个向量点包含 `user_id`、`file_id`、`filename`、`chunk_index`、`source_type` 和原始 `text`。

切块策略不是固定粗暴截断：短文档直接作为一个 chunk；简历、JD 等结构化文档优先按段落和标题切分；长文本使用带 overlap 的滑窗切块。向量写入采用批处理，避免上传大文件时单次 Worker invocation 压力过高。删除文件时会同步删除 R2 原件、D1 元数据和 Qdrant 中对应 `file_id` 的向量，保证旧内容不会继续被召回。

## 多模态支持

当前实现支持文本、Markdown、DOCX、PDF、图片、音频和视频进入同一套 RAG 管线。PDF 通过 Mistral OCR 转成文本；图片、音频和视频的多模态提取主要走 OpenRouter MiMo Omni（默认 `xiaomi/mimo-v2-omni`）：图片提取 OCR 和视觉描述，音频提取 ASR 转写，视频提取语音转写、关键画面时间线和画面文字。图片在 Omni 未配置时可回退到 Mistral OCR，音频和视频则要求配置 OpenRouter。

视频文件容易触发 Worker CPU 限制，因此采用两阶段队列：第一条队列消息完成多模态转写并把 transcript 暂存到 R2，第二条队列消息再分批 embedding 并写入 Qdrant。这样把重任务拆开，降低单次执行超时风险。

## 遇到的挑战及解决方案

- Worker 执行时间有限：深度研究和视频处理都改为 Queue + D1 状态机，前端通过轮询展示进度。
- RAG 数据隔离风险：所有向量检索强制携带 `user_id`，文件问答额外携带 `file_id`，删除文件时同步清理向量。
- 本地开发依赖云服务成本高：实现 SQLite、本地 R2、本地 Qdrant JSON 和 deterministic embedding fallback，保证无密钥也能跑通核心流程。
- 上下文窗口增长：使用“摘要 + 最近消息窗口 + 语义记忆召回”的组合，避免把全部历史对话塞进 prompt。
- Prompt 过大或规则冲突：通过 PromptBundle 和场景化 Skill 注入拆分提示词，只在对应意图下追加必要规则。
- 多模态处理较重：图片/PDF 同步处理，视频改为异步两阶段处理，并将研究队列和媒体队列拆开，减少互相阻塞。
