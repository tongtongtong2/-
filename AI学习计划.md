# AI应用开发 — 3个月学习计划

> 目标：从零到能独立开发AI应用（RAG + Agent + 本地部署）
> 每天投入：3小时（1h看 + 2h写）
> 开始日期：____年__月__日
> 预计完成：____年__月__日

---

## 前置自查

在学习开始前，确认以下能力：

- [ ] Python熟练（能独立写Flask/FastAPI接口）
- [ ] Linux命令行基础（ls/cd/grep/curl）
- [ ] Git基本操作（clone/commit/push）
- [ ] JSON/HTTP基础概念

如果某项不达标，先花1-2周补齐，否则后面会反复卡住。

---

## 第1-2周：LLM核心原理

### 学习目标
理解Transformer、Token、Embedding、Attention是什么，不要求手写。

### 必看视频

| 序号 | 视频 | 平台 | 时长 |
|------|------|------|------|
| 1 | 3Blue1Brown "直观理解Transformer" | YouTube/B站搬运 | 26min |
| 2 | 李宏毅 "Transformer详解" | B站搜"李宏毅 transformer" | 1h |
| 3 | Andrej Karpathy "Let's build GPT from scratch" | YouTube/B站搬运 | 2h |

### 必读博客

| 博客 | 链接 |
|------|------|
| Jay Alammar "The Illustrated Transformer" | jalammar.github.io/illustrated-transformer/ |
| Jay Alammar "How GPT Works" | jalammar.github.io/how-gpt3-works-visualizations-animations/ |
| Lilian Weng "Attention? Attention!" | lilianweng.github.io/posts/2018-06-24-attention/ |

### 动手
- [ ] 理解Tokenization：用tiktoken库切分中英文文本，对比token数量
- [ ] 理解Embedding：用openai embedding API把一段话转成向量，算两个句子的余弦相似度

---

## 第3-4周：API调用 + Prompt基础

### 学习目标
熟练调用LLM API，掌握system prompt设计，理解function calling。

### 必看视频

| 序号 | 视频 | 平台 | 时长 |
|------|------|------|------|
| 1 | 吴恩达 "ChatGPT Prompt Engineering for Developers" | B站搜"吴恩达 prompt engineering" | 1.5h |
| 2 | OpenAI官方 "Function Calling Tutorial" | YouTube搜 openai function calling | 30min |
| 3 | Anthropic "Tool Use with Claude" | YouTube搜 anthropic tool use | 20min |

### 必读

| 资源 | 链接 |
|------|------|
| OpenAI API文档 | platform.openai.com/docs |
| Anthropic API文档 | docs.anthropic.com |
| OpenAI Cookbook | github.com/openai/openai-cookbook |
| Anthropic Cookbook | github.com/anthropics/anthropic-cookbook |

### 动手项目

- [ ] **项目1：命令行聊天机器人**
  - Python脚本，支持多轮对话
  - 用argparse切换模型（gpt-4o / claude-sonnet）
  - 支持流式输出

- [ ] **项目2：PDF智能摘要工具**
  - 输入PDF文件路径
  - 提取文本 → 调用LLM → 输出200字摘要 + 3个关键点
  - 支持批量处理一个文件夹

- [ ] **项目3：结构化信息提取**
  - 输入一段自由文本（新闻/简历/合同）
  - 输出固定JSON格式（如姓名/日期/金额）
  - 使用function calling或JSON mode

---

## 第5-6周：RAG — 检索增强生成

### 学习目标
搭建完整的RAG系统：文档加载 → 切分 → 向量化 → 检索 → 生成。

### 必看视频

| 序号 | 视频 | 平台 | 时长 |
|------|------|------|------|
| 1 | LangChain RAG实战 | B站搜 "LangChain RAG" | 系列教程 |
| 2 | LlamaIndex入门 | YouTube搜 "LlamaIndex tutorial" | 1h |
| 3 | Jerry Liu "Building Advanced RAG" | YouTube搜 jerry liu rag | 40min |

### 必读

| 资源 | 链接 |
|------|------|
| LlamaIndex文档 | docs.llamaindex.ai |
| LangChain RAG教程 | python.langchain.com/docs/tutorials/rag/ |
| Lilian Weng "Building RAG" | lilianweng.github.io/posts/2023-06-23-agent/ |
| Pinecone RAG指南 | pinecone.io/learn/series/rag/ |

### 动手项目

- [ ] **项目4：个人知识库问答**
  - 收集50+篇你感兴趣的文章/文档
  - 用ChromaDB做向量存储
  - 实现多轮对话问答
  - 对比不同chunk size（256/512/1024）对答案质量的影响

- [ ] **项目5：RAG增强版**
  - 加上reranking（Cohere rerank或bge-reranker）
  - 加上HyDE（生成假设文档再检索）
  - 对比三个版本：基础RAG / RAG+rerank / RAG+HyDE

---

## 第7-8周：AI Agent开发

### 学习目标
理解Agent的ReAct模式，掌握tool定义和多Agent编排。

### 必看视频

| 序号 | 视频 | 平台 | 时长 |
|------|------|------|------|
| 1 | LangGraph入门到实战 | B站搜 "LangGraph" | 系列教程 |
| 2 | CrewAI多Agent实战 | B站搜 "CrewAI" | 系列教程 |
| 3 | Anthropic "Building Effective Agents" | 看博客即可 | - |

### 必读

| 资源 | 链接 |
|------|------|
| Anthropic "Building effective agents" | anthropic.com/engineering/building-effective-agents |
| LangGraph文档 | langchain-ai.github.io/langgraph/ |
| CrewAI文档 | docs.crewai.com |
| Lilian Weng "LLM Powered Autonomous Agents" | lilianweng.github.io/posts/2023-06-23-agent/ |

### 动手项目

- [ ] **项目6：自动研究Agent**
  - 输入一个主题 → Agent自动搜索网页 → 阅读 → 整理 → 输出研究报告
  - 使用LangGraph实现ReAct循环
  - Tool至少包含：搜索、读网页、写文件

- [ ] **项目7：数据分析Agent**
  - 上传CSV文件 → Agent理解数据 → 写Python代码 → 执行 → 画图 → 输出结论
  - 安全性：代码在sandbox中执行
  - 支持中文提问

---

## 第9-10周：模型部署与优化

### 学习目标
掌握本地模型部署，理解量化和推理优化。

### 必看视频

| 序号 | 视频 | 平台 | 时长 |
|------|------|------|------|
| 1 | Ollama快速入门 | YouTube搜 "Ollama tutorial" | 30min |
| 2 | llama.cpp实战 | YouTube搜 "llama.cpp setup" | 40min |
| 3 | vLLM部署指南 | YouTube搜 "vLLM deployment" | 1h |

### 必读

| 资源 | 链接 |
|------|------|
| Ollama官网 | ollama.com |
| llama.cpp GitHub | github.com/ggml-org/llama.cpp |
| vLLM文档 | docs.vllm.ai |
| HuggingFace GGUF指南 | huggingface.co/docs/hub/gguf-llamacpp |

### 动手

- [ ] 用Ollama在本地跑qwen2.5或deepseek-coder，对比API调用的成本
- [ ] 用llama.cpp部署一个GGUF量化模型，调Q4/Q5/Q6对比质量
- [ ] 用vLLM部署一个OpenAI兼容API服务，做并发压测

---

## 第11-12周：综合项目

### 以下三个方向选一个做深入：

---

### 方向A：AI股票分析助手（结合你的量化背景）
**功能：**
- 爬取财经新闻/公告 → RAG向量化存储
- Agent分析：MACD信号 + 新闻面 + 基本面
- 输出：每日扫描报告 + 个股深度分析
- 前端：Gradio或Streamlit

**技术栈：** FastAPI + LangChain/LangGraph + ChromaDB + Ollama本地模型

---

### 方向B：企业内部知识库Agent
**功能：**
- 上传公司文档（PDF/Word/网页）
- 自动切分、向量化
- 多轮对话问答 + 来源引用
- 对话历史管理 + 用户认证

**技术栈：** FastAPI + LlamaIndex + Milvus + Vue前端

---

### 方向C：通用AI Agent平台
**功能：**
- 可视化定义Agent workflow
- 插件式tool系统
- 支持多个LLM provider切换
- 执行日志 + Token统计

**技术栈：** Next.js + Python后端 + LangGraph + MCP协议

---

## 每日时间表（建议）

| 时间 | 做什么 |
|------|--------|
| 20:00 - 21:00 | 看视频/读博客（输入） |
| 21:00 - 23:00 | 写代码/做项目（输出） |
| 周末半天 | 综合项目推进 |

## 每周检查节点

| 周次 | 检查点 |
|------|--------|
| 第2周末 | 能解释Transformer的前向传播过程 |
| 第4周末 | 三个动手小项目全部完成并能演示 |
| 第6周末 | RAG项目能跑起来，检索质量可用 |
| 第8周末 | Agent能自主完成多步任务 |
| 第10周末 | 本地模型部署成功，API服务可调用 |
| 第12周末 | 综合项目上线，可以demo给面试官看 |

---

## 避坑指南

1. **别只看不写** — 看100个视频不如写1个项目，这行面试看代码不看播放记录
2. **别追新模型** — 每周都有新模型发布，追不过来。学的是架构和思路
3. **别从论文开始** — 论文是给研究员看的。先看博客/视频理解概念，需要深入再翻论文
4. **别死磕原理** — Transformer细节不理解没关系，做几个项目后回来看会豁然开朗
5. **中文资源优先李沐、李宏毅、Datawhale** — 质量高且没翻译损耗
6. **遇到问题先搜GitHub Issues和Stack Overflow** — 不是先问ChatGPT

---

## 资源速查

### B站UP主
- 李沐 ("跟李沐学AI") — 论文精读 + DL原理
- 李宏毅 — ML/DL课程
- Datawhale — AI学习社区，资料全面
- 宝玉说AI — AI资讯（公众号同名）

### YouTube频道
- Andrej Karpathy — 必看
- 3Blue1Brown — 数学可视化
- LangChain — 框架官方
- LlamaIndex — 框架官方
- Anthropic — Agent/Prompt最佳实践

### 必读书签
- lilianweng.github.io — LLM Agent/RAG最好的博客
- github.com/openai/openai-cookbook
- github.com/anthropics/anthropic-cookbook
- anthropic.com/engineering
- platform.openai.com/docs

---

> 最后一句：AI开发这行，3个月能入门，1年能独当一面。关键不是学了多少，是做了多少项目。从今天开始，别等"准备好"——第1天就动手写代码。
