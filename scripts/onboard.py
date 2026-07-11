#!/usr/bin/env python3
"""
本地环境探测 + 交互式引导脚本

扫描用户本地安装的文档解析工具和 Python 依赖，
辅助 AI agent 在任务开始时向用户提问并生成执行计划。

用法：
    python3 scripts/onboard.py                    # 完整探测 + 交互式引导
    python3 scripts/onboard.py --scan             # 只扫描本地环境
    python3 scripts/onbound.py --scan --json      # JSON 输出
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

_SCRIPT_DIR = Path(__file__).parent
_PROJECT_ROOT = _SCRIPT_DIR.parent


# ═══════════════════════════════════════════
# 文档解析工具探测
# ═══════════════════════════════════════════

def detect_parsing_tools() -> List[Dict[str, Any]]:
    """探测本地安装的文档解析工具"""
    tools = []

    # 1. MinerU (CLI 或 npm 包)
    mineru_cli = shutil.which("mineru")
    if mineru_cli:
        tools.append({"name": "MinerU CLI", "type": "cli", "command": "mineru", "formats": ["PDF", "图片", "Word", "PPT", "Excel"]})
    # 检查 npm 全局包
    try:
        result = subprocess.run(["npm", "list", "-g", "mineru-open-api"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and "mineru-open-api" in result.stdout:
            tools.append({"name": "MinerU Open API (npm)", "type": "npm", "command": "npx mineru-open-api", "formats": ["PDF", "图片", "Word", "PPT", "Excel"]})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # 检查环境变量
    if os.environ.get("MINERU_TOKEN"):
        tools.append({"name": "MinerU API (token已配置)", "type": "api", "command": "MINERU_TOKEN", "formats": ["PDF", "图片", "Word", "PPT", "Excel"]})

    # 2. PaddleOCR (Python 包)
    try:
        import paddleocr
        tools.append({"name": "PaddleOCR", "type": "python", "command": "paddleocr", "formats": ["图片", "PDF"]})
    except ImportError:
        pass

    # 3. 合合信息 TextIn (检查环境变量)
    if os.environ.get("TEXTIN_API_KEY") or os.environ.get("TEXTRACT_API_KEY"):
        tools.append({"name": "合合信息 TextIn", "type": "api", "command": "TEXTIN_API_KEY", "formats": ["PDF", "图片", "Word"]})

    # 4. 阿里云百炼 (检查环境变量或 bl CLI)
    bl_path = shutil.which("bl") or shutil.which("bailian")
    if bl_path:
        tools.append({"name": "阿里云百炼 CLI", "type": "cli", "command": "bl", "formats": ["PDF", "图片", "Word"]})
    if os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("BAILIAN_API_KEY"):
        tools.append({"name": "阿里云百炼 API", "type": "api", "command": "DASHSCOPE_API_KEY", "formats": ["PDF", "图片", "Word"]})

    # 5. LibreOffice (CLI)
    lo_path = shutil.which("libreoffice") or shutil.which("soffice")
    if lo_path:
        tools.append({"name": "LibreOffice", "type": "cli", "command": "libreoffice", "formats": ["DOCX", "PPTX", "XLSX", "ODT"]})

    # 6. pandoc (CLI)
    pandoc_path = shutil.which("pandoc")
    if pandoc_path:
        tools.append({"name": "pandoc", "type": "cli", "command": "pandoc", "formats": ["DOCX", "HTML", "EPUB", "LaTeX"]})

    # 7. markitdown (Python 包，微软出品)
    try:
        import markitdown
        tools.append({"name": "MarkItDown", "type": "python", "command": "markitdown", "formats": ["DOCX", "PPTX", "XLSX", "PDF"]})
    except ImportError:
        pass

    return tools


# ═══════════════════════════════════════════
# Python 依赖探测
# ═══════════════════════════════════════════

def detect_python_deps() -> Dict[str, bool]:
    """探测 Python 依赖安装状态"""
    deps = {}
    dep_map = {
        "PyYAML": "yaml",
        "pypdf": "pypdf",
        "jieba": "jieba",
        "rank-bm25": "rank_bm25",
        "numpy": "numpy",
        "sentence-transformers": "sentence_transformers",
        "faiss-cpu": "faiss",
        "torch": "torch",
        "networkx": "networkx",
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "mcp": "mcp",
        "ragas": "ragas",
    }
    for pip_name, import_name in dep_map.items():
        try:
            __import__(import_name)
            deps[pip_name] = True
        except ImportError:
            deps[pip_name] = False
    return deps


# ═══════════════════════════════════════════
# 能力推断
# ═══════════════════════════════════════════

def infer_capabilities(tools: List[Dict], deps: Dict[str, bool]) -> Dict[str, Any]:
    """根据已安装的工具和依赖推断当前能力"""
    has_parsing = len(tools) > 0
    has_bm25 = deps.get("jieba", False) and deps.get("rank-bm25", False)
    has_vector = deps.get("sentence-transformers", False) and deps.get("faiss-cpu", False) and deps.get("torch", False)
    has_rerank = has_vector  # reranker 复用 sentence-transformers
    has_graph = deps.get("networkx", False)
    has_api = deps.get("fastapi", False) and deps.get("uvicorn", False)
    has_mcp = deps.get("mcp", False)
    has_eval = deps.get("ragas", False)

    # 检索能力等级
    if has_vector and has_bm25:
        search_level = "full"  # 四路融合 + 重排
    elif has_bm25:
        search_level = "bm25"  # BM25 + 结构索引
    else:
        search_level = "grep"  # 仅 Grep

    # 可搭建的知识库类型
    kb_types = []
    if has_parsing:
        kb_types.append("book_kb")    # 书籍评注
        kb_types.append("case_kb")    # 裁判文书
        kb_types.append("qa_kb")      # 问答集
    kb_types.append("agentic")        # Agentic 无需解析工具

    # 对外服务能力
    services = []
    if has_api:
        services.append("http_api")
    if has_mcp:
        services.append("mcp")

    return {
        "search_level": search_level,
        "has_parsing": has_parsing,
        "has_bm25": has_bm25,
        "has_vector": has_vector,
        "has_rerank": has_rerank,
        "has_graph": has_graph,
        "has_api": has_api,
        "has_mcp": has_mcp,
        "has_eval": has_eval,
        "kb_types": kb_types,
        "services": services,
        "missing_for_full": _missing_for_full(deps),
    }


def _missing_for_full(deps: Dict[str, bool]) -> List[str]:
    """列出达到 full 能力还缺什么"""
    missing = []
    if not deps.get("jieba"):
        missing.append("jieba (BM25 分词)")
    if not deps.get("rank-bm25"):
        missing.append("rank-bm25 (BM25 检索)")
    if not deps.get("sentence-transformers"):
        missing.append("sentence-transformers (向量嵌入+重排)")
    if not deps.get("faiss-cpu"):
        missing.append("faiss-cpu (向量索引)")
    if not deps.get("torch"):
        missing.append("torch (模型后端)")
    if not deps.get("networkx"):
        missing.append("networkx (GraphRAG)")
    return missing


# ═══════════════════════════════════════════
# 交互式引导
# ═══════════════════════════════════════════

def interactive_onboard(tools: List[Dict], deps: Dict[str, bool], caps: Dict):
    """交互式引导用户完成配置选择"""
    print("=" * 60)
    print("legal-kb-builder 交互式引导")
    print("=" * 60)

    # ── Q1: 文档解析工具 ──
    print("\n── Q1: 文档解析工具 ──")
    if tools:
        print("检测到本地已安装以下解析工具：")
        for i, t in enumerate(tools, 1):
            print(f"  {i}. {t['name']} ({t['type']}) — 支持: {', '.join(t['formats'])}")
        print(f"  0. 手动输入其他工具")
    else:
        print("⚠️ 未检测到本地解析工具。")
        print("  需要处理 PDF/DOCX/图片等非 md 文件时，至少需要一个解析后端。")
        print("  推荐安装：")
        print("    MinerU:    npm install -g mineru-open-api  (需 MINERU_TOKEN)")
        print("    PaddleOCR: pip install paddleocr")
        print("    LibreOffice: brew install libreoffice (macOS)")
        print("    pandoc:    brew install pandoc")
        print("  若输入已是 md/txt 格式，可跳过此步。")

    # ── Q2: 知识库类型 ──
    print("\n── Q2: 知识库类型 ──")
    print("  1. book_kb   — 结构化书籍（法典评注/司法解释/学术专著/教科书）")
    print("  2. case_kb   — 裁判文书（判决书/裁定书/调解书）")
    print("  3. qa_kb     — 问答集/FAQ（法律咨询问答/培训问答/客服话术）")
    print("  4. agentic   — Agentic 实时检索（无需预建索引，Grep+蒙特卡洛采样）")
    print("  5. 混合      — 多种类型语料，由路由器自动分发")

    # ── Q3: 部署形态 ──
    print("\n── Q3: 部署形态 ──")
    print("  1. 本地 skill（默认）— 构建知识库 + 安装为本地 skill，在当前 agent 中直接调用")
    print("  2. 本地服务          — 额外启动 HTTP API / MCP 供其他程序调用")
    print("  3. 云端托管          — 部署到 Qoder Cloud Agents / 阿里云百炼，获取公网 API")

    # ── Q4: 云端平台（仅当 Q3 选 3 时）──
    print("\n── Q4: 云端平台（仅当选择云端托管时）──")
    print("  1. Qoder Cloud Agents — 全托管，无需服务器")
    print("  2. 阿里云百炼         — 需百炼 CLI，支持知识库上传/MCP/HTTP API")

    # ── Q5: 最终服务形态（仅当 Q3 选 2 或 3 时）──
    print("\n── Q5: 最终服务形态（仅当选择本地服务或云端托管时）──")
    print("  1. HTTP API   — 供网站/小程序/App 后端调用")
    print("  2. MCP 服务   — 供 Claude Desktop/Cursor 等 MCP 客户端调用")
    print("  3. 钉钉机器人 — 钉钉群 webhook")
    print("  4. 飞书机器人 — 飞书应用 webhook")

    # ── 生成执行计划 ──
    print("\n" + "=" * 60)
    print("当前环境能力评估")
    print("=" * 60)

    level_names = {
        "full": "完整（四路融合 + Cross-Encoder 重排 + GraphRAG）",
        "bm25": "BM25 + 结构索引（两路融合）",
        "grep": "基础（仅 Grep 关键词匹配）",
    }
    print(f"\n检索能力: {level_names.get(caps['search_level'], caps['search_level'])}")
    print(f"可建知识库类型: {', '.join(caps['kb_types'])}")

    if caps["missing_for_full"]:
        print(f"\n达到完整能力还需安装: {', '.join(caps['missing_for_full'])}")
        print(f"  一键安装: pip install -r requirements-vector.txt -r requirements-graph.txt")

    if not tools:
        print("\n⚠️ 未检测到解析工具。若语料是 PDF/DOCX/图片，需要先安装一个解析后端。")
        print("  参考: assets/parser-backends.example.yaml")

    print("\n" + "=" * 60)
    print("请将以上选项告知 AI agent，它将据此执行对应流程。")
    print("=" * 60)


# ═══════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="本地环境探测 + 交互式引导")
    parser.add_argument("--scan", action="store_true", help="只扫描不引导")
    parser.add_argument("--json", action="store_true", help="JSON 输出（配合 --scan）")
    args = parser.parse_args()

    tools = detect_parsing_tools()
    deps = detect_python_deps()
    caps = infer_capabilities(tools, deps)

    if args.scan:
        output = {
            "parsing_tools": tools,
            "python_deps": deps,
            "capabilities": caps,
        }
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print("=== 文档解析工具 ===")
            if tools:
                for t in tools:
                    print(f"  ✓ {t['name']} ({t['type']}) — {', '.join(t['formats'])}")
            else:
                print("  (未检测到)")

            print("\n=== Python 依赖 ===")
            for name, installed in deps.items():
                print(f"  {'✓' if installed else '✗'} {name}")

            print(f"\n=== 能力评估 ===")
            print(f"  检索能力: {caps['search_level']}")
            print(f"  解析工具: {'有' if caps['has_parsing'] else '无'}")
            print(f"  BM25: {'✓' if caps['has_bm25'] else '✗'}")
            print(f"  向量检索: {'✓' if caps['has_vector'] else '✗'}")
            print(f"  GraphRAG: {'✓' if caps['has_graph'] else '✗'}")
            print(f"  HTTP API: {'✓' if caps['has_api'] else '✗'}")
            print(f"  MCP: {'✓' if caps['has_mcp'] else '✗'}")
            if caps["missing_for_full"]:
                print(f"\n  达到完整能力还需: {', '.join(caps['missing_for_full'])}")
        return

    interactive_onboard(tools, deps, caps)


if __name__ == "__main__":
    main()
