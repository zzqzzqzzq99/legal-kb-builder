#!/usr/bin/env python3
"""
法律知识库工厂主入口（KB Factory）

把 legal-kb-builder 的双层路由 + 四条流水线（book_kb / case_kb / qa_kb / agentic）
编排成一个统一的"丢进来就建好库"的入口：

    任意语料（PDF/DOCX/MD/TXT/JSON/图片）
       │
    格式路由（format_detector + parser_adapter）  → 全部转成 md
       │
    数据源路由（material_router）                  → book_kb / case_kb / qa_kb / agentic / direct
       │
    对应流水线自动构建
       │
    可检索的知识库

使用方式：
    # 一键构建
    python3 scripts/kb_factory.py build ~/legal_materials/合同法FAQ.pdf \\
        --output ~/kbs/合同法问答库 --name "合同法FAQ"

    # 只看路由决策（不实际构建）
    python3 scripts/kb_factory.py route ~/legal_materials/合同法FAQ.pdf

    # 批量构建（整个目录）
    python3 scripts/kb_factory.py build ~/legal_materials/ --output ~/kbs/ --batch
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from material_router import MaterialRouter, RoutingDecision


class KBFactory:
    """
    法律知识库工厂

    编排格式路由 → 数据源路由 → 流水线构建的完整流程。
    """

    def __init__(self):
        self.router = MaterialRouter()

    # ─── 路由（不构建） ───

    def route(self, input_path: str) -> RoutingDecision:
        """
        对输入文件执行双层路由，返回决策结果（不实际构建）。

        如果输入是非 md 格式，会先检测是否需要解析，并在 suggested_params 中标注。
        """
        path = Path(input_path)
        if not path.exists():
            return RoutingDecision(
                target_skill="unknown",
                reasoning=f"文件不存在: {input_path}",
            )
        return self.router.route(input_path)

    # ─── 构建（路由 + 构建） ───

    def build(
        self,
        input_path: str,
        output_dir: str,
        name: str = "",
        default_category: str = "",
        skip_parse: bool = False,
    ) -> Dict[str, Any]:
        """
        一键构建：路由 → 解析（若需要）→ 流水线构建。

        Args:
            input_path: 输入文件或目录
            output_dir: 知识库输出目录
            name: 知识库名称
            default_category: 问答库默认分类
            skip_parse: 跳过格式解析（输入已经是 md）

        Returns:
            构建结果摘要
        """
        path = Path(input_path)
        out = Path(output_dir)

        # Step 1: 格式路由 + 解析
        md_path = self._ensure_markdown(path, skip_parse)
        if md_path is None:
            return {"error": f"无法将 {input_path} 转换为 Markdown"}

        # Step 2: 数据源路由
        decision = self.router.route(str(md_path))
        print(f"路由决策: {decision.target_skill} (置信度 {decision.confidence:.0%})")
        print(f"  理由: {decision.reasoning}")

        # Step 3: 对应流水线构建
        if decision.target_skill == "qa_kb":
            return self._build_qa_kb(md_path, out, name, default_category)
        elif decision.target_skill == "case_kb":
            return self._build_case_kb(md_path, out, name)
        elif decision.target_skill == "book_kb":
            return self._build_book_kb(md_path, out, name, decision.book_type)
        elif decision.target_skill == "agentic":
            return self._build_agentic(path, out, name)
        else:  # direct
            return self._build_direct(md_path, out)

    def build_batch(
        self,
        input_dir: str,
        output_dir: str,
        skip_parse: bool = False,
    ) -> List[Dict[str, Any]]:
        """批量构建：对目录下每个文件分别路由和构建"""
        dir_path = Path(input_dir)
        if not dir_path.is_dir():
            print(f"输入不是目录: {input_dir}")
            return []

        files = []
        for ext in ("*.pdf", "*.docx", "*.doc", "*.md", "*.txt", "*.json",
                     "*.png", "*.jpg", "*.jpeg"):
            files.extend(dir_path.glob(ext))

        print(f"发现 {len(files)} 个文件")
        results = []
        for f in files:
            print(f"\n{'='*60}")
            print(f"处理: {f.name}")
            print(f"{'='*60}")
            name = f.stem
            out = Path(output_dir) / f.stem
            result = self.build(str(f), str(out), name=name, skip_parse=skip_parse)
            result["input_file"] = str(f)
            results.append(result)

        return results

    # ─── 格式路由 + 解析 ───

    def _ensure_markdown(self, path: Path, skip_parse: bool = False) -> Optional[Path]:
        """确保输入是 Markdown 格式；若不是则调用 parser_adapter 转换"""
        if path.is_dir():
            # 目录：找其中的 md 文件，或转换所有非 md 文件
            md_files = list(path.glob("*.md"))
            if md_files:
                return path  # 返回目录，由流水线处理
            # 没有 md，尝试转换目录下所有文件
            return self._parse_directory(path)

        suffix = path.suffix.lower()
        if suffix in (".md", ".txt", ".markdown"):
            return path

        if skip_parse:
            print(f"跳过解析，但文件不是 md: {path}")
            return None

        # 调用 parser_adapter 转换
        print(f"解析非 md 文件: {path.name}")
        temp_dir = path.parent / f"_parse_temp_{path.stem}"
        temp_dir.mkdir(exist_ok=True)

        try:
            result = subprocess.run(
                [sys.executable, str(_SCRIPT_DIR / "parser_adapter.py"),
                 str(path), "-o", str(temp_dir)],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"解析失败: {result.stderr}", file=sys.stderr)
                return None

            md_files = list(temp_dir.glob("*.md"))
            if not md_files:
                print("解析后未找到 md 文件", file=sys.stderr)
                return None

            # 单文件：返回 md 文件路径
            if len(md_files) == 1:
                return md_files[0]
            # 多文件：返回目录
            return temp_dir

        except subprocess.TimeoutExpired:
            print("解析超时", file=sys.stderr)
            return None
        except Exception as e:
            print(f"解析异常: {e}", file=sys.stderr)
            return None

    def _parse_directory(self, dir_path: Path) -> Optional[Path]:
        """转换目录下所有非 md 文件"""
        temp_dir = dir_path / "_parsed_md"
        temp_dir.mkdir(exist_ok=True)

        for f in dir_path.iterdir():
            if f.suffix.lower() in (".md", ".txt") or f.name.startswith("."):
                continue
            if f.is_dir():
                continue
            try:
                subprocess.run(
                    [sys.executable, str(_SCRIPT_DIR / "parser_adapter.py"),
                     str(f), "-o", str(temp_dir)],
                    capture_output=True, text=True, timeout=120,
                )
            except Exception:
                continue

        md_files = list(temp_dir.glob("*.md"))
        return temp_dir if md_files else None

    # ─── 各流水线构建 ───

    def _build_qa_kb(
        self, md_path: Path, out_dir: Path, name: str, default_category: str
    ) -> Dict[str, Any]:
        """构建问答知识库"""
        from qa_kb import QAKnowledgeBase

        kb = QAKnowledgeBase(str(out_dir))
        if not (out_dir / "config.yaml").exists():
            kb.init(name or "问答知识库")

        if md_path.is_dir():
            count = kb.add_batch(str(md_path), default_category=default_category)
        else:
            count = kb.add_file(str(md_path), default_category=default_category)
            kb.rebuild_indices()

        stats = kb.stats()
        return {
            "kb_type": "qa_kb",
            "output_dir": str(out_dir),
            "qa_count": stats.get("total_qa", 0),
            "has_indices": stats.get("has_indices", False),
            "categories": stats.get("categories", {}),
        }

    def _build_case_kb(self, md_path: Path, out_dir: Path, name: str) -> Dict[str, Any]:
        """构建裁判文书知识库"""
        from judgment_kb import JudgmentKnowledgeBase

        kb = JudgmentKnowledgeBase(str(out_dir))
        if not (out_dir / "config.yaml").exists():
            kb.init(name or "裁判文书知识库")

        if md_path.is_dir():
            kb.add_batch(str(md_path))
        else:
            kb.add(str(md_path))
            kb.rebuild_indices()

        stats = kb.stats()
        return {
            "kb_type": "case_kb",
            "output_dir": str(out_dir),
            "judgment_count": stats.get("total_judgments", 0),
            "courts": stats.get("court_count", 0),
            "causes": stats.get("cause_count", 0),
        }

    def _build_book_kb(
        self, md_path: Path, out_dir: Path, name: str, book_type: str
    ) -> Dict[str, Any]:
        """构建书籍知识库（编排 legal_kb.py 全流程）"""
        # book_kb 流程较复杂（拆分→合并→索引→检索），
        # 这里调用 merge_md + legal_kb build-search-index
        import subprocess

        out_dir.mkdir(parents=True, exist_ok=True)

        # 合并入库
        cmd = [
            sys.executable, str(_SCRIPT_DIR / "merge_md.py"),
            str(md_path) if not md_path.is_dir() else str(md_path),
            "-o", str(out_dir),
            "--name", name or "法律书籍知识库",
            "--legal", "--clean",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return {"error": f"合并入库失败: {result.stderr[:500]}"}

        # 构建检索索引
        cmd2 = [
            sys.executable, str(_SCRIPT_DIR / "legal_kb.py"),
            "build-search-index",
        ]
        if name:
            cmd2.extend(["--book", name])
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=300,
                                 cwd=str(out_dir))

        return {
            "kb_type": "book_kb",
            "book_type": book_type,
            "output_dir": str(out_dir),
            "has_index": (out_dir / "_vectors.faiss").exists()
                         or (out_dir / "_bm25_corpus.json").exists(),
        }

    def _build_agentic(self, source_path: Path, out_dir: Path, name: str) -> Dict[str, Any]:
        """Agentic 模式：转换到缓存目录"""
        cache_dir = out_dir / ".agentic_cache" / (name or source_path.stem)
        cache_dir.mkdir(parents=True, exist_ok=True)

        if source_path.is_file() and source_path.suffix.lower() not in (".md", ".txt"):
            subprocess.run(
                [sys.executable, str(_SCRIPT_DIR / "parser_adapter.py"),
                 str(source_path), "-o", str(cache_dir)],
                capture_output=True, text=True, timeout=120,
            )
        elif source_path.is_file():
            shutil.copy2(str(source_path), str(cache_dir / source_path.name))

        md_count = len(list(cache_dir.glob("*.md")))
        return {
            "kb_type": "agentic",
            "cache_dir": str(cache_dir),
            "md_count": md_count,
        }

    def _build_direct(self, md_path: Path, out_dir: Path) -> Dict[str, Any]:
        """方法论/参考文档：直接放置"""
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / md_path.name
        shutil.copy2(str(md_path), str(dest))
        return {
            "kb_type": "direct",
            "output_dir": str(out_dir),
            "file": str(dest),
        }


# ─── CLI ───

def main():
    parser = argparse.ArgumentParser(
        description="法律知识库工厂 — 一键路由 + 构建"
    )
    subparsers = parser.add_subparsers(dest="command")

    # route 子命令
    route_p = subparsers.add_parser("route", help="只路由不构建")
    route_p.add_argument("input", help="输入文件或目录")

    # build 子命令
    build_p = subparsers.add_parser("build", help="一键构建知识库")
    build_p.add_argument("input", help="输入文件或目录")
    build_p.add_argument("--output", "-o", required=True, help="知识库输出目录")
    build_p.add_argument("--name", default="", help="知识库名称")
    build_p.add_argument("--category", default="", help="问答库默认分类")
    build_p.add_argument("--skip-parse", action="store_true", help="跳过格式解析")
    build_p.add_argument("--batch", action="store_true", help="批量构建（输入为目录）")
    build_p.add_argument("--json", action="store_true", help="JSON 输出")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    factory = KBFactory()

    if args.command == "route":
        decision = factory.route(args.input)
        print(json.dumps({
            "target_skill": decision.target_skill,
            "book_type": decision.book_type,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "suggested_params": decision.suggested_params,
        }, ensure_ascii=False, indent=2))

    elif args.command == "build":
        if args.batch:
            results = factory.build_batch(args.input, args.output, skip_parse=args.skip_parse)
        else:
            result = factory.build(
                args.input, args.output,
                name=args.name,
                default_category=args.category,
                skip_parse=args.skip_parse,
            )
            results = [result]

        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"\n{'='*60}")
            print("构建完成")
            print(f"{'='*60}")
            for r in results:
                kb_type = r.get("kb_type", "unknown")
                out = r.get("output_dir", r.get("cache_dir", ""))
                print(f"  [{kb_type}] {out}")
                if "qa_count" in r:
                    print(f"    问答对: {r['qa_count']}")
                if "judgment_count" in r:
                    print(f"    裁判文书: {r['judgment_count']}")


if __name__ == "__main__":
    main()
