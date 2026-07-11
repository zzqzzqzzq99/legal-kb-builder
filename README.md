# legal-kb-builder

**本地法律知识库建设一体化工厂。**

从"一堆 PDF/DOCX/图片/Markdown/问答集法律资料"到"可对外服务的业务咨询智能体"，一个包搞定：

- 🔀 **双层路由**：先判"是不是 md（不是就交给你配置的解析后端）"，再判"该走书籍 KB / 裁判文书 KB / 问答集 KB / Agentic 实时检索 哪条流水线"。
- 🧩 **解析后端可插拔**：MinerU、阿里云百炼、合合信息 TextIn、PaddleOCR、LibreOffice、pandoc、任意自写脚本——你自己在 `assets/parser-backends.yaml` 里配。
- 🔎 **三路融合检索**：BM25（`jieba` + `rank_bm25`）+ 向量（`bge-small-zh-v1.5` + FAISS）+ 结构索引，用 RRF 融合。
- 💬 **问答集流水线**：支持 FAQ / 业务咨询问答 / 培训问答等问答形态语料，"问题匹配为主、答案召回为辅"双索引检索。
- 🤖 **业务咨询智能体**：跨库编排（意图分类→KB路由→多源检索→结构化回答），支持多轮对话。
- 🌐 **对外服务**：HTTP API（FastAPI）+ 钉钉/飞书 webhook + MCP Server，支撑前端问答平台和 IM 机器人。
- ⚖️ **面向法律语义**：区分"书的目录条文"与"正文引用条文"，避免把 69 条司法解释建成 489 条索引这类常见事故。
- 📦 **零平台绑定**：全部脚本自包含、路径全部相对，可以直接放到 Claude Code / Cursor / QoderWork / Gemini CLI / OpenCode 等任意 AI Agent 环境里当技能包使用。

## 快速开始

```bash
# 1) 依赖
python3 -m pip install -r requirements.txt

# 2) 配置解析后端（至少启用一个）
cp assets/parser-backends.example.yaml assets/parser-backends.yaml
# 打开 parser-backends.yaml，把你要用的后端 enabled 改为 true 并填 token/cmd

# 3) 一键构建（工厂入口自动路由 + 构建）
python3 scripts/kb_factory.py build ~/legal_materials/合同法FAQ.pdf \
    --output ~/kbs/faq_kb --name "合同法FAQ"

# 4) 对外提供服务
#    a) 命令行咨询
python3 scripts/consultation_agent.py --qa-kb ~/kbs/faq_kb ask "格式条款无效？"
#    b) HTTP API（前端/钉钉/飞书）
python3 scripts/api_server.py --qa-kb ~/kbs/faq_kb --port 8000
#    c) MCP（Claude Desktop / Cursor）
python3 scripts/mcp_server.py  # 配合 KB_PATH / QA_KB_PATH 环境变量
```

## 四条流水线 + 咨询智能体

| 类型 | 适用场景 | 主脚本 |
|---|---|---|
| **book_kb** | 法典评注 / 司法解释理解与适用 / 学术专著 / 教科书 / 案例汇编 / 法规汇编 / 实务指引 | `scripts/legal_kb.py` |
| **case_kb** | 法院裁判文书（判决书 / 裁定书 / 调解书 / 决定书） | `scripts/judgment_kb.py` |
| **qa_kb** | FAQ / 业务咨询问答 / 培训问答 / 客服话术 / 法律咨询问答集 | `scripts/qa_kb.py` |
| **agentic** | 探索性学术资料（论文 / 比较法 / 报告 / 单本随查） | `scripts/monte_carlo_sampler.py` |
| **consult** | 跨库业务咨询（意图分类→KB路由→多源检索→结构化回答） | `scripts/consultation_agent.py` |

细节请见 [SKILL.md](SKILL.md)。

## 目录

```
legal-kb-builder/
├── SKILL.md                  # 详细使用说明（AI Agent 也可直接读作 skill 定义）
├── README.md                 # 本文件
├── requirements.txt
├── scripts/                  # 全部可执行脚本
│   ├── kb_factory.py         # 工厂主入口（一键路由 + 构建）
│   ├── consultation_agent.py # 业务咨询智能体
│   ├── api_server.py         # HTTP API 服务（钉钉/飞书 webhook）
│   ├── mcp_server.py         # MCP 服务
│   └── ...                   # 四条流水线 + 检索引擎
├── assets/                   # 配置：解析后端 / 路由规则 / 词表 / 正则 / 问答 / 咨询
└── references/               # 深度文档（检索模式 / 索引模板 / 配置字段 / 端到端样例）
```

## 设计原则

1. **目录即锚**：书籍类知识库的一切都以书的真实目录为唯一依据。
2. **正文引用 ≠ 结构条目**：一本 69 条的司法解释书里，正文出现的"民法典第 584 条"是引用，不是本书条目。
3. **只纳入主文**：排除前言、序言、后记、致谢、脚注、出版信息。
4. **问题匹配为主**：问答集检索以"用户提问 ↔ 库内问题"的语义对齐为核心，答案召回为辅。
5. **零外部依赖**：把 API SDK 硬绑到工具里会把维护成本转嫁给下游；这里只做适配器，用户自己决定用什么后端。

## 许可

采用 **CC BY-NC-ND 4.0 + 6 附加条款** 双层许可：署名／非商业／禁改编 + 禁 AI 训练 / 禁上架收费平台 / 企业与行政机关识别为商用 / 学术引用格式 / 禁背书 / 权利保留。完整条款见 [LICENSE](LICENSE)。商业授权、企业部署授权、AI 训练豁免请联系作者：游初 &lt;994559732@qq.com&gt;。
