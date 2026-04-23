# TaskMate 实现说明

项目 Demo：https://taskmate-homework.keximing-taskmate.workers.dev/

GitHub 仓库：https://github.com/boluo250/homework

## 整体架构

TaskMate 是一个部署在 Cloudflare Worker 上的轻量级任务助理 MVP，整体采用“前端工作台 + Worker API + Agent 编排 + 服务层 + 多存储后端”的分层架构。前端工作台负责聊天区、任务侧栏、文件工作区和研究进度展示；Worker API 作为统一入口，负责静态资源返回、HTTP 路由分发和队列消费；主 Agent 负责意图识别、上下文组装、Prompt 选择和工具调度；服务层负责任务管理、搜索、研究、文件解析、RAG 和记忆管理；状态与存储层再把数据分别落到关系库、对象存储和向量库中。

一次完整请求的主链路大致是：前端把用户消息发到 Worker；Worker 先补齐当前用户、会话、任务、文件选择等上下文；Agent 再根据意图判断这是资料补全、任务操作、文件问答、实时搜索还是深度研究；若需要执行动作，则通过 Tool 调用进入对应状态层和服务层；最后把结果组织成自然语言回复返回前端。对于耗时较长的深度研究和视频处理，则改为“HTTP 提交 + Queue 异步执行 + 前端轮询状态”的模式，以适配 Cloudflare 的运行时约束。

数据层按职责拆分：D1/SQLite 存用户、对话、任务、文件元数据和研究任务状态；R2/本地文件系统存原始上传文件；Qdrant/本地 JSON 向量库存文件分块向量和长期对话记忆。项目保留本地适配器和 Cloudflare 适配器两套实现，运行时根据绑定和环境变量自动切换，方便本地开发、测试和云端部署共用同一套业务逻辑。

## 统一 Tool 设计

这个项目的一个关键设计，是把自然语言需求统一收敛到 Tool 调用机制中，而不是为每种动作分别设计表单式流程。对用户而言，交互入口始终是聊天；对系统而言，Agent 会先识别意图，再把动作映射到具体 Tool。这样一来，任务管理、资料保存、助手改名、文件问答和研究触发都能复用同一套调度框架，既保证交互一致性，也降低了后端扩展成本。

其中任务能力的收敛最为明显：任务的增删改查并不是散落在多个模块中，而是统一封装在一个 `TaskTool` 中，由 `execute()` 根据动作分发到 `create / update / delete / get / list`。这意味着用户无论表达“创建任务”“修改优先级”“删除刚才那个任务”还是“查看当前任务列表”，在架构上都属于同一个任务域工具，只是 action 不同。该设计既保留了自然语言交互的灵活性，也避免了后端逻辑被拆分得过于零散。

类似地，用户资料保存和助手改名虽然分别由 `ProfileTool` 与 `AssistantIdentityTool` 负责，但它们同样被注册进统一的 `ToolRegistry` 中，并共享同一套 Tool Definition、参数约束、调用排序与结果回传机制。从 Agent 视角看，不同业务能力都可以被当成“可调度工具”；从工程视角看，新增能力时只需要补一个新的 Tool 和对应状态/服务实现，而不需要重写整套对话主流程。

## 子代理规划的具体实现

深度研究并不是直接让单个模型一次性生成答案，而是进入 Research Mode。系统先由 `ResearchAgent` 根据问题类型生成 3 到 5 个研究步骤，每个步骤包含标题、目标、检索词、来源偏好和最大来源数。

每个步骤被视为一个“逻辑子代理”：它独立执行 `搜索 -> 抓取网页 -> 提取证据 -> 生成阶段结论`。`ResearchService` 将主研究任务、子任务、进度和事件持久化到 D1；在 Cloudflare 环境中通过 Queue 分发执行，在本地则用异步任务模拟。所有子代理完成后，主 Agent 汇总 evidence、gaps、references，生成结构化 Markdown 报告。

该设计没有引入复杂的多进程 Agent 框架，但完整保留了面试场景中更关键的 Planner、Sub-task、Tool Use、Progress Tracking 和 Final Synthesis 能力。

## 记忆召回（RAG）的设计与流程

系统使用两类可召回上下文：短期上下文和长期语义记忆。短期上下文来自最近对话，并由 `ConversationContextManager` 在消息过多时压缩成摘要；长期记忆由 `MemoryService` 将用户和助手消息向量化后写入 Qdrant，payload 中包含 `user_id`、`conversation_id`、`message_id`、`role` 和 `source_type=chat_memory`。

用户发起新问题时，主 Agent 会读取用户档案、最近对话、摘要、任务列表，并按需召回长期记忆或文件片段。记忆检索始终按 `user_id` 过滤，避免多用户数据串扰；文件问答则额外按 `file_id` 过滤，确保回答只来自用户选择或相关的文件。

## 提示词的动态调整设计

提示词并没有写成一个固定的大 Prompt，而是由 `PromptBundleRegistry` 动态组装。系统先区分 Router Prompt、Intent Response Prompt 和 File QA Prompt：Router Prompt 负责判断是否调用工具；Response Prompt 根据 `collect_user_profile`、`task_crud`、`deep_research`、`file_qa` 等意图追加不同规则；File QA Prompt 再根据 `summary`、`compare`、`extract`、`qa` 等问答模式切换模板。

Prompt 还会注入运行时上下文，包括用户姓名/邮箱、助手昵称、最近对话摘要、最近消息、任务列表、已选文件 ID、长期记忆召回结果和文件证据片段。`SkillsLoader` 会按场景追加操作指令：默认加载任务技能，选中文件时加载 `file_rag`，出现“研究/调研/方案/tradeoff/compare”等关键词时加载 `research_orchestrator`。这样可以做到不同场景只给模型必要规则，减少无关指令干扰。

## 文件处理与向量化细节

文件上传流程为：校验后缀和大小，保存原始文件到 R2，写入文件元数据到 D1，解析文本，按结构化规则切块，调用 Embedding Provider 生成向量，最后写入 Qdrant。每个向量点包含 `user_id`、`file_id`、`filename`、`chunk_index`、`source_type` 和原始 `text`。

切块策略不是固定粗暴截断：短文档直接作为一个 chunk；简历、JD 等结构化文档优先按段落和标题切分；长文本使用带 overlap 的滑窗切块。向量写入采用批处理，避免上传大文件时单次 Worker invocation 压力过高。删除文件时会同步删除 R2 原件、D1 元数据和 Qdrant 中对应 `file_id` 的向量，保证旧内容不会继续被召回。

## 多模态支持

当前实现支持文本、Markdown、DOCX、PDF、图片、音频和视频进入同一套 RAG 管线。PDF 通过 Mistral OCR 转成文本；图片、音频和视频的多模态提取主要走 OpenRouter MiMo Omni（默认 `xiaomi/mimo-v2-omni`）：图片提取 OCR 和视觉描述，音频提取 ASR 转写，视频提取语音转写、关键画面时间线和画面文字。图片在 Omni 未配置时可回退到 Mistral OCR，音频和视频则要求配置 OpenRouter。

视频文件容易触发 Worker CPU 限制，因此采用两阶段队列：第一条队列消息完成多模态转写并把 transcript 暂存到 R2，第二条队列消息再分批 embedding 并写入 Qdrant。这样把重任务拆开，降低单次执行超时风险。

## 遇到的挑战及解决方案

- Cloudflare 线上环境与本地环境差异较大：本地能跑通的搜索、抓取、多模态解析和报告汇总，部署到 Worker 后会受到 CPU 时间、请求生命周期和平台限制影响。为此，系统将重任务改为 Queue + D1 状态机驱动，并在云端请求链路补充了超时控制，避免任务无限挂起。
- 深度研究链路最复杂的问题是分布式状态一致性：真实调试中先后出现过任务卡在 `orchestrating`、`2/3`、`synthesizing` 等阶段，根因分别涉及队列重复投递、子任务乱序执行、重复 orchestrate 以及汇总阶段外部模型调用挂住。最终通过将 orchestrator 设计为幂等、把子任务改成顺序派发、对重复消息直接忽略，并补全 phase/event 持久化和回归测试，稳定了这条主链路。
- RAG 的难点不只是“检索到内容”，更在于可控性和可信度：一方面需要严格按 `user_id`、`file_id` 做过滤，避免多用户和多文件内容串扰；另一方面底部引用不能只展示 top-k 检索结果，否则会出现“回答正确但参考来源不准确”的问题。后续系统将引用机制改成要求模型显式返回 `EVIDENCE_IDS`，再由后端映射回真实片段，使引用更接近实际证据。
- 多模态文件支持的难点在于不同媒介的处理方式完全不同，而且视频在 Free 计划下最容易超时：图片适合 OCR/视觉理解，音频需要转写，视频还要同时处理语音、关键画面和画面文字。最终系统采用组合式解析路由，PDF 走 Mistral OCR，图片优先走 OpenRouter 多模态模型，音频和视频统一走 Omni 模型；其中视频改成异步入队处理，避免上传请求直接撞上 Worker CPU 限制。

## 面试需求完成情况对照

### 2. 核心功能需求（必须完成）

- 2.1 基础对话与用户管理
  - 实现网页对话界面，支持聊天区、任务侧栏、文件工作区和研究进度展示。✅
  - 当用户未提供邮箱和姓名时，AI 会主动追问并持久化存储。✅
  - 后续对话中，AI 能正确使用用户姓名称呼用户。✅
  - 用户可以为 AI 设置昵称，并支持后续修改。✅

- 2.2 任务管理（vibe coding 方式）
  - 用户通过自然语言对话完成任务的增删改查，以及任务需求细节维护。✅
  - 不依赖传统表单，任务操作由 Agent + Tool 调用完成。✅

- 2.3 外部搜索与深度研究
  - 已实现基于 Serper 的实时搜索接口；配置 `SERPER_API_KEY` 后可启用线上实时信息检索。✅
  - 面对复杂研究主题，系统可先规划步骤，再拆分“逻辑子代理”执行多轮搜索、证据提取与汇总，最终生成结构化 Markdown 报告。✅

- 2.4 文件处理与 RAG 系统
  - 用户可上传 PDF、Word、TXT、Markdown 等文件。✅
  - 系统会自动解析、切块、向量化，并存入向量数据库（Qdrant Cloud / 本地 fallback）。✅
  - 后续对话中，AI 可通过语义检索召回相关文档片段作为上下文增强回答。✅
  - 支持对上传文件的增删改查，并在工作空间中进行管理。✅

- 2.5 数据持久化
  - 使用 Cloudflare D1（本地为 SQLite fallback）存储用户信息、任务列表、对话记录、研究任务状态等。✅
  - 使用向量数据库（Qdrant / 本地 JSON fallback）存储文档片段与长期对话记忆。✅

### 3. 加分项（可选，可显著提升评价）

- 多模态大模型应用：已支持图片、音频、视频的内容提取，并纳入 RAG 与对话上下文；其中视频链路已按 Cloudflare 运行时约束改为异步处理(但是提取受到cpu limit 限制)。✅
- 实现 Tree of Thoughts (TOT) 或 Graph of Thoughts (GOT) 推理模式，并展示其效果。未实现
- 提供完整的前端工作空间（文件浏览器、上传进度条、文件类型标签）。✅
- 实现细粒度的意图识别与动态 Prompt 模板选择。✅
- 完善的单元测试与部署流水线。✅
