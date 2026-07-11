#!/usr/bin/env python3
"""
Legal Knowledge Base - 主入口脚本
复用 pdf-split-converter 核心逻辑，添加质量校验和增强检索
"""

import argparse
import os
import sys
import json
import yaml
from pathlib import Path
from datetime import datetime

# 让本 scripts/ 目录下的模块可直接 import
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quality_checker import QualityChecker
from enhanced_index import EnhancedIndex, ALL_BOOK_TYPES
from hybrid_search import HybridSearch


# 中文友好类型 → EnhancedIndex 标准 book_type 的映射
_BOOK_TYPE_ALIAS = {
    "专著": "monograph",
    "教科书": "textbook",
    "评注": "code_commentary",
    "法典评注": "code_commentary",
    "司法解释": "judicial_interpretation",
    "司法解释适用": "judicial_interpretation",
    "案例汇编": "case_compilation",
    "案例": "case_compilation",
    "法规汇编": "statute_compilation",
    "法规": "statute_compilation",
    "实务指引": "practice_guide",
    "实务": "practice_guide",
}


def _normalize_book_type(user_type):
    """把中文/别名映射到 enhanced_index.ALL_BOOK_TYPES 中的标准值。"""
    if user_type in ALL_BOOK_TYPES:
        return user_type
    alias = _BOOK_TYPE_ALIAS.get(user_type)
    if alias:
        return alias
    return "monograph"  # 兜底


class LegalKnowledgeBase:
    """法律知识库主类"""
    
    def __init__(self, kb_path=None):
        self.kb_path = Path(kb_path) if kb_path else Path.cwd() / "legal_kb"
        self.config = self._load_config()
        self.quality_checker = QualityChecker()
        self.enhanced_index = EnhancedIndex(self.kb_path)
        self.hybrid_search = HybridSearch(self.kb_path)
    
    def _load_config(self):
        """加载配置文件"""
        config_path = self.kb_path / "config.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        return self._default_config()
    
    def _default_config(self):
        """默认配置"""
        return {
            "knowledge_base": {
                "name": "法律知识库",
                "path": str(self.kb_path)
            },
            "processing": {
                "split_mode": "bookmark",
                "ocr_enabled": True,
                "quality_check": {
                    "enabled": True,
                    "ocr_confidence_threshold": 0.85,
                    "check_chapter_continuity": True
                },
                "enhanced_index": {
                    "extract_articles": True,
                    "extract_scholars": True,
                    "build_citation_graph": True
                }
            },
            "search": {
                "default_mode": "hybrid",
                "api_enhancement": {
                    "enabled": False,
                    "provider": "claude",
                    "api_key": ""
                }
            }
        }
    
    def init(self, name, path=None):
        """初始化知识库"""
        if path:
            self.kb_path = Path(path)
        
        # 创建目录结构
        dirs = ["books", "indices", "cache", "logs"]
        for d in dirs:
            (self.kb_path / d).mkdir(parents=True, exist_ok=True)
        
        # 保存配置
        self.config["knowledge_base"]["name"] = name
        self.config["knowledge_base"]["path"] = str(self.kb_path)
        
        config_path = self.kb_path / "config.yaml"
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.config, f, allow_unicode=True, sort_keys=False)
        
        # 创建主索引
        main_index = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "books": [],
            "total_articles": 0,
            "total_scholars": 0
        }
        
        with open(self.kb_path / "indices" / "main_index.json", 'w', encoding='utf-8') as f:
            json.dump(main_index, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 知识库 '{name}' 初始化成功")
        print(f"📁 路径: {self.kb_path}")
        return True
    
    def add(
        self,
        pdf_path,
        author=None,
        book_type="专著",
        year=None,
        toc_articles=None,
        toc_chapters=None,
        toc_cases=None,
        toc_topics=None,
        toc_statutes=None,
    ):
        """添加书籍到知识库

        Args:
            pdf_path: PDF 文件路径
            author: 作者
            book_type: 书籍类型（可用中文别名，会被 _normalize_book_type 归一化）
            year: 出版年份
            toc_articles: 目录声明的条文号列表（法典评注/司法解释类）
            toc_chapters: 目录声明的章节标题（专著/教科书类）
            toc_cases: 目录声明的案例（案例汇编类）
            toc_topics: 目录声明的专题（实务指引类）
            toc_statutes: 目录声明的法规（法规汇编类）
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            print(f"❌ 文件不存在: {pdf_path}")
            return False

        book_name = pdf_path.stem
        normalized_type = _normalize_book_type(book_type)
        print(f"📚 开始处理: {book_name} (类型: {book_type} → {normalized_type})")

        # Step 1: PDF拆分（复用 pdf-split-converter）
        print("  Step 1: PDF拆分...")
        split_dir = self.kb_path / "cache" / f"split_{book_name}"
        if not self._split_pdf(pdf_path, split_dir):
            return False

        # Step 2: MinerU转换
        print("  Step 2: MinerU转换...")
        md_dir = self.kb_path / "cache" / f"md_{book_name}"
        if not self._convert_to_md(split_dir, md_dir):
            return False

        # Step 3: 质量校验（新增）
        if self.config["processing"]["quality_check"]["enabled"]:
            print("  Step 3: 质量校验...")
            quality_report = self.quality_checker.check(md_dir)
            if not self._handle_quality_report(quality_report):
                return False

        # Step 4: 增强索引（新增）
        print("  Step 4: 生成增强索引...")

        # 条文驱动型必须有 toc_articles；如果调用方没传，尝试从 md 标题里扫描
        if normalized_type in ("code_commentary", "judicial_interpretation") and not toc_articles:
            toc_articles = self._auto_scan_toc_articles(md_dir)
            if toc_articles:
                print(f"     ℹ️  自动扫描到 {len(toc_articles)} 个结构条文号（推荐调用方显式传入 toc_articles 以确保准确）")
            else:
                print("     ⚠️  未提供 toc_articles 且自动扫描失败，降级为 monograph 处理")
                normalized_type = "monograph"

        # 组装 build() 参数
        build_kwargs = {
            "md_dir": md_dir,
            "book_info": {
                "name": book_name,
                "author": author,
                "type": book_type,
                "year": year,
            },
            "book_type": normalized_type,
        }
        if normalized_type in ("code_commentary", "judicial_interpretation"):
            build_kwargs["toc_articles"] = toc_articles or []
        elif normalized_type in ("monograph", "textbook"):
            if toc_chapters:
                build_kwargs["toc_chapters"] = toc_chapters
        elif normalized_type == "case_compilation":
            build_kwargs["toc_cases"] = toc_cases or []
        elif normalized_type == "statute_compilation":
            build_kwargs["toc_statutes"] = toc_statutes or []
        elif normalized_type == "practice_guide":
            build_kwargs["toc_topics"] = toc_topics or []

        try:
            book_index = self.enhanced_index.build(**build_kwargs)
        except ValueError as e:
            # 缺 TOC 参数等强校验错误：给出清晰指引后退回 monograph
            print(f"     ⚠️  增强索引构建失败：{e}")
            print(f"     ➜ 请在 add() 调用中显式传入对应 TOC 参数，或使用 --type 专著/monograph")
            build_kwargs["book_type"] = "monograph"
            for k in ("toc_articles", "toc_cases", "toc_statutes", "toc_topics", "toc_chapters"):
                build_kwargs.pop(k, None)
            book_index = self.enhanced_index.build(**build_kwargs)
        
        # Step 5: 合并入库
        print("  Step 5: 合并入库...")
        book_output_dir = self.kb_path / "books" / book_name
        if not self._merge_to_kb(md_dir, book_index, book_output_dir):
            return False
        
        # 更新主索引
        self._update_main_index(book_name, author, book_type, book_index)
        
        # 清理缓存
        import shutil
        shutil.rmtree(split_dir, ignore_errors=True)
        shutil.rmtree(md_dir, ignore_errors=True)
        
        print(f"✅ '{book_name}' 添加成功!")
        print(f"   - 法条数: {book_index.get('article_count', 0)}")
        print(f"   - 学者观点: {book_index.get('scholar_view_count', 0)}")
        print(f"   - 页数: {book_index.get('page_count', 0)}")
        return True
    
    def _split_pdf(self, pdf_path, output_dir):
        """PDF 拆分 - 直接调用 split_pdf 模块的构建块，绕过其 CLI 层。

        v2 修复：早前实现调用 split_pdf.main() 会重新解析 sys.argv，导致传入参数完全失效。
        这里改为直接调用 group_by_bookmarks / group_by_auto + split_pdf 函数。
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            import split_pdf as sp
            from pypdf import PdfReader

            reader = PdfReader(str(pdf_path))
            total_pages = len(reader.pages)
            mode = self.config["processing"].get("split_mode", "bookmark")
            chunk_size = self.config["processing"].get("chunk_size", sp.DEFAULT_CHUNK_SIZE)
            overlap = self.config["processing"].get("overlap", sp.DEFAULT_OVERLAP)

            # 生成分段
            bookmarks = sp.get_bookmarks_flat(reader)
            if mode == "bookmark" and bookmarks:
                segments = sp.group_by_bookmarks(
                    bookmarks, total_pages,
                    target_level=self.config["processing"].get("bookmark_level", 1),
                    max_pages=chunk_size,
                    overlap=overlap,
                )
            else:
                if mode == "bookmark" and not bookmarks:
                    print("     ⚠️  未发现书签，自动切换到 auto 模式")
                segments = sp.group_by_auto(total_pages, chunk_size, overlap)

            if not segments:
                raise RuntimeError("未能生成有效的拆分方案")

            # 校验覆盖完整性（信息性）
            complete, missing = sp.verify_coverage(segments, total_pages)
            if not complete:
                print(f"     ⚠️  拆分方案未完全覆盖，缺失 {len(missing)} 页")

            # 执行拆分
            source_name = pdf_path.stem
            manifest_items = sp.split_pdf(reader, segments, str(output_dir), source_name)

            # 写清单
            manifest_path = output_dir / "split_manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump({
                    "source": str(pdf_path.resolve()),
                    "source_name": source_name,
                    "total_pages": total_pages,
                    "split_mode": mode,
                    "chunk_size": chunk_size,
                    "overlap_pages": overlap,
                    "coverage_complete": complete,
                    "files": manifest_items,
                }, f, ensure_ascii=False, indent=2)

            print(f"     ✅ 拆分完成：{len(manifest_items)} 个片段 → {output_dir}")
            return True
        except Exception as e:
            print(f"     ⚠️  拆分失败: {e}")
            # 降级：整个 PDF 作为一个文件
            import shutil
            shutil.copy(pdf_path, output_dir / f"000_{pdf_path.stem}.pdf")
            return True
    
    def _convert_to_md(self, split_dir, md_dir):
        """PDF → Markdown 转换 - 调用 parser_adapter 走用户配置的解析后端。

        v2 修复：早前实现只是生成 conversion_manifest.json 让用户手动跑 MinerU，
        导致 book_kb 流水线端到端不通。现在直接调用 ParserAdapter，按
        parser-backends.yaml 里的 default_order 依次尝试后端。
        """
        md_dir = Path(md_dir)
        md_dir.mkdir(parents=True, exist_ok=True)

        pdf_files = sorted(Path(split_dir).glob("*.pdf"))
        if not pdf_files:
            print("     ⚠️  未找到 PDF 文件")
            return False

        print(f"     发现 {len(pdf_files)} 个 PDF 片段，开始解析")

        # 尝试加载 parser adapter
        adapter = None
        try:
            from parser_adapter import ParserAdapter
            adapter = ParserAdapter()
        except FileNotFoundError as e:
            print(f"     ⚠️  未配置 parser-backends.yaml：{e}")
            print(f"     ➜ 请先 cp assets/parser-backends.example.yaml assets/parser-backends.yaml 并填写 API key")
            self._write_manual_manifest(pdf_files, md_dir)
            return False
        except Exception as e:
            print(f"     ⚠️  加载 parser_adapter 失败：{e}")
            self._write_manual_manifest(pdf_files, md_dir)
            return False

        # 逐个 PDF 调用适配器
        success_count = 0
        failed = []
        for pdf in pdf_files:
            try:
                result = adapter.parse_to_markdown(str(pdf), outdir=str(md_dir))
                if result.ok and result.output_path:
                    success_count += 1
                    print(f"       ✓ {pdf.name} → {result.output_path.name} "
                          f"[{result.backend}, {result.elapsed_ms}ms]")
                else:
                    failed.append((pdf.name, result.stderr[:200]))
            except Exception as e:
                failed.append((pdf.name, str(e)[:200]))

        print(f"     ✅ 成功 {success_count}/{len(pdf_files)}")
        if failed:
            for name, err in failed[:5]:
                print(f"       ✗ {name}: {err}")
            if len(failed) > 5:
                print(f"       … 另 {len(failed)-5} 个失败")

        # 至少有一个成功即视为可继续
        return success_count > 0

    def _write_manual_manifest(self, pdf_files, md_dir):
        """降级路径：生成清单让用户手动跑外部工具再放回 md_dir。"""
        manifest_path = md_dir / "conversion_manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump({
                "pdf_files": [str(f) for f in pdf_files],
                "output_dir": str(md_dir),
                "status": "pending",
                "hint": "请手动用 MinerU/百炼/合合等外部工具把这些 PDF 转成 Markdown，然后放回此目录",
            }, f, ensure_ascii=False, indent=2)
        print(f"     📄 已生成手动转换清单: {manifest_path}")

    def _auto_scan_toc_articles(self, md_dir):
        """扫描 md_dir 下所有 markdown 文件的标题行，提取"第X条"作为 TOC。

        仅将 Markdown 标题（以 # 开头）或独立成行的"第X条"视为结构条文号，
        避免混入正文中引用的其他法律的条文号。
        """
        import re

        md_dir = Path(md_dir)
        pattern_heading = re.compile(
            r"^\s*#{1,6}\s*第([一二三四五六七八九十百千零\d]+)条"
        )
        pattern_line_start = re.compile(
            r"^\s*第([一二三四五六七八九十百千零\d]+)条\s*[【\[]?"
        )

        def _to_int(s):
            if s.isdigit():
                return int(s)
            m = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,
                 '八':8,'九':9,'十':10,'百':100,'千':1000}
            total, temp = 0, 0
            for ch in s:
                v = m.get(ch)
                if v is None:
                    return None
                if v >= 10:
                    total += (temp or 1) * v
                    temp = 0
                else:
                    temp = temp * 10 + v
            return total + temp if (total + temp) > 0 else None

        found = set()
        for md in sorted(md_dir.glob("**/*.md")):
            try:
                for line in md.read_text(encoding='utf-8').splitlines():
                    m = pattern_heading.match(line) or pattern_line_start.match(line)
                    if m:
                        n = _to_int(m.group(1))
                        if n is not None and 1 <= n <= 5000:
                            found.add(n)
            except Exception:
                continue

        return sorted(found)

    def _handle_quality_report(self, report):
        """处理质量报告"""
        if report["overall_status"] == "error":
            print(f"     ❌ 质量检查未通过:")
            for issue in report["issues"]:
                print(f"        - {issue}")
            return False
        
        if report["overall_status"] == "warning":
            print(f"     ⚠️  发现警告:")
            for warning in report["warnings"]:
                print(f"        - {warning}")
            print(f"     继续处理，但建议后续人工复核")
        
        return True
    
    def _merge_to_kb(self, md_dir, book_index, output_dir):
        """合并到知识库"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存书籍索引
        with open(output_dir / "_book_index.json", 'w', encoding='utf-8') as f:
            json.dump(book_index, f, ensure_ascii=False, indent=2)
        
        # 复制Markdown文件
        import shutil
        md_files = sorted(md_dir.glob("*.md"))
        for md_file in md_files:
            shutil.copy(md_file, output_dir / md_file.name)
        
        return True
    
    def _update_main_index(self, book_name, author, book_type, book_index):
        """更新主索引"""
        main_index_path = self.kb_path / "indices" / "main_index.json"
        with open(main_index_path, 'r', encoding='utf-8') as f:
            main_index = json.load(f)
        
        book_entry = {
            "name": book_name,
            "author": author,
            "type": book_type,
            "added_at": datetime.now().isoformat(),
            "article_count": book_index.get("article_count", 0),
            "scholar_view_count": book_index.get("scholar_view_count", 0),
            "page_count": book_index.get("page_count", 0)
        }
        
        # 去重更新
        main_index["books"] = [b for b in main_index["books"] if b["name"] != book_name]
        main_index["books"].append(book_entry)
        main_index["total_articles"] = sum(b.get("article_count", 0) for b in main_index["books"])
        main_index["total_scholars"] = len(set(b.get("author") for b in main_index["books"] if b.get("author")))
        
        with open(main_index_path, 'w', encoding='utf-8') as f:
            json.dump(main_index, f, ensure_ascii=False, indent=2)
    
    def search(self, article=None, query=None, scholar=None, topic=None, book=None):
        """检索入口"""
        if article:
            return self.hybrid_search.search_by_article(article, book)
        elif query:
            return self.hybrid_search.search_by_query(query, book)
        elif scholar and topic:
            return self.hybrid_search.search_scholar_view(scholar, topic, book)
        else:
            print("❌ 请指定检索条件: --article, --query, 或 --scholar + --topic")
            return None
    
    def verify(self, book=None):
        """质量验证"""
        if book:
            book_dir = self.kb_path / "books" / book
            if not book_dir.exists():
                print(f"❌ 书籍不存在: {book}")
                return False
            
            print(f"🔍 验证书籍: {book}")
            # 重新运行质量检查
            report = self.quality_checker.check(book_dir)
            
            # 保存报告
            report_path = self.kb_path / "logs" / f"verify_{book}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            print(f"📄 验证报告已保存: {report_path}")
            return True
        else:
            # 验证整个知识库
            print("🔍 验证整个知识库...")
            main_index_path = self.kb_path / "indices" / "main_index.json"
            with open(main_index_path, 'r', encoding='utf-8') as f:
                main_index = json.load(f)
            
            for book_entry in main_index.get("books", []):
                self.verify(book_entry["name"])
            
            return True
    
    def list_books(self):
        """列出所有书籍"""
        main_index_path = self.kb_path / "indices" / "main_index.json"
        if not main_index_path.exists():
            print("❌ 知识库未初始化")
            return
        
        with open(main_index_path, 'r', encoding='utf-8') as f:
            main_index = json.load(f)
        
        print(f"\n📚 知识库: {main_index.get('name', '未命名')}")
        print(f"创建时间: {main_index.get('created_at', '未知')}")
        print(f"\n共 {len(main_index.get('books', []))} 本书籍:\n")
        
        for book in main_index.get("books", []):
            print(f"  📖 {book['name']}")
            print(f"     作者: {book.get('author', '未知')}")
            print(f"     类型: {book.get('type', '未知')}")
            print(f"     法条数: {book.get('article_count', 0)}")
            print(f"     学者观点: {book.get('scholar_view_count', 0)}")
            print()
    
    def build_search_index(self, book=None):
        """
        构建 BM25 + 向量检索索引

        为指定书籍（或全部书籍）构建高级检索索引。
        索引文件保存在各书籍目录内。
        """
        books_dir = self.kb_path / "books"
        if not books_dir.exists():
            print("❌ 知识库未初始化或无书籍")
            return
        
        if book:
            book_dirs = [books_dir / book]
            if not book_dirs[0].exists():
                print(f"❌ 书籍不存在: {book}")
                return
        else:
            book_dirs = [d for d in books_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
        
        for book_dir in book_dirs:
            print(f"\n🔧 构建检索索引: {book_dir.name}")
            
            # BM25 索引
            try:
                from bm25_searcher import BM25Searcher
                bm25 = BM25Searcher()
                bm25.build_index(book_dir)
            except ImportError:
                print("  ⚠️  jieba/rank-bm25 未安装，跳过 BM25 索引")
            except Exception as e:
                print(f"  ⚠️  BM25 索引构建失败: {e}")
            
            # 向量索引
            try:
                from embedding_manager import EmbeddingManager
                em = EmbeddingManager()
                em.build_index(book_dir)
            except ImportError:
                print("  ⚠️  sentence-transformers/faiss 未安装，跳过向量索引")
            except Exception as e:
                print(f"  ⚠️  向量索引构建失败: {e}")
        
        print("\n✅ 检索索引构建完成")


def main():
    parser = argparse.ArgumentParser(description="Legal Knowledge Base - 法律知识库")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # init 命令
    init_parser = subparsers.add_parser("init", help="初始化知识库")
    init_parser.add_argument("--name", required=True, help="知识库名称")
    init_parser.add_argument("--path", help="知识库路径（默认当前目录）")
    
    # add 命令
    add_parser = subparsers.add_parser("add", help="添加书籍")
    add_parser.add_argument("pdf_path", help="PDF文件路径")
    add_parser.add_argument("--author", help="作者")
    add_parser.add_argument(
        "--type", default="专著",
        help=("书籍类型：monograph(专著)/textbook(教科书)/code_commentary(评注)/"
              "judicial_interpretation(司法解释)/case_compilation(案例汇编)/"
              "statute_compilation(法规汇编)/practice_guide(实务指引)")
    )
    add_parser.add_argument("--year", help="出版年份")
    add_parser.add_argument(
        "--toc-articles",
        help='结构条文号：范围"1-69"、逗号"1,3,5"、或"@path/to/list.txt"（每行一个数字）'
    )
    add_parser.add_argument(
        "--toc-chapters",
        help='章节标题：逗号分隔、或"@path/to/list.txt"（每行一个标题）'
    )
    add_parser.add_argument(
        "--toc-cases",
        help='案例名称：逗号分隔、或"@path/to/list.txt"'
    )
    add_parser.add_argument(
        "--toc-topics",
        help='专题标题：逗号分隔、或"@path/to/list.txt"'
    )
    add_parser.add_argument(
        "--toc-statutes",
        help='法规名称：逗号分隔、或"@path/to/list.txt"'
    )
    
    # search 命令
    search_parser = subparsers.add_parser("search", help="检索")
    search_parser.add_argument("--article", help="法条编号（如：第1165条）")
    search_parser.add_argument("--query", help="自然语言查询")
    search_parser.add_argument("--scholar", help="学者姓名")
    search_parser.add_argument("--topic", help="主题")
    search_parser.add_argument("--book", help="限定书籍")
    
    # verify 命令
    verify_parser = subparsers.add_parser("verify", help="质量验证")
    verify_parser.add_argument("--book", help="指定书籍（默认全部）")
    
    # list 命令
    subparsers.add_parser("list", help="列出所有书籍")
    
    # build-search-index 命令
    build_idx_parser = subparsers.add_parser("build-search-index", help="构建 BM25 + 向量检索索引")
    build_idx_parser.add_argument("--book", help="指定书籍（默认全部）")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # 执行命令
    kb = LegalKnowledgeBase()
    
    if args.command == "init":
        kb.init(args.name, args.path)
    elif args.command == "add":
        # 解析 TOC 参数
        def _parse_int_list(spec):
            if not spec:
                return None
            if spec.startswith("@"):
                try:
                    with open(spec[1:], "r", encoding="utf-8") as f:
                        return [int(x.strip()) for x in f if x.strip().isdigit()]
                except Exception as e:
                    print(f"⚠️  读取 {spec[1:]} 失败: {e}")
                    return None
            if "-" in spec and "," not in spec:
                parts = spec.split("-")
                if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    return list(range(int(parts[0]), int(parts[1]) + 1))
            return [int(x.strip()) for x in spec.split(",") if x.strip().isdigit()]

        def _parse_str_list(spec):
            if not spec:
                return None
            if spec.startswith("@"):
                try:
                    with open(spec[1:], "r", encoding="utf-8") as f:
                        return [line.strip() for line in f if line.strip()]
                except Exception as e:
                    print(f"⚠️  读取 {spec[1:]} 失败: {e}")
                    return None
            return [x.strip() for x in spec.split(",") if x.strip()]

        kb.add(
            args.pdf_path,
            author=args.author,
            book_type=args.type,
            year=args.year,
            toc_articles=_parse_int_list(getattr(args, "toc_articles", None)),
            toc_chapters=_parse_str_list(getattr(args, "toc_chapters", None)),
            toc_cases=_parse_str_list(getattr(args, "toc_cases", None)),
            toc_topics=_parse_str_list(getattr(args, "toc_topics", None)),
            toc_statutes=_parse_str_list(getattr(args, "toc_statutes", None)),
        )
    elif args.command == "search":
        result = kb.search(args.article, args.query, args.scholar, args.topic, args.book)
        if result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "verify":
        kb.verify(args.book)
    elif args.command == "list":
        kb.list_books()
    elif args.command == "build-search-index":
        kb.build_search_index(args.book)


if __name__ == "__main__":
    main()
