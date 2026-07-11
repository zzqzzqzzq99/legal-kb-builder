# RAG 评估框架

对法律知识库的检索与生成质量做量化评估，支撑迭代优化（换 embedding 模型、调 chunk_size、开关 rerank 等参数前后对比）。

## 快速开始

```bash
# 基础检索评估（无需 LLM，无额外依赖）
python eval/eval_rag.py --kb-path ~/legal_kb/books/民法典评注

# 指定 K 值
python eval/eval_rag.py --kb-path ~/legal_kb/books/民法典评注 --top-k 5

# 完整 RAGAS 评估（需安装 ragas）
pip install ragas datasets
python eval/eval_rag.py --kb-path ~/legal_kb/books/民法典评注 --full

# 带标签，用于对比实验
python eval/eval_rag.py --kb-path ~/kb --label "rerank_enabled"
python eval/eval_rag.py --kb-path ~/kb --label "rerank_disabled"
```

## 两套指标

### A. 基础检索指标（始终可用，无依赖）

| 指标 | 说明 | 目标 |
|------|------|------|
| `hit_rate@k` | Top-K 结果中命中相关关键词的样本比例 | → 1.0 |
| `mrr` | 平均倒数排名（首个命中结果的排名倒数） | → 1.0 |
| `recall@k` | Top-K 覆盖相关关键词的平均比例 | → 1.0 |

基于 `relevant_keywords` 字段做关键词命中判断，不依赖 LLM，适合快速对比检索参数变化。

### B. RAGAS 指标（可选，需 `pip install ragas`）

| 指标 | 说明 | 目标 |
|------|------|------|
| `faithfulness` | 答案是否完全基于检索上下文（防幻觉） | → 1.0 |
| `answer_relevance` | 答案是否回答了问题 | → 1.0 |
| `context_precision` | 相关文档是否排在前面 | → 1.0 |
| `context_recall` | 答案所需信息是否都在上下文 | → 1.0 |
| `answer_correctness` | 答案与标准答案的匹配度 | → 1.0 |

RAGAS 评估需要 LLM（默认调用 OpenAI，可配置其他），用于深度评估生成质量。

## 评估集格式

`eval/legal_qa_eval.jsonl`，每行一个 JSON：

```json
{
  "query": "善意取得的构成要件有哪些",
  "ground_truth_answer": "善意取得需满足：受让时善意、以合理价格受让、已交付或登记...",
  "relevant_keywords": ["善意取得", "善意", "合理价格", "交付", "登记", "第311条"],
  "category": "物权"
}
```

当前内置 20 条覆盖民法典各编（物权、合同、侵权、继承、婚姻家庭、担保、总则）的标注样本。
**建议扩充到 50-100 条**以获得更稳定的统计意义。扩充时保持字段一致即可。

## 迭代优化闭环

```
1. 基线评估：python eval/eval_rag.py --kb-path ~/kb --label "baseline"
2. 调整参数（如切换 bge-m3 模型、开启 rerank、调 chunk_size）
3. 重新评估：python eval/eval_rag.py --kb-path ~/kb --label "bge_m3_rerank"
4. 对比 eval/results/ 下两次结果的 summary
5. 指标提升则采纳，下降则回退
```

### 短板诊断

| 指标低 | 可能原因 | 优化方向 |
|--------|---------|---------|
| `recall@k` 低 | 召回不足 | 增大 top_k / 换更强 embedding / 优化分块 |
| `hit_rate@k` 低 | 精排不足 | 开启 rerank / 调 RRF 权重 |
| `faithfulness` 低 | 幻觉 | 优化 prompt / 限制仅引用检索内容 |
| `context_recall` 低 | 检索缺失 | 扩充知识库 / 换 embedding 模型 |

## 结果存储

每次评估结果保存到 `eval/results/<timestamp>_<label>.json`，含：
- `summary`: 各指标平均值
- `details`: 每条样本的逐项指标
- `sample_count`: 样本数

对比实验时直接 diff 两个结果文件的 `summary` 即可。
