#!/usr/bin/env python3
"""
法律知识库 RAG 评估脚本

评估流程：
  1. 读取 eval/legal_qa_eval.jsonl 标注集
  2. 对每条 query 调用 hybrid_search 检索
  3. 计算检索质量指标 + 生成质量指标

两套指标（自动按依赖降级）：

  A. 基础检索指标（无外部依赖，始终可用）：
     - hit_rate@k:  Top-K 结果命中 relevant_keywords 的比例
     - mrr:         平均倒数排名（首个命中结果的排名倒数）
     - recall@k:    Top-K 覆盖 relevant_keywords 的比例

  B. RAGAS 指标（需 pip install ragas，可选）：
     - faithfulness:        答案是否完全基于检索上下文
     - answer_relevance:    答案是否回答了问题
     - context_precision:   相关文档是否排在前面
     - context_recall:      答案所需信息是否都在上下文
     - answer_correctness:  答案与标准答案的匹配度

用法：
    # 基础检索评估（无需 LLM）
    python eval/eval_rag.py --kb-path ~/legal_kb/books/民法典评注

    # 指定 K 值
    python eval/eval_rag.py --kb-path ~/legal_kb/books/民法典评注 --top-k 5

    # 完整 RAGAS 评估（需安装 ragas + 配置 LLM）
    python eval/eval_rag.py --kb-path ~/legal_kb/books/民法典评注 --full

    # 对比两次检索（参数变化前后）
    python eval/eval_rag.py --kb-path ~/kb --label "rerank_enabled"

输出：
    控制台指标摘要 + eval/results/<timestamp>_<label>.json 详细结果
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"

if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

EVAL_DIR = _SCRIPT_DIR
EVAL_SET = EVAL_DIR / "legal_qa_eval.jsonl"
RESULTS_DIR = EVAL_DIR / "results"


# ─── 标注集加载 ───

def load_eval_set(path: Path = EVAL_SET) -> List[Dict[str, Any]]:
    """加载 JSONL 格式的评估集"""
    if not path.exists():
        print(f"评估集不存在: {path}")
        return []
    samples = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))
    return samples


# ─── 基础检索指标（无依赖） ───

def compute_retrieval_metrics(
    query: str,
    retrieved_snippets: List[str],
    relevant_keywords: List[str],
    top_k: int = 5,
) -> Dict[str, float]:
    """
    计算基础检索指标（基于关键词命中）。

    Args:
        query: 原始查询
        retrieved_snippets: 检索返回的文本片段列表（按相关性降序）
        relevant_keywords: 标注的相关关键词列表
        top_k: 计算 hit_rate 和 recall 的 K 值

    Returns:
        {hit_rate@k, mrr, recall@k}
    """
    if not retrieved_snippets or not relevant_keywords:
        return {"hit_rate@k": 0.0, "mrr": 0.0, "recall@k": 0.0}

    top_snippets = retrieved_snippets[:top_k]

    # hit_rate@k: Top-K 中是否有任一命中任一关键词
    hit = 0
    first_hit_rank = 0
    for rank, snippet in enumerate(top_snippets, 1):
        snippet_lower = snippet.lower()
        if any(kw.lower() in snippet_lower for kw in relevant_keywords):
            hit = 1
            if first_hit_rank == 0:
                first_hit_rank = rank
            break

    # MRR: 首个命中结果的排名倒数
    mrr = 1.0 / first_hit_rank if first_hit_rank > 0 else 0.0

    # recall@k: Top-K 覆盖的关键词比例
    combined = " ".join(top_snippets).lower()
    covered = sum(1 for kw in relevant_keywords if kw.lower() in combined)
    recall = covered / len(relevant_keywords) if relevant_keywords else 0.0

    return {
        "hit_rate@k": float(hit),
        "mrr": mrr,
        "recall@k": recall,
    }


# ─── RAGAS 指标（可选依赖） ───

def try_ragas_eval(
    query: str,
    answer: str,
    contexts: List[str],
    ground_truth: str,
) -> Dict[str, float]:
    """
    尝试用 RAGAS 计算 5 大指标。

    依赖不可用时返回空字典（调用方应跳过 RAGAS 部分）。
    """
    try:
        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevance,
            context_precision,
            context_recall,
            answer_correctness,
        )
        from datasets import Dataset
    except ImportError:
        return {}

    try:
        data = Dataset.from_dict({
            "question": [query],
            "answer": [answer],
            "contexts": [contexts],
            "ground_truth": [ground_truth],
        })
        result = evaluate(
            data,
            metrics=[
                faithfulness,
                answer_relevance,
                context_precision,
                context_recall,
                answer_correctness,
            ],
        )
        return {k: float(v) for k, v in result.items()}
    except Exception as e:
        print(f"  [RAGAS] 评估失败: {e}")
        return {}


# ─── 主评估流程 ───

def run_evaluation(
    kb_path: str,
    top_k: int = 5,
    full: bool = False,
    label: str = "",
) -> Dict[str, Any]:
    """
    对评估集执行检索评估。

    Args:
        kb_path: 知识库路径
        top_k: 检索 Top-K
        full: 是否启用 RAGAS 完整评估
        label: 结果标签（用于对比实验）

    Returns:
        评估结果汇总
    """
    samples = load_eval_set()
    if not samples:
        return {"error": "评估集为空"}

    # 延迟导入检索引擎
    try:
        from hybrid_search import HybridSearch
    except ImportError as e:
        return {"error": f"无法导入 HybridSearch: {e}"}

    searcher = HybridSearch(Path(kb_path))

    results = []
    for i, sample in enumerate(samples, 1):
        query = sample["query"]
        relevant_keywords = sample.get("relevant_keywords", [])
        ground_truth = sample.get("ground_truth_answer", "")

        print(f"\n[{i}/{len(samples)}] {query}")

        # 执行检索
        try:
            search_result = searcher.search_by_query(query, use_ai=False)
        except Exception as e:
            print(f"  检索异常: {e}")
            search_result = {"results": []}

        # 提取检索片段
        snippets = []
        for book_result in search_result.get("results", []):
            for match in book_result.get("top_matches", []):
                snippets.extend(match.get("snippets", []))

        # 基础检索指标
        metrics = compute_retrieval_metrics(
            query, snippets, relevant_keywords, top_k=top_k
        )
        print(f"  hit@{top_k}={metrics['hit_rate@k']:.0f} "
              f"mrr={metrics['mrr']:.2f} "
              f"recall@{top_k}={metrics['recall@k']:.2f}")

        # RAGAS 指标（可选）
        ragas_metrics = {}
        if full:
            answer = search_result.get("suggested_prompt", "")  # 简化：用检索上下文
            ragas_metrics = try_ragas_eval(
                query, answer, snippets[:top_k], ground_truth
            )
            if ragas_metrics:
                print(f"  RAGAS: " + " ".join(
                    f"{k}={v:.2f}" for k, v in ragas_metrics.items()
                ))

        results.append({
            "query": query,
            "category": sample.get("category", ""),
            "retrieved_count": len(snippets),
            "metrics": {**metrics, **ragas_metrics},
        })

    # 汇总
    summary = summarize(results)
    print("\n" + "=" * 60)
    print("评估汇总")
    print("=" * 60)
    for k, v in summary.items():
        print(f"  {k}: {v:.4f}")

    # 保存结果
    save_result(summary, results, label, kb_path)

    return {"summary": summary, "details": results}


def summarize(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """汇总所有样本的指标平均值"""
    if not results:
        return {}
    metric_keys = set()
    for r in results:
        metric_keys.update(r["metrics"].keys())

    summary = {}
    for key in metric_keys:
        values = [r["metrics"][key] for r in results if key in r["metrics"]]
        if values:
            summary[key] = sum(values) / len(values)
    return summary


def save_result(
    summary: Dict[str, float],
    details: List[Dict[str, Any]],
    label: str,
    kb_path: str,
) -> Path:
    """保存评估结果到文件"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    label_suffix = f"_{label}" if label else ""
    out_path = RESULTS_DIR / f"{ts}{label_suffix}.json"

    output = {
        "timestamp": ts,
        "kb_path": kb_path,
        "label": label,
        "summary": summary,
        "sample_count": len(details),
        "details": details,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
    return out_path


# ─── CLI ───

def main():
    parser = argparse.ArgumentParser(
        description="法律知识库 RAG 评估脚本"
    )
    parser.add_argument("--kb-path", required=True, help="知识库路径")
    parser.add_argument("--top-k", type=int, default=5, help="检索 Top-K")
    parser.add_argument("--full", action="store_true", help="启用 RAGAS 完整评估")
    parser.add_argument("--label", default="", help="结果标签（用于对比实验）")
    args = parser.parse_args()

    run_evaluation(
        kb_path=args.kb_path,
        top_k=args.top_k,
        full=args.full,
        label=args.label,
    )


if __name__ == "__main__":
    main()
