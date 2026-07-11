---
name: legal-kb-builder
description: "构建本地法律知识库。Use when 需要把 PDF/DOCX/图片/Markdown/问答集等法律语料转化为可检索的知识库，支持书籍评注、裁判文书、问答集、Agentic 实时检索四条流水线，混合检索(BM25+向量+GraphRAG)+Cross-Encoder 重排。默认产出本地 skill 供当前 agent 调用；用户主动要求时可进一步做成 HTTP API/MCP/云端托管智能体。"
metadata:
  clawdbot:
    emoji: ⚖️
    requires:
      anyBins:
        - python3
---

# legal-kb-builder — 本地法律知识库建设工厂

> **核心定位**：把法律语料转化为**本地可检索的知识库**，并安装为**本地 skill** 供当前 agent 直接调用。云端托管和对外服务是**可选扩展**——仅当用户主动要求时才进行。

## When to Use

- **构建法律知识库**：用户有一批 PDF/DOCX/图片/Markdown 法律资料，想转化为可检索的知识库
- **裁判文书管理**：需要批量导入裁判文书，按案号/法院/案由/争议焦点结构化检索
- **问答集/FAQ 建设**：有法律问答集（显式 Q/A、编号、Markdown 标题、表格、JSON 等格式），想做成可检索的问答库
- **法条检索增强**：需要"第X条"精确检索 + 语义检索 + 法条关联图谱多跳查询
- **Agentic 实时检索**：不想预建索引，靠 Grep + 蒙特卡洛采样做实时检索
- **RAG 质量评估**：需要用 hit_rate/MRR/Recall + RAGAS 指标量化评估检索质量
- **（可选）对外服务**：用户主动要求时，可进一步做成 HTTP API / MCP / 钉钉飞书 / 云端托管智能体

## 0 · 任务开始前的交互式引导（每次必做！）

> **每次执行本 skill 时，必须先向用户确认以下问题，再开始构建。**
> 可用 `python3 scripts/onboard.py --scan` 自动探测本地环境，减少用户手动回答。

### Q1: 文档解析工具（处理非 md 文件时必须）

运行 `python3 scripts/onboard.py --scan` 探测本地已安装的解析工具。探测到的工具直接询问用户选哪个；未探测到时向用户推荐安装选项：

| 工具 | 安装方式 | 支持格式 |
|------|---------|---------|
| MinerU | `npm install -g mineru-open-api`（需 MINERU_TOKEN） | PDF/图片/Word/PPT/Excel |
| PaddleOCR | `pip install paddleocr` | 图片/PDF |
| 合合信息 TextIn | 配置 TEXTIN_API_KEY | PDF/图片/Word |
| 阿里云百炼 | `npm install -g bailian-cli` + `bl auth login` | PDF/图片/Word |
| LibreOffice | `brew install libreoffice`（macOS） | DOCX/PPTX/XLSX |
| pandoc | `brew install pandoc` | DOCX/HTML/EPUB |

> 若用户输入已是 md/txt 格式，可跳过此步。

### Q2: 知识库类型（路由方案）

询问用户的语料是什么类型，据此选择流水线：

| 选项 | 流水线 | 适用语料 |
|------|--------|---------|
| 1 | `book_kb` | 法典评注/司法解释/学术专著/教科书/法规汇编 |
| 2 | `case_kb` | 裁判文书（判决书/裁定书/调解书） |
| 3 | `qa_kb` | 问答集/FAQ/法律咨询问答 |
| 4 | `agentic` | 不预建索引，实时 Grep + 蒙特卡洛采样 |
| 5 | 混合 | 多种类型语料，由 `material_router.py` 自动分发 |

### Q3: 部署形态（决定任务终止点）

| 选项 | 形态 | 任务终止点 |
|------|------|-----------|
| **1（默认）** | **本地 skill** | 构建知识库 → 安装为本地 skill → **结束** |
| 2 | 本地服务 | 构建知识库 → 启动 HTTP API / MCP → 供其他程序调用 |
| 3 | 云端托管 | 构建知识库 → 部署到 Qoder / 百炼 → 获取公网 API |

> **默认选 1**。仅当用户主动要求对外服务时才选 2 或 3。

### Q4: 云端平台（仅当 Q3 选 3 时）

| 选项 | 平台 | 是否需要服务器 |
|------|------|--------------|
| 1 | Qoder Cloud Agents | 不需要（全托管） |
| 2 | 阿里云百炼 | mcp/api 模式需要 |

### Q5: 最终服务形态（仅当 Q3 选 2 或 3 时）

| 选项 | 形态 | 说明 |
|------|------|------|
| 1 | HTTP API | 供网站/小程序/App 后端调用 |
| 2 | MCP 服务 | 供 Claude Desktop/Cursor 等 MCP 客户端调用 |
| 3 | 钉钉机器人 | 钉钉群 webhook |
| 4 | 飞书机器人 | 飞书应用 webhook |

### 引导流程图

```text
任务开始
  │
  ├─ Q1: 解析工具（onboard.py --scan 探测 + 用户确认）
  ├─ Q2: 知识库类型（book/case/qa/agentic/混合）
  ├─ Q3: 部署形态 ← 默认选 1（本地 skill）
  │    ├─ 选 1 → 构建知识库 → 安装本地 skill → 结束
  │    ├─ 选 2 → Q5: 服务形态 → 构建服务 → 结束
  │    └─ 选 3 → Q4: 云端平台 → Q5: 服务形态 → 部署 → 结束
  │
  └─ 开始构建
```

## 0.1 · 使用前先看这三件事

1. **本工具不带任何在线文档解析 API**。要处理 PDF/DOCX/图片等非 md 文件，你必须先在 `assets/parser-backends.yaml` 里配置至少一个后端（MinerU、阿里云百炼、合合信息 TextIn、PaddleOCR、LibreOffice、pandoc，或自写脚本任选其一），本工具只负责按顺序调用它们、并在失败时降级。
2. **本工具最看重"目录即锚"**。做书籍/评注类知识库时，索引必须以书的真实目录（Table of Contents）为唯一依据；正文中出现的"参见第X条"是引用，不是结构条目。
3. **本工具产出的是"知识库 + 检索脚本"**，不是一个搜索服务。构建出的 `_知识库索引.json`、`_vectors.faiss`、`_bm25_corpus.json` 可以直接用 `scripts/hybrid_search.py` 或你自己的下游程序检索。

## 1 · 目录结构

```text
legal-kb-builder/
├── SKILL.md                        # 本文件
├── README.md                       # 面向发布分发的介绍（可选）
├── requirements.txt                # 必需依赖（PyYAML + pypdf + jieba + rank-bm25 + numpy）
├── requirements-vector.txt         # 可选：向量检索 + Cross-Encoder 重排（含 torch）
├── requirements-graph.txt          # 可选：GraphRAG 法条关联图谱（networkx）
├── requirements-api.txt            # 可选：HTTP API 服务（fastapi/uvicorn）
├── requirements-mcp.txt            # 可选：MCP 服务（mcp）
├── requirements-eval.txt           # 可选：RAGAS 评估（ragas/datasets）
├── requirements-all.txt            # 一键全部安装（引用以上所有）
│
├── scripts/                        # 全部可执行脚本（自包含，路径全部相对）
│   ├── format_detector.py          # ① 格式路由：md 直通 / 需要解析
│   ├── parser_adapter.py           # ② 解析后端适配器（读 parser-backends.yaml）
│   ├── material_router.py          # ③ 数据源路由：book_kb / case_kb / qa_kb / agentic / direct
│   │
│   ├── legal_kb.py                 # 【流水线 A】结构化书籍 KB 主入口
│   ├── split_pdf.py                #   PDF 拆分（书签/手动/自动 三模式）
│   ├── merge_md.py                 #   合并 + 边界去重
│   ├── quality_checker.py          #   OCR 质量校验
│   ├── text_cleaner.py             #   OCR 纠错 + 法律文本规范化
│   ├── enhanced_index.py           #   目录驱动索引
│   ├── hybrid_search.py            #   四路融合检索 + Cross-Encoder 重排（RRF + Rerank + GraphRAG）
│   ├── bm25_searcher.py            #   jieba 分词 + BM25Okapi
│   ├── embedding_manager.py        #   多模型可配置嵌入 + FAISS（bge-small/large/m3）+ 父子分块
│   ├── reranker.py                 #   Cross-Encoder 重排（bge-reranker-v2-m3，可选依赖）
│   ├── graph_rag.py                #   GraphRAG 法条关联图谱（多跳检索，可选依赖 networkx）
│   ├── query_rewriter.py           #   查询改写（规范化+同义词扩展+指代消解+子问题拆解）
│   │
│   ├── judgment_kb.py              # 【流水线 B】裁判文书 KB 主入口
│   ├── judgment_parser.py          #   案号/当事人/事实/说理/判决 要素抽取
│   │
│   ├── qa_parser.py                # 【流水线 D】问答对解析器（显式/编号/Markdown/表格/JSON/启发式）
│   ├── qa_kb.py                    #   问答集 KB 主入口（问题匹配为主、答案召回为辅）
│   │
│   ├── monte_carlo_sampler.py      # 【流水线 C】Agentic 实时检索：EXPLORATION→EXPLOITATION→SYNTHESIS
│   ├── knowledge_clusters.py       #   跨会话集群缓存
│   ├── session_tracker.py          #   查询历史与 FAST/DEEP 建议
│   ├── scan_library.py             #   文献库结构预扫描
│   │
│   ├── consultation_agent.py       # 【咨询智能体】跨库编排：意图分类→KB 路由→多源检索→结构化回答
│   ├── api_server.py               # 【HTTP API】FastAPI 服务（/ask + 钉钉/飞书 webhook）
│   ├── kb_factory.py               # 【工厂主入口】一键路由 + 构建任意语料到最适合的知识库
│   ├── mcp_server.py               # 【MCP 服务】把检索与咨询能力暴露给 MCP 客户端
│   ├── onboard.py                 #   ★ 环境探测+交互式引导（任务开始时先运行）
│   ├── install_deps.py             #   依赖安装助手（按场景选择，交互式/CLI）
│   ├── deploy_agent.py             #   云端部署助手（Qoder Cloud Agents / 阿里云百炼）
│   └── shared_utils.py             #   共用工具（配置加载、同义词、日志）
│
├── assets/
│   ├── parser-backends.example.yaml   # ★ 复制为 parser-backends.yaml 后填写
│   ├── routing-rules.yaml             # 数据源路由规则（含问答集识别）
│   ├── config-template.yaml           # 拆分/合并/清洗一体化配置
│   ├── legal-corrections.yaml         # 法律文本纠错规则
│   ├── ocr-corrections.yaml           # OCR 常见错字规则
│   ├── keyword-expansion.yaml         # 同义词表（BM25 + Agentic 共用）
│   ├── element-patterns.yaml          # 裁判文书要素抽取正则
│   ├── judgment-fields.yaml           # 裁判文书字段与嵌入权重
│   ├── qa-patterns.yaml               # 问答对抽取规则（六种格式）
│   ├── qa-fields.yaml                 # 问答字段与嵌入权重
│   ├── consultation-config.yaml       # 咨询智能体配置（意图/路由/模板/对话）
│   └── deploy-backends.example.yaml   # ★ 云端部署配置模板（Qoder/百炼）
│
└── references/                     # 深度说明文档，需要时按需读取
    ├── retrieval-guide.md
    ├── search-patterns.md
    ├── config-reference.md
    ├── examples.md                 # 端到端样例（书籍库/裁判库/问答库/咨询/钉钉接入）
    └── deploy-guide.md             # 云端部署指南（Qoder Cloud Agents / 阿里云百炼）

eval/                               # RAG 评估框架（hit_rate/mrr/recall + 可选 RAGAS 五指标）
├── eval_rag.py                     #   评估脚本
├── legal_qa_eval.jsonl             #   20 条法律领域标注样本
└── README.md                       #   使用说明
```

## 2 · 快速开始

```bash
# 1. 装依赖（按需选择，不要全装！详见 §15）
#    最小安装（仅格式路由 + Grep）：
python3 -m pip install -r requirements.txt
#    推荐安装（书籍知识库 + 向量检索 + 重排 + GraphRAG + 评估）：
python3 -m pip install -r requirements.txt -r requirements-vector.txt -r requirements-graph.txt -r requirements-eval.txt
#    或用交互式安装助手：
python3 scripts/install_deps.py

# 2. 配置解析后端（至少启用一个）
cp assets/parser-backends.example.yaml assets/parser-backends.yaml
$EDITOR assets/parser-backends.yaml    # 打开你想启用的后端，改 enabled: true

# 3. 检测输入格式（可选，主要用来观察）
python3 scripts/format_detector.py ~/legal_books/民法典评注.pdf

# 4. 一键路由：告诉工具"我有这样一批材料"，它会自己决定该走哪条流水线
python3 scripts/material_router.py ~/legal_books/民法典评注.pdf
#   → target_skill: book_kb / case_kb / agentic / direct
#   → 后面按对应流水线继续
```

## 3 · 顶层双层路由

**每次运行必然依次经过两道路由**：

```text
      ┌────────────────────────┐
      │  用户输入：一个文件或   │
      │  一个目录               │
      └───────────┬─────────────┘
                  │
     ┌────────────▼────────────┐
     │ 第 1 层：格式路由        │  ← scripts/format_detector.py
     │ 是 .md/.txt 吗？         │
     └────┬───────────────┬─────┘
       是 │            否 │
          │               │
          │     ┌─────────▼───────────┐
          │     │ 解析后端适配器       │  ← scripts/parser_adapter.py
          │     │ 按 default_order 依  │     依据 assets/parser-backends.yaml
          │     │ 次尝试 MinerU / 百   │     的顺序：MinerU → 百炼 → 合合 →
          │     │ 炼 / 合合 / PaddleOCR│     PaddleOCR → LibreOffice → pandoc
          │     │ / LibreOffice / …    │     → 兜底直通
          │     │ 任一成功即返回 md    │
          │     └─────────┬────────────┘
          │               │
     ┌────▼───────────────▼────┐
     │ 第 2 层：数据源路由      │  ← scripts/material_router.py
     │ 分析样本内容，判断类型   │     规则：assets/routing-rules.yaml
     └──┬──────┬──────┬──────┬─┘
        │      │      │      │
   book_kb case_kb qa_kb agentic  direct
        │      │      │      │     └─ 方法论文档 → references/ 直接落盘
   ┌────▼──┐┌──▼───┐┌─▼───┐┌─▼──────────┐
   │流水线A││流水线B││流水线D││流水线C     │
   │结构化 ││裁判  ││问答集││Agentic实时│
   │书籍   ││文书  ││     ││           │
   └───┬───┘└──┬──┘└──┬──┘└─────┬─────┘
       │       │      │          │
       └───────┴──────┴──────────┘
                  │
     ┌────────────▼────────────┐
     │ 业务咨询智能体           │  ← scripts/consultation_agent.py
     │ 意图分类→KB路由→多源检索 │     配置：assets/consultation-config.yaml
     │ →证据融合→结构化回答     │
     └────────────┬────────────┘
                  │
     ┌────────────▼────────────┐
     │ 对外服务层               │
     │  • HTTP API (api_server) │  ← /ask + 钉钉/飞书 webhook
     │  • MCP Server            │  ← consult / qa_search 工具
     │  • CLI 直接调用           │
     └─────────────────────────┘
```

## 4 · 核心原则（做任何流水线前先内化）

> **目录即锚**：任何书籍类知识库的组织结构、索引编写和检索方案，一律以书的真实目录为唯一依据。绝不能通过扫描正文中出现的条文编号来生成索引。
>
> **正文中的引用 ≠ 书的结构条目**：一本讲解 69 条司法解释的书，正文里可能引用了数百个民法典条文——这些引用不是书的组织单元。
>
> **只纳入主文**：知识库只收录书籍的正文章节。前言、序言、后记、致谢、脚注/尾注、出版信息一律排除。

## 5 · 流水线 A — 结构化书籍 KB（`book_kb`）

适用于：**法典评注 / 司法解释理解与适用 / 学术专著 / 教科书 / 案例汇编 / 法规汇编 / 实务指引**。

### 5.1 阶段零 — 书籍类型识别（最关键！）

在做任何拆分和索引之前，**必须先理解这本书的组织逻辑**。按优先级提取目录：

1. PDF 书签：`python scripts/split_pdf.py <input.pdf> --mode bookmark --dry-run`
2. 前 20 页转换后找"目录/Contents"
3. 全书转换后前 300 行

提取出的目录先保存为 `_目录_原始.md`，作为后续所有索引工作的唯一基础。

| 书籍类型 | 目录特征 | 组织单元 | 索引键 |
|---|---|---|---|
| 法典评注类 | 目录以"第X条"为主线 | 被评注法律的条文号 | 条文号 → 文件+位置 |
| 司法解释适用类 | 目录以本司法解释的条文号（几十条）为主线 | **司法解释自身的条文号**（**注意：不是被引用的其他法律条文！**） | 司法解释条文号 → 文件+位置 |
| 专著类 | 目录以章/节为主线，学术逻辑组织 | 章节编号 | 章节 → 文件+位置 |
| 教科书类 | 编→章→节→目 层级 | 编章节目 | 层级路径 → 文件+位置 |
| 案例汇编类 | 目录以案例名/案由/专题为主线 | 案例 | 案例名/案号 → 文件+位置 |
| 法规汇编类 | 目录列多部法律名 | 法律法规名 | 法律名 → 文件+位置 |
| 实务指引类 | 目录按流程/问题分类 | 专题/问题 | 专题名 → 文件+位置 |

**识别方法**：读取目录，回答三个问题——目录主要条目是什么？条目关系是顺序/层级/并列？书名与前言有没有明确说明组织方式？

### 5.2 阶段一 — PDF 拆分（防信息丢失版）

> **MinerU 当前单文件上限为 200 页**（2026-07 确认，原为 600）。
> `split_pdf.py` 默认 `--max-pages 200`，`parser_adapter.py` 检测到超过此限制时自动分片。
> 各后端的页数限制可在 `parser-backends.yaml` 的 `max_pages` 字段覆盖。

```bash
# 三种模式，按优先级选用
python scripts/split_pdf.py book.pdf -o splits/ --mode bookmark --level 1      # 首选：按 PDF 书签
python scripts/split_pdf.py book.pdf -o splits/ --mode manual --config c.yaml  # 备选：手动指定
python scripts/split_pdf.py book.pdf -o splits/ --mode auto                    # 兜底：等分

# 粒度控制（默认 150 页/块 + 3 页重叠，留余量低于 200 页上限）
python scripts/split_pdf.py book.pdf -o splits/ --chunk-size 150 --overlap 3

# 若后端限制有变动，可手动指定上限
python scripts/split_pdf.py book.pdf -o splits/ --max-pages 100   # 更保守
```

**大文件自动分片**：若直接调用 `parser_adapter.py` 解析一个超过 200 页的 PDF，它会自动：
1. 调用 `split_pdf.py` 按 200 页拆分（带 3 页重叠）
2. 逐片调用解析后端
3. 合并所有片的 md 输出
4. 若某片仍失败，自动缩小到 100 页重试，最多降级 2 次

**拆分策略配合阶段零结果**：

- 法典评注 / 司法解释适用：让每个分卷对应一组连续条文；分卷边界不切断同一条文。
- 专著：按章分卷；单章超过后端页数限制时在节边界拆分。
- 案例汇编：按案例数量均分，分卷边界不切断单个案例。

输出：`output_dir/` 下编号 PDF + `split_manifest.json`（含重叠信息）。

### 5.3 阶段二 — 转换为 Markdown

**通过 `parser_adapter.py` 调用你配置的后端**：

```bash
# 单文件
python scripts/parser_adapter.py splits/part_001.pdf -o splits_md/

# 或先测试一下会用哪个后端
python scripts/parser_adapter.py splits/part_001.pdf --dry-run

# 强制换某个后端
python scripts/parser_adapter.py splits/part_001.pdf --backends aliyun-bailian,paddleocr
```

`parser-backends.yaml` 里列出的后端会**按 default_order 顺序尝试**，失败自动降级到下一个；`enabled: false` 会跳过。逐个文件调用可以避免超时。

### 5.4 阶段三 — 质量校验

```bash
python scripts/quality_checker.py splits_md/
```

检查 OCR 置信度、章节连续性、引用完整性、重复段落、法律格式；集成 `text_cleaner.py` 的 `detect_issues()` 做深度评估。

### 5.5 阶段四 — 合并入库（边界去重版）

```bash
python scripts/merge_md.py splits_md/ -o kb_dir/ \
    --name "民法典评注" \
    --manifest splits/split_manifest.json \
    --legal --clean
```

`--clean` 触发 `text_cleaner.py` 的 8 步清洗：OCR 纠错 → 页眉页脚 → 页码 → 脚注分离 → 空白规范化 → 表格重建 → 重复段落去除 → 法律文本规范化。

`--manifest` 让 `merge_md.py` 读取拆分清单中的重叠页信息，用文本相似度自动去重（阈值 60%）。

输出结构：
```text
kb_dir/
├── _知识库索引.json      # 机器可读索引（草稿）
├── _目录.md              # 人可读目录
├── 第一部分_总则.md
├── 第二部分_物权.md
└── ...
```

### 5.6 阶段五 — 目录驱动索引编写（最容易出错！）

`merge_md.py` 生成的 `_知识库索引.json` **只是草稿**，必须人工审核：

**索引编写四步法**：

1. **从目录出发**：打开 `_目录.md`，逐项核对索引是否一一对应。
2. **数量一致性校验**：
   - 法典评注类：索引条文数 = 被评注法律的总条文数
   - 司法解释适用类：索引条文数 = 司法解释总条文数（如 69 条，**不是** 489 条！）
   - 专著类：索引章节数 = 目录章节数
   - 案例汇编类：索引案例数 = 目录案例数
3. **随机抽样验证**：抽 3–5 个条目，用 Grep 在对应 MD 文件中确认位置。
4. **手工编写 `topic_index`**：覆盖核心概念 → 组织单元编号。

七种书籍类型的索引 JSON 模板参见 [references/retrieval-guide.md](references/retrieval-guide.md)。

### 5.7 阶段六 — 构建三路融合检索索引

```bash
python scripts/legal_kb.py build-search-index [--book 书名]
```

一次性生成：

- **BM25 索引**：jieba 中文分词 + `rank_bm25`，同义词扩展来自 `assets/keyword-expansion.yaml`
- **向量索引**：嵌入模型（默认 `bge-small-zh-v1.5` 384维，可切换 `bge-large-zh-v1.5` / `bge-m3` 1024维），FAISS 存储
- **结构索引**：即前面写好的 `_知识库索引.json`

**切换嵌入模型**（模型变更后需重建索引）：

```bash
# 用 bge-m3（2025 前沿，多语言+多粒度，语义召回 +15%）
python scripts/embedding_manager.py build kb_dir/ --model BAAI/bge-m3

# 查看可用模型
python scripts/embedding_manager.py --models
```

产物：
```text
kb_dir/
├── _vectors.faiss
├── _chunks.json          # 含 model 和 dim 字段，加载时自动校验一致性
├── _bm25_corpus.json
├── _知识库索引.json
├── _目录.md
└── 第X部分_物权.md
```

### 5.8 阶段七 — 四路融合检索 + Cross-Encoder 重排 + 父子分块（RRF + Rerank + GraphRAG）

```text
查询 → [查询改写] → [索引查找] + [BM25 关键词] + [向量语义] + [GraphRAG 图谱] → RRF 融合 → Cross-Encoder 重排 → Top-K 结果
```

- **查询改写（v2.2）**：口语→书面语规范化 + 同义词扩展 + 指代消解 + 子问题拆解（LLM 模式）
- **路径 A — 索引查找**：`topic_index` / 条文号精确匹配
- **路径 B — BM25**：jieba 分词 + 同义词扩展 + BM25Okapi
- **路径 C — 向量**：嵌入模型 + FAISS 余弦相似度（支持父子分块：小块检索+大块上下文）
- **路径 D — GraphRAG（v2.2）**：法条关联图谱多跳检索（法条→案例→法条）
- **融合公式**：`score(d) = Σ 1/(60 + rank_i(d))`（对每个路径 i）
- **重排（v2.1）**：RRF 融合后取 Top-30 候选，用 `bge-reranker-v2-m3` Cross-Encoder 精排到 Top-5（+20% 精度）。可选依赖，未安装时降级为纯 RRF

**父子分块（v2.2，推荐生产环境）**：

```bash
# 用 parent_child 策略构建索引（小块256检索 + 大块1024上下文）
python scripts/embedding_manager.py build kb_dir/ --strategy parent_child
```

**GraphRAG 法条关联图谱（v2.2）**：

```bash
# 构建图谱（从法律文本抽取法条/案例/法律名实体）
python scripts/graph_rag.py build kb_dir/

# 多跳查询
python scripts/graph_rag.py search kb_dir/ "第311条"
```

调用：

```bash
python scripts/hybrid_search.py --kb kb_dir/ --query "格式条款的效力认定"
```

## 6 · 流水线 B — 裁判文书 KB（`case_kb`）

裁判文书有固定结构（**案号 → 当事人 → 事实 → 说理 → 判决**），因此不做全文分块，而是"要素抽取 + 字段级嵌入"。

### 6.1 要素抽取字段

| 字段 | 说明 |
|---|---|
| `case_number` | 案号，如 `(2023)京0108民初12345号` |
| `court` | 审理法院 |
| `procedure` | 一审 / 二审 / 再审 |
| `document_type` | 判决书 / 裁定书 / 调解书 / 决定书 |
| `parties` | 原告 / 被告 / 第三人（含代理人） |
| `cause_of_action` | 案由 |
| `claims` | 诉讼请求 |
| `found_facts` | 经审理查明段落 |
| `court_reasoning` | 本院认为段落 —— **最有价值** |
| `judgment_result` | 判决如下段落 |
| `applied_laws` | 引用的法律条文 |
| `dispute_focus` | 争议焦点 |

抽取模式定义在 `assets/element-patterns.yaml`，字段权重在 `assets/judgment-fields.yaml`。

### 6.2 全流程命令

```bash
# 初始化
python scripts/judgment_kb.py --kb ./case_kb init --name "合同纠纷案例库"

# 单文书导入（PDF 请先 parser_adapter 转 md）
python scripts/judgment_kb.py --kb ./case_kb add judgment.md

# 批量导入
python scripts/judgment_kb.py --kb ./case_kb batch ./judgments_md/

# 构建索引（BM25 + FAISS + 元数据 JSON）
python scripts/judgment_kb.py --kb ./case_kb rebuild

# 三种检索
python scripts/judgment_kb.py --kb ./case_kb search --case "(2023)京0108民初12345号"
python scripts/judgment_kb.py --kb ./case_kb search --cause "买卖合同纠纷"
python scripts/judgment_kb.py --kb ./case_kb search --query "违约金调整标准"

# 统计
python scripts/judgment_kb.py --kb ./case_kb stats
```

### 6.3 存储结构

```text
case_kb/
├── config.yaml
├── judgments/                    # 每份文书一个 JSON
│   ├── (2023)京0108民初12345号.json
│   └── ...
├── indices/
│   ├── metadata.json             # 结构化字段索引（案号/法院/当事人/适用法律）
│   ├── _bm25_corpus.json         # BM25 语料 + tokenized（rank-bm25 后端）
│   ├── _vectors.faiss            # FAISS 向量索引
│   └── _chunks.json              # 向量 chunk 元数据（chunk_id ↔ 文书 stem）
└── cache/
```

## 7 · 流水线 C — Agentic 实时检索（`agentic`）

**没有预建索引，没有向量数据库**——把 PDF 转成 md 缓存后，AI Agent/本地脚本自己就是检索代理。

灵感来自 Sirchmunk 的 Indexless Retrieval，但只用本工具即可跑通。

### 7.1 两种模式

- **FAST**（默认）：检查集群缓存 → 命中直接返回 / 未命中做单轮 Grep；目标 < 5 秒，2 次工具调用。
- **DEEP**：三阶段蒙特卡洛采样；目标 10–30 秒，5–10 次工具调用。用户明说"详细/全面/深度"，或 `session_tracker` 建议时启用。

### 7.2 缓存目录结构

```text
~/legal_books/
├── 王泽鉴_损害赔偿.pdf
└── .agentic_cache/
    ├── 王泽鉴_损害赔偿/
    │   ├── _book_type.txt        # 首次分析出的书籍类型，避免重复
    │   ├── 第一章_概述.md
    │   └── ...
    └── _clusters/                # 跨会话集群缓存（Knowledge Cluster Store）
        ├── clusters.json
        └── ...
```

删除某本书的缓存目录即可触发重转换。

### 7.3 DEEP 三阶段（`scripts/monte_carlo_sampler.py`）

**Phase 1 · EXPLORATION（3–5 秒）**  
生成多组搜索词（分词 + 同义词 + n-gram）→ 随机采样 60% 文件（>10 文件时）→ 多模式 Grep → 评分（keyword_density × position_weight × context_quality）→ Top 30% 进入下一阶段。

**Phase 2 · EXPLOITATION（5–15 秒）**  
对高分文件的高分区域做 100–200 行深度阅读；提取完整段落、法律引用、学者观点；新颖性检查（与已收集证据相似度 < 0.5 才保留）；自适应停止（证据充足或收益递减）。

**Phase 3 · SYNTHESIS（<1 秒）**  
去重（相似度 > 0.8 保留较长版本）→ 按子主题分组 → 置信度评估 → 持久化到 Knowledge Cluster Store。

### 7.4 命令

```bash
# 转换单本书到 agentic 缓存
python scripts/parser_adapter.py ~/legal_books/王泽鉴_损害赔偿.pdf \
    -o ~/legal_books/.agentic_cache/王泽鉴_损害赔偿/

# 先扫描一下文献库结构
python scripts/scan_library.py ~/legal_books/.agentic_cache/

# 执行 DEEP 检索
python scripts/monte_carlo_sampler.py \
    --library ~/legal_books/.agentic_cache/王泽鉴_损害赔偿/ \
    --query "与有过失的构成要件" \
    --mode deep
```

### 7.5 查询理解 —— "第X条"的两种含义

在司法解释适用类书籍（目录第 1–69 条）中：
- "第 32 条怎么理解" → **结构检索**：查本书第 32 条的理解与适用
- "民法典第 584 条" → **关联检索**：查本书中引用第 584 条时的论述

这一步的正确率取决于书籍类型能不能识别对——所以缓存目录里保留 `_book_type.txt`。

## 8 · 流水线 D — 问答集 KB（`qa_kb`）

适用于：**FAQ / 业务咨询问答 / 培训问答 / 客服话术 / 法律咨询问答集** 等问答形态语料。

问答集与书籍、裁判文书的本质区别：**基本单元是"问题-答案对"而非条文或案例**。因此检索策略是"**问题匹配为主、答案召回为辅**"——用户提问时，先匹配库内已有问题的语义，再补充答案内容的关键词召回。

### 8.1 支持的问答格式

`qa_parser.py` 自动检测并解析六种格式：

| 格式 | 示例 | 检测特征 |
|---|---|---|
| 显式标记型 | `Q: 问题` / `A: 答案` | 行首 Q:/A:/问:/答: |
| 编号问答型 | `Q1: 问题` / `A1: 答案` | 行首 Q1:/问1: |
| Markdown 标题型 | `### 问题` 下方为答案 | 标题以问号结尾或含 Q1 |
| 表格型 | `\| 问题 \| 答案 \|` | 表头含问题/答案别名 |
| JSON 型 | `[{"question":"...","answer":"..."}]` | 合法 JSON 含 q/a 字段 |
| 启发式连续段落 | 问句行（以？结尾）+ 后续段落 | 以？结尾的短行 |

抽取规则配置在 `assets/qa-patterns.yaml`，字段权重在 `assets/qa-fields.yaml`。

### 8.2 检索策略：双索引 + RRF 融合

问答库构建**两套独立索引**：

```text
用户提问
   │
   ├──→ 问题索引（q_index）     ← 问题 BM25 + 问题向量
   │     "用户提问 ↔ 库内问题"  权重最高（核心路径）
   │
   ├──→ 答案索引（a_index）     ← 答案 BM25 + 答案向量（含 tags 加权）
   │     "用户提问 ↔ 库内答案"  辅助召回
   │
   ├──→ 结构过滤                ← 分类/标签精确匹配
   │
   └──→ RRF 融合 → 排序结果
```

问题索引权重 > 答案索引权重（`qa-fields.yaml` 中 `question_semantic: 1.5` vs `answer_semantic: 0.8`），确保"问题对问题"的语义对齐优先。

### 8.3 全流程命令

```bash
# 初始化
python3 scripts/qa_kb.py --kb ./faq_kb init --name "合同法FAQ"

# 从文件导入（自动检测问答格式）
python3 scripts/qa_kb.py --kb ./faq_kb add ~/faq/合同法问答.md --category "合同法"

# 批量导入目录
python3 scripts/qa_kb.py --kb ./faq_kb batch ~/faq/ --category "合同法"

# 手动添加单个问答对
python3 scripts/qa_kb.py --kb ./faq_kb add-pair \
    --question "定金罚则如何适用？" \
    --answer "给付定金方不履行则无权返还；收受方不履行则双倍返还。" \
    --category "合同法" --tags "定金,违约" --source "民法典第587条"

# 重建索引（问题索引 + 答案索引）
python3 scripts/qa_kb.py --kb ./faq_kb rebuild

# 检索
python3 scripts/qa_kb.py --kb ./faq_kb search --query "格式条款无效" --top-k 5
python3 scripts/qa_kb.py --kb ./faq_kb search --query "违约金" --category "合同法"

# 推荐相似问题（只走问题索引，用于输入联想）
python3 scripts/qa_kb.py --kb ./faq_kb recommend "定金" --top-k 5

# 统计
python3 scripts/qa_kb.py --kb ./faq_kb stats
```

### 8.4 存储结构

```text
faq_kb/
├── config.yaml
├── qa_pairs/                 # 每个问答对一个 JSON
│   ├── qa_0001.json
│   └── ...
├── indices/
│   ├── metadata.json         # 结构化元数据索引（分类/标签统计）
│   ├── q_index/              # 问题专用索引（核心）
│   │   ├── _bm25_corpus.json
│   │   ├── _vectors.faiss
│   │   └── _chunks.json
│   └── a_index/              # 答案召回索引（辅助）
│       ├── _bm25_corpus.json
│       ├── _vectors.faiss
│       └── _chunks.json
└── cache/
```

### 8.5 问答对 JSON 结构

```json
{
  "id": "qa_0001",
  "question": "格式条款无效的情形有哪些？",
  "answer": "根据《民法典》第497条...",
  "category": "合同法",
  "tags": ["格式条款", "无效"],
  "source": "民法典第497条",
  "confidence": 1.0,
  "question_index": 1,
  "raw_format": "explicit",
  "added_at": "2026-07-05T16:00:00"
}
```

## 9 · 业务咨询智能体（`consultation_agent`）

把四条流水线的知识库编排成一个统一的业务咨询智能体：

```text
用户提问
   │
   意图分类（article_lookup / case_search / faq_consult / scholarly_inquiry / practical_guide）
   │
   KB 路由（每种意图查询 1-N 个知识库，按优先级）
   │
   多源检索（qa_kb / case_kb / book_kb / agentic 各自检索）
   │
   证据融合（RRF + 去重 + 阈值过滤）
   │
   结构化回答（按意图选择回答模板，拼接证据）
```

### 9.1 意图分类

基于关键词规则（`assets/consultation-config.yaml`）：

| 意图 | 关键词示例 | 路由到 |
|---|---|---|
| `article_lookup` 法条查询 | "第X条"、"法条"、"法律规定" | book_kb → qa_kb |
| `case_search` 案例检索 | "案例"、"判决"、"怎么判" | case_kb → qa_kb |
| `faq_consult` 常见问题 | "怎么办"、"如何处理"、"流程" | qa_kb → book_kb |
| `scholarly_inquiry` 学理探究 | "构成要件"、"学说"、"观点" | book_kb → case_kb |
| `practical_guide` 实务指引 | "操作"、"步骤"、"风险" | qa_kb → book_kb → case_kb |

### 9.2 多轮对话

- **上下文窗口**：保留最近 N 轮对话（默认 5）
- **指代消解**：用户说"那这个呢"时，拼接上一轮主题
- **上下文衰减**：第 k 轮权重 = decay^(k-1)（默认 0.6）
- **澄清阈值**：top1 相关度过低时主动要求用户澄清

### 9.3 使用方式

```bash
# 命令行直接咨询
python3 scripts/consultation_agent.py \
    --qa-kb ~/kbs/faq_kb --case-kb ~/kbs/case_kb --book-kb ~/kbs/book_kb \
    ask "格式条款无效的情形有哪些？"

# JSON 输出（供程序调用）
python3 scripts/consultation_agent.py --qa-kb ~/kbs/faq_kb \
    ask "违约金过高怎么调整？" --json

# 自动发现知识库
python3 scripts/consultation_agent.py --discover ask "表见代理的构成要件"

# 重置对话上下文
python3 scripts/consultation_agent.py --reset ask "新的问题"
```

### 9.4 回答模板

按意图选择结构化模板（`consultation-config.yaml` → `answer_generation.templates`）：

- **faq_consult**：【直接回答】→【法律依据】→【操作建议】→【注意事项】
- **case_search**：【检索到的相关案例】→【裁判要旨】→【类案裁判规则】
- **article_lookup**：【法条原文】→【条文主旨】→【理解与适用】→【关联条文】
- **scholarly_inquiry**：【问题界定】→【通说观点】→【不同学说】→【实务倾向】
- **practical_guide**：【操作步骤】→【法律依据】→【风险提示】

## 10 · HTTP API 服务（可选 — 仅当用户要求对外服务时）

> **此章节为可选扩展**。默认情况下不需要启动 HTTP API。仅当用户在 §0 引导中 Q3 选择"本地服务"或"云端托管"时才使用。

把咨询智能体和各知识库检索以 HTTP 接口暴露，支撑**前端问答平台**和**钉钉/飞书机器人**。

### 10.1 接口概览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/ask` | 通用业务咨询（意图分类→KB路由→多源检索→结构化回答） |
| POST | `/qa/ask` | 问答库直接检索 |
| POST | `/case/search` | 裁判文书检索 |
| GET | `/kb/list` | 列出已加载的知识库 |
| GET | `/kb/{type}/stats` | 知识库统计 |
| GET | `/health` | 健康检查 |
| GET | `/sessions` | 列出活跃会话 |
| DELETE | `/session/{id}` | 清除会话上下文 |
| POST | `/webhook/dingtalk` | 钉钉机器人 webhook 适配 |
| POST | `/webhook/feishu` | 飞书机器人 webhook 适配 |

### 10.2 启动

```bash
# 安装依赖（可选，仅 API 服务需要）
pip install fastapi uvicorn pydantic

# 指定知识库启动
python3 scripts/api_server.py \
    --qa-kb ~/kbs/faq_kb \
    --case-kb ~/kbs/case_kb \
    --port 8000 --host 0.0.0.0

# 自动发现知识库
python3 scripts/api_server.py --discover

# 环境变量方式
QA_KB_PATH=~/kbs/faq_kb python3 scripts/api_server.py
```

启动后访问 `http://localhost:8000/docs` 查看交互式 API 文档。

### 10.3 前端问答平台调用示例

```javascript
// 通用咨询
const res = await fetch("http://your-server:8000/ask", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
        question: "格式条款无效的情形有哪些？",
        session_id: "user_123"  // 多轮对话用
    })
});
const data = await res.json();
// data.answer — 结构化回答
// data.evidence — 证据列表
// data.suggestions — 建议/澄清
```

### 10.4 钉钉机器人接入

1. 钉钉群 → 群设置 → 智能群助手 → 添加自定义机器人
2. 安全设置选择"IP 地址段"，填入你的服务器 IP
3.（如支持 Outgoing）POST 地址填 `http://your-server:8000/webhook/dingtalk`

钉钉消息格式（自动适配）：
```json
// 入站
{"msgtype": "text", "text": {"content": "违约金过高怎么调整？"}, "conversationId": "cid_001"}

// 出站（自动返回）
{"msgtype": "text", "text": {"content": "【直接回答】\n  [问答库] ..."}}
```

### 10.5 飞书机器人接入

1. 飞书开放平台 → 创建应用 → 事件订阅
2. 请求地址填 `http://your-server:8000/webhook/feishu`
3. 订阅 `im.message.receive_v1` 事件

飞书会先发送 URL 验证（challenge），API 自动处理后即可接收消息事件。

## 11 · 工厂主入口与 MCP 服务

### 11.1 工厂主入口（`kb_factory`）

一键把任意语料路由并构建到最适合的知识库：

```bash
# 只看路由决策（不构建）
python3 scripts/kb_factory.py route ~/legal_materials/合同法FAQ.pdf

# 一键构建
python3 scripts/kb_factory.py build ~/legal_materials/合同法FAQ.pdf \
    --output ~/kbs/合同法FAQ --name "合同法FAQ"

# 批量构建整个目录
python3 scripts/kb_factory.py build ~/legal_materials/ \
    --output ~/kbs/ --batch --json
```

工厂自动完成：格式路由 → 解析（若需要）→ 数据源路由 → 对应流水线构建。

### 11.2 MCP 服务（`mcp_server`）

把检索与咨询能力暴露给任何 MCP 客户端（Claude Desktop / Cursor / Cline / Continue）：

```json
{
  "mcpServers": {
    "legal-kb": {
      "command": "python3",
      "args": ["/path/to/legal-kb-builder/scripts/mcp_server.py"],
      "env": {
        "KB_PATH": "/path/to/book_kb",
        "QA_KB_PATH": "/path/to/qa_kb",
        "CASE_KB_PATH": "/path/to/case_kb"
      }
    }
  }
}
```

暴露的 MCP 工具：

| 工具 | 说明 |
|---|---|
| `consult` | 跨库业务咨询（意图分类→KB路由→多源检索→结构化回答） |
| `qa_search` | 问答库检索（问题匹配为主、答案召回为辅） |
| `qa_recommend` | 推荐相似问题（输入联想） |
| `qa_stats` | 问答库统计 |
| `search_by_article` | 按法条编号精确检索（book_kb） |
| `search_by_query` | 自然语言检索（book_kb） |
| `search_by_scholar` | 学者观点检索（book_kb） |
| `list_books` / `list_kbs` | 列出书籍/知识库 |
| `get_book_index` | 读取书籍索引 |

## 12 · 常见错误与防范

| 错误 | 症状 | 防范 |
|---|---|---|
| 正文引用条文被当作书的结构条目 | 索引条文数远超实际（69 条变 489 条） | 阶段零先定组织单元；索引完成做数量一致性校验；司法解释适用类只算自身条文号 |
| 书籍类型误判 | 用评注方式给专著建索引，找不到章节 | 先读目录；目录没"第X条"作为主要条目就不是评注类 |
| 分卷切断连续内容 | 同一条评注被切到两个文件 | 分卷边界选在两个组织单元之间；用重叠页保底 |
| 解析后端全部失败 | `parser_adapter` 抛 RuntimeError | 至少启用一个可用后端；生产环境建议在线 API + 本地 OCR 双通道 |
| 中文路径转换失败 | doc-parse 类工具报错 | 先 cp 到无中文目录，转换完成后再挪回；或用 `shlex.quote()`（`parser_adapter` 已处理） |

## 13 · 集成式知识库构建（把一本书整合进已有知识库）

**场景**：不是从零建独立库，而是把某本书的核心内容整合进已有的某个知识库文件（例如把《民事诉讼管辖精义》整合进 `jurisdiction-rules.md`）。

| 维度 | 独立构建 | 集成式构建 |
|---|---|---|
| 产物 | 独立多文件知识库 + 索引 | 已有文件中的少量文件/段落 |
| 组织结构 | 以书的原始目录为锚 | 以目标知识库的现有结构为锚 |
| 内容处理 | 尽量保留全文 | 提炼主文，去序言/脚注/后记 |
| 典型触发 | "构建 XX 知识库" | "把这本书整合到 XX 里" |

推荐流程：

1. **Step 1**：拿到 md 源文件（优先复用用户已有的 doc-parse 输出；已过时的旧产物果断弃用）。
2. **Step 2**：制作"原书章节 → 目标节"映射表。
3. **Step 3**：**用一个 Python 脚本**机械抽取——按章节标题正则切分、过滤前言/序言/后记/致谢/脚注/出版信息、清理 OCR 伪影、每章输出到 `chapters/`。这一步不要用 subagent（脚本 5 秒完成，subagent 需要几分钟）。
4. **Step 4**：需要"理解 + 改写"的部分再启并行 subagent（每组 3–4 章），产出 `integrated_groupN.md`。
5. **Step 5**：组装脚本按目标节序号排列，检查 Markdown 层级（H2 = 节，H3 = 子节，H4 = 细分点）。
6. **Step 6**：质量校验。

## 14 · 配置与扩展点

| 想要改的东西 | 改哪 |
|---|---|
| 加/减解析后端 | `assets/parser-backends.yaml` |
| 调整数据源分类阈值（含问答集识别） | `assets/routing-rules.yaml` |
| 拆分/合并/清洗一体化 | `assets/config-template.yaml` |
| OCR 错字规则 | `assets/ocr-corrections.yaml` |
| 法律术语纠错 | `assets/legal-corrections.yaml` |
| 同义词（BM25 + Agentic 共用） | `assets/keyword-expansion.yaml` |
| 裁判文书要素正则 | `assets/element-patterns.yaml` |
| 裁判文书字段与嵌入权重 | `assets/judgment-fields.yaml` |
| 问答对抽取规则（六种格式） | `assets/qa-patterns.yaml` |
| 问答字段与嵌入权重 | `assets/qa-fields.yaml` |
| 咨询意图/路由/模板/对话 | `assets/consultation-config.yaml` |

深度说明：

- `references/retrieval-guide.md` — 七类书籍的索引 JSON 模板全清单
- `references/search-patterns.md` — 检索模式与融合公式
- `references/config-reference.md` — 全部配置字段的含义与默认值
- `references/examples.md` — 四条端到端样例（书籍库 / 裁判库 / 单本随查 / 目录级自动路由）与常见故障排查

## 15 · 依赖安装（按需选择，不要全装）

本工具采用**按场景安装**策略。**不要盲目 `pip install -r requirements.txt`**——那只装基础依赖。请根据你的使用场景选择对应的依赖组合。

### 15.1 快速选择

```bash
# 方式 A：交互式安装助手（推荐新手）
python3 scripts/install_deps.py

# 方式 B：检查当前已装了什么
python3 scripts/install_deps.py --check

# 方式 C：列出所有场景
python3 scripts/install_deps.py --list

# 方式 D：直接指定场景安装
python3 scripts/install_deps.py --scene book-full    # 推荐：书籍知识库+图谱+评估
```

### 15.2 场景与依赖对照表

| 场景 | 适用需求 | 安装命令 | 大小 |
|------|---------|---------|------|
| `minimal` | 只做格式路由 + Grep | `pip install -r requirements.txt` | ~10MB |
| `book` | 书籍知识库（BM25+向量+重排） | `pip install -r requirements.txt -r requirements-vector.txt` | ~2.5GB |
| `book-full` | **书籍知识库 + GraphRAG + 评估（推荐生产）** | `pip install -r requirements.txt -r requirements-vector.txt -r requirements-graph.txt -r requirements-eval.txt` | ~2.6GB |
| `case` | 裁判文书知识库 | 同 `book` | ~2.5GB |
| `qa` | 问答集/FAQ 知识库 | 同 `book` | ~2.5GB |
| `agentic` | Agentic 实时检索（无需向量库） | `pip install -r requirements.txt` | ~10MB |
| `api` | 对外 HTTP API（前端/钉钉/飞书） | `pip install -r requirements.txt -r requirements-vector.txt -r requirements-api.txt` | ~2.6GB |
| `mcp` | MCP 服务（Claude Desktop/Cursor） | `pip install -r requirements.txt -r requirements-vector.txt -r requirements-mcp.txt` | ~2.6GB |
| `all` | 全部功能一次性装齐 | `pip install -r requirements-all.txt` | ~3GB |

> **torch 是大头**：向量检索依赖 torch（~2GB）。如果你只需要 BM25 + Grep（如 Agentic 模式），完全不需要装 torch。

### 15.3 依赖文件说明

| 文件 | 包含 | 必需性 |
|------|------|--------|
| `requirements.txt` | PyYAML + pypdf + jieba + rank-bm25 + numpy | **必装**（所有场景） |
| `requirements-vector.txt` | sentence-transformers + faiss-cpu + torch | 按需（向量检索+重排） |
| `requirements-graph.txt` | networkx | 按需（GraphRAG 图谱） |
| `requirements-api.txt` | fastapi + uvicorn + pydantic | 按需（HTTP API） |
| `requirements-mcp.txt` | mcp | 按需（MCP 服务） |
| `requirements-eval.txt` | ragas + datasets | 按需（RAGAS 评估） |
| `requirements-all.txt` | 引用以上全部 | 方便一次性装齐 |

### 15.4 不装某依赖时的降级行为

| 缺失依赖 | 影响 | 降级行为 |
|---------|------|---------|
| 无 pypdf | 无法拆分 PDF | 需手动拆分或用其他工具 |
| 无 jieba/rank-bm25 | 无 BM25 检索 | 降级为"结构索引 + Grep"单路 |
| 无 sentence-transformers/faiss/torch | 无向量检索 + 无 Cross-Encoder 重排 | 降级为"BM25 + 结构索引"两路融合 |
| 无 networkx | 无 GraphRAG 图谱 | 降级为三路融合（无图谱路径） |
| 无 fastapi/uvicorn | api_server.py 无法启动 | 其他功能不受影响 |
| 无 mcp | mcp_server.py 无法启动 | 其他功能不受影响 |
| 无 ragas/datasets | 无 RAGAS 五指标 | 基础指标（hit_rate/mrr/recall）仍可用 |

## 15.5 · 默认流程（本地 skill 形态）

> **大多数用户走这条路就够了**。构建完本地知识库后，安装为本地 skill 即完成任务。

```text
1. onboard.py --scan          # 探测本地环境
2. 确认 Q1-Q3（§0 引导）       # 用户选解析工具+知识库类型+部署形态(默认本地skill)
3. install_deps.py --scene X  # 按场景装依赖
4. kb_factory.py build ...    # 构建知识库
5. 安装为本地 skill            # 把 SKILL.md + 知识库放到 agent 的 skill 目录
6. 结束                       # 用户在 agent 中直接调用该 skill 检索知识库
```

**安装位置**：若用户未指定，与用户当前运行 agent 中的其他本地 skill 放在一起（通常是 `~/.workbuddy/skills/` 或 agent 配置的 skill 目录）。安装后 agent 可直接调用该 skill 检索对应知识库。

**安装内容**：
- 精简版 SKILL.md（只含检索调用说明，不含构建流程）
- 知识库目录（md 文件 + 索引文件）
- 检索脚本（hybrid_search.py + 依赖脚本）

## 16 · 关于 AI Agent 调用本工具

本工具全部 CLI 都是标准 argparse 接口，任何 agent 框架（Claude Code / Cursor / Gemini CLI / OpenCode ...）都可以直接把 `scripts/*.py` 当子命令调用。推荐的调用顺序：

```text
1. format_detector.py <input> --json         # 拿到格式决策
2. parser_adapter.py <input> -o <outdir>     # 转 md（若需要）
3. material_router.py <md_file>              # 拿到 target_skill
4. 按 target_skill 分别调用：
     book_kb  → legal_kb.py 全流程
     case_kb  → judgment_kb.py 全流程
     qa_kb    → qa_kb.py 全流程
     agentic  → monte_carlo_sampler.py
     direct   → 直接 cp 到 references/
5. 或直接用工厂入口一键完成 1-4：
     kb_factory.py build <input> --output <outdir> --name <name>
6. 对外提供服务：
     咨询     → consultation_agent.py ask "问题"
     HTTP API → api_server.py --qa-kb <path> --port 8000
     MCP      → mcp_server.py（暴露 consult / qa_search 等工具）
```

## 17 · RAG 质量评估（`eval/`）

用量化指标评估检索质量，支撑迭代优化（换模型、调参数前后对比）。

### 17.1 两套指标

| 指标类型 | 依赖 | 指标 | 说明 |
|---------|------|------|------|
| 基础检索 | 无 | hit_rate@k / mrr / recall@k | 关键词命中，始终可用 |
| RAGAS | `pip install ragas` | faithfulness / answer_relevance / context_precision / context_recall / answer_correctness | LLM 评估生成质量 |

### 17.2 使用方式

```bash
# 基线评估（无依赖）
python eval/eval_rag.py --kb-path ~/kbs/民法典评注 --label "baseline"

# 完整 RAGAS 评估
python eval/eval_rag.py --kb-path ~/kbs/民法典评注 --full --label "bge_m3_rerank"

# 对比 eval/results/ 下两次结果的 summary
```

评估集 `eval/legal_qa_eval.jsonl` 内置 20 条覆盖民法典各编的标注样本，建议扩充到 50-100 条。详见 `eval/README.md`。

## 18 · 云端部署（可选扩展 — 仅当用户主动要求时）

> **此章节为可选扩展**。默认情况下，构建本地知识库 + 安装为本地 skill 即完成任务。
> 仅当用户在 §0 引导中 Q3 选择"云端托管"时，才执行以下内容。

本地知识库构建完成后，若用户要求公网可访问的智能体 API，有两条托管路径：

| 平台 | 特点 | 是否需要服务器 |
|------|------|--------------|
| **Qoder Cloud Agents** | 全托管，Agent 在云端 sandbox 运行你的检索脚本 | 不需要 |
| **阿里云百炼** | 通过百炼 CLI 创建智能体，支持知识库上传/MCP/HTTP API 三种接入 | mcp/api 模式需要 |

### 18.1 快速部署

```bash
# 交互式部署（推荐）
python3 scripts/deploy_agent.py

# 检查前置条件
python3 scripts/deploy_agent.py --check

# 指定平台
python3 scripts/deploy_agent.py --platform qoder --kb-path ~/kbs/民法典评注
python3 scripts/deploy_agent.py --platform bailian --kb-path ~/kbs/民法典评注

# 演练（不实际调用 API）
python3 scripts/deploy_agent.py --platform qoder --kb-path ~/kbs/民法典评注 --dry-run
```

### 18.2 Qoder Cloud Agents（无需服务器）

```bash
# 1. 获取 PAT：https://qoder.com → 设置 → 个人访问令牌
export QODER_PAT="your-token"

# 2. 部署（上传 KB 文件 + 创建 Agent）
python3 scripts/deploy_agent.py --platform qoder --kb-path ~/kbs/民法典评注

# 3. 部署后获得 agent_id，通过公网 API 调用：
# POST https://api.qoder.com/api/v1/cloud/sessions  (创建会话)
# POST .../sessions/{id}/events                     (发送咨询)
# GET  .../sessions/{id}/events/stream              (SSE 实时接收)
```

### 18.3 阿里云百炼（三种接入模式）

```bash
# 1. 安装百炼 CLI
npm install -g bailian-cli
bl auth login --console

# 2. 部署
python3 scripts/deploy_agent.py --platform bailian --kb-path ~/kbs/民法典评注
```

三种知识库接入模式（在 `deploy-backends.yaml` 中配置 `kb_mode`）：
- `upload`：上传 md 到百炼知识库（无需服务器，但丢失混合检索）
- `mcp`：百炼通过 MCP 调用你的 mcp_server（需公网服务器，保留完整检索）
- `api`：百炼通过 HTTP 调用你的 api_server（需公网服务器）

### 18.4 部署后对外集成

获得公网 API 后，你可以进一步做（**本技能工作范围不再覆盖**）：
- 网站 / 小程序 / App：后端调用 API，前端展示
- MCP 服务：把 API 封装为 MCP 工具
- CLI 工具：命令行调用 API
- 钉钉/飞书机器人：webhook 接收消息 → 调用 API → 返回

详细部署指南见 [references/deploy-guide.md](references/deploy-guide.md)。

## 19 · 许可

**CC BY-NC-ND 4.0 + 6 附加条款**（详见根目录 `LICENSE`）：

- BY 署名 / NC 非商业 / ND 禁改编 —— 基础三项。
- **禁 AI 训练**：不得作为任何 ML 模型的训练/微调/蒸馏/RAG 语料。
- **禁上架收费技能市场**：不得在收费 skill/plugin/agent 市场上再分发。
- **企业与行政机关一律视同商用**：企业、政府机关、司法机关、国企及其外包商的内部使用亦视为商用，需另行商业授权。
- **学术引用格式**：论文、书籍、公开演讲需以正式参考文献条目（而非脚注一笔带过）引用本工具。
- **禁背书**：未经许可不得使用作者姓名/花名"游初"/雇主标识做背书或暗示赞助。
- **权利保留**：作者保留发布付费专业版、单独商业授权、更新未来版本许可的权利。

商业授权 / 企业部署 / AI 训练豁免请联系：游初 &lt;994559732@qq.com&gt;。

## Tips

- **"目录即锚"是法律知识库的头号原则**：索引必须以书的真实目录为唯一依据，正文中"参见第X条"是引用不是结构条目。一本讲解 69 条司法解释的书，正文引用了数百条民法典——如果把引用也当结构条目，索引会从 69 条膨胀到 489 条。
- **司法解释适用类的陷阱**：目录只有几十条（如 69 条），但正文引用了大量其他法律条文。索引只算司法解释自身的条文号，绝不能把被引用的条文也纳入索引。
- **切换 embedding 模型后必须重建索引**：`_chunks.json` 存了 model 和 dim 字段，加载时自动校验。bge-small(384维) 切到 bge-m3(1024维) 后不重建会导致维度不匹配。
- **父子分块比固定分块好**：小块(256字符)检索精度高，大块(1024字符)上下文完整。生产环境用 `--strategy parent_child`，效果远好于固定 512 字符分块。
- **Cross-Encoder 重排是 +20% 精度的关键**：RRF 融合后取 Top-30 做 bge-reranker-v2-m3 精排到 Top-5。不装 sentence-transformers 会降级为纯 RRF，精度损失明显。
- **GraphRAG 解决全局问题**：传统向量检索只能返回局部片段，查"民法典物权编的主要制度"这类全局问题需要法条关联图谱。用 `graph_rag.py build` 构建图谱后，多跳查询能发现"第311条→适用案例→共现法条"的关联链。
- **裁判文书别做全文分块**：裁判文书有固定结构（案号→当事人→事实→说理→判决），应该做要素抽取 + 字段级嵌入。"本院认为"段落价值最高，应独立建索引。
- **问答库要建双索引**：问题索引权重(1.5) > 答案索引权重(0.8)。用户提问应该先和库内已有问题对齐（语义同构），而不是直接匹配答案内容。
- **中文路径解析容易失败**：doc-parse 类工具对中文路径报错时，先 cp 到无中文目录转换，完成后再挪回。`parser_adapter.py` 已用 `shlex.quote()` 处理，但部分后端仍有问题。
- **RAGAS 评估闭环不可少**：没有评估就无法回答"换了个模型，检索质量变好还是变差"。先用 `eval/eval_rag.py --label baseline` 建基线，每次改参数后对比。
- **Agentic 模式的蒙特卡洛采样不是随机**：EXPLORATION 阶段做多模式 Grep + 评分（keyword_density × position_weight × context_quality），EXPLOITATION 阶段对高分区域深度阅读，有自适应停止机制。
