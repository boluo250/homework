# 面试展示版端到端测试

这份文档配套 [`tests/test_demo_e2e_acceptance.py`](/Users/kkk/kkk-magic/homework/tests/test_demo_e2e_acceptance.py:1)，目标不是把所有边界情况都测满，而是给面试官一个很直观的证据：

- 这个项目不是“接口拼起来了”，而是关键链路真的闭环了。
- 对话式资料补全、任务管理、搜索、深度研究、文件上传与 RAG 都能串起来。
- Cloudflare Worker 形态下的 API 入口已经具备演示价值。

## 怎么跑

本地直接执行：

```bash
python3 -m pytest tests/test_demo_e2e_acceptance.py -q
```

如果你使用 `uv`：

```bash
uv run pytest tests/test_demo_e2e_acceptance.py -q
```

如果现场环境没有装 `pytest`，可以直接跑这个无依赖演示脚本：

```bash
python3 scripts/run_demo_e2e.py
```

## 这 3 个 E2E 测试分别证明什么

### 1. 对话 + 用户资料 + 任务 + 搜索闭环

对应测试：
- [`test_demo_e2e_chat_task_and_search_flow`](/Users/kkk/kkk-magic/homework/tests/test_demo_e2e_acceptance.py:80)

覆盖能力：
- 首页可访问
- 首次发任务请求时，AI 会先追问姓名和邮箱
- 用户资料与助手昵称可持久化
- 用户可通过自然语言创建并查询任务
- 搜索问题能触发外部搜索工具链路

面试时可以这样讲：
- “我先从网页入口进来，直接说创建任务，系统不会盲目执行，而是先完成用户建档。”
- “补完姓名邮箱后，再创建任务，任务会真正写入持久层并能查询出来。”
- “如果我问实时信息，Agent 会走搜索能力而不是假装知道最新情况。”

### 2. 文件工作区 + RAG 闭环

对应测试：
- [`test_demo_e2e_file_workspace_and_rag_flow`](/Users/kkk/kkk-magic/homework/tests/test_demo_e2e_acceptance.py:134)

覆盖能力：
- 文件上传
- 自动解析与向量化
- 文件列表查询
- 文件重命名
- 基于指定文件上下文的问答
- 删除文件后，向量检索结果同步消失

面试时可以这样讲：
- “上传的是一份简历/项目材料，系统会自动切块并写入向量库。”
- “随后我直接问‘总结这个文档’，回答会带文件引用，不是泛答。”
- “如果我删除文件，再继续问，系统不会再召回旧内容，这证明文件元数据和向量清理是联动的。”

### 3. 深度研究闭环

对应测试：
- [`test_demo_e2e_research_submit_and_poll`](/Users/kkk/kkk-magic/homework/tests/test_demo_e2e_acceptance.py:210)

覆盖能力：
- 研究任务提交
- 异步轮询
- 子任务推进
- 结构化报告输出

面试时可以这样讲：
- “复杂问题不会直接单轮回答，而是进入 research job。”
- “系统会先规划子任务，再执行搜索和证据汇总，最后输出结构化报告。”
- “这里我专门把‘子代理规划’写进最终报告，方便面试官看到 Agent 设计不是口头描述，而是产品行为的一部分。”

## 推荐现场展示顺序

建议把演示控制在 5 到 8 分钟，节奏会比较舒服：

1. 打开首页，先展示这是一个真实可访问的 Web 工作台。
2. 输入一句“帮我创建一个任务”，让系统先追问姓名和邮箱。
3. 补充“我叫小李，邮箱是 xiaoli@example.com，叫你阿塔”，展示用户建档和助手昵称。
4. 创建一个与作业高度相关的任务，例如“简历优化 / 面试作业 / RAG Demo”。
5. 上传一份简历或项目说明文件，马上问“总结这个文档”。
6. 发起一个研究型问题，例如“帮我调研 Cloudflare Worker 上实现 RAG 的轻量方案”。
7. 等待研究报告出现后，重点讲“子代理规划、检索证据、结构化输出”。

## 面试时最值得强调的点

- 这套 E2E 不是只测 happy path 的单接口，而是按真实用户操作顺序把整个链路串了起来。
- 测试用的是 HTTP 路由入口，离部署后的 Worker 运行方式很近，能证明不是单纯的内部函数自测。
- 文件删除后的“不可再召回”是一个很好的展示点，能体现你对 RAG 一致性和数据隔离的重视。
- 研究模式单独做成异步任务并可轮询，是比较符合 Worker 场景的工程选择，也容易让面试官看到架构意识。
