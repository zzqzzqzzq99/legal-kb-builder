# Legal Knowledge Base 检索指南

## 检索方式

### 1. 法条精确检索

最常用、最准确的检索方式。

```bash
# 检索特定法条
python scripts/legal_kb.py search --article "第1165条"

# 跨书检索
python scripts/legal_kb.py search --article "第1165条"

# 限定书籍
python scripts/legal_kb.py search --article "第1165条" --book "王泽鉴民法总则"
```

支持的法条编号格式：
- 阿拉伯数字：`第1165条`
- 中文数字：`第一千百六十五条`
- 混合：`第1条`

### 2. 自然语言检索

用于理解概念、找相关学说。

```bash
# 概念理解
python scripts/legal_kb.py search --query "什么是意思表示的瑕疵"

# 学说查找
python scripts/legal_kb.py search --query "无权处分的效力争议"

# 限定书籍
python scripts/legal_kb.py search --query "表见代理构成要件" --book "王泽鉴民法总则"
```

检索策略：
1. 如果查询包含法条编号，自动转为精确检索
2. 否则进行关键词匹配
3. 返回相关段落和上下文

### 3. 学者观点检索

专门查找特定学者的观点。

```bash
# 查找学者对某问题的观点
python scripts/legal_kb.py search --scholar "王泽鉴" --topic "无权处分"

# 结合书籍限定
python scripts/legal_kb.py search --scholar "王泽鉴" --topic "物权行为" --book "民法物权"
```

## 检索结果解读

### 法条检索结果

```json
{
  "query": "第1165条",
  "normalized": "第1165条",
  "results": [
    {
      "book": "王泽鉴民法总则",
      "book_info": {
        "name": "王泽鉴民法总则",
        "author": "王泽鉴",
        "type": "评注"
      },
      "article": "第1165条",
      "occurrences": 3,
      "contents": [
        {
          "location": {"file": "001_导论.md", "line": 45},
          "content": "...第1165条规定了..."
        }
      ]
    }
  ]
}
```

### 关键词检索结果

```json
{
  "query": "无权代理",
  "keywords": ["无权代理"],
  "results": [
    {
      "book": "王泽鉴民法总则",
      "match_count": 15,
      "top_matches": [
        {
          "file": "003_代理.md",
          "score": 8.5,
          "snippets": ["...无权代理的效力..."]
        }
      ]
    }
  ]
}
```

## 高级用法

### 批量检索

```python
from scripts.hybrid_search import HybridSearch

searcher = HybridSearch("./my_kb")

# 批量法条检索
articles = ["第1165条", "第1166条", "第117条"]
for article in articles:
    result = searcher.search_by_article(article)
    print(f"{article}: {len(result['results'])} 本书提及")
```

### 结果筛选

```python
# 只取特定学者的观点
result = searcher.search_by_query("无权处分")
for book_result in result["results"]:
    book_info = book_result.get("book_info", {})
    if book_info.get("author") == "王泽鉴":
        print(f"找到王泽鉴的观点")
```

### 引用溯源

```python
# 查找某法条被引用的情况
index = json.load(open("books/王泽鉴民法总则/_book_index.json"))
citations = index["citation_graph"].get("第1165条", [])
for citation in citations:
    print(f"在 {citation['file']} 第{citation['line']}行被引用")
```

## 检索优化建议

### 1. 法条检索优先

如果知道具体法条，优先使用 `--article` 参数：
- 速度更快（直接索引查找）
- 结果更准确（100%召回）

### 2. 关键词精炼

自然语言检索时，使用专业术语：
- ✅ 好：`--query "表见代理构成要件"`
- ❌ 差：`--query "代理的问题"`

### 3. 限定范围

书籍较多时，用 `--book` 限定范围：
- 提高检索速度
- 减少无关结果

### 4. 组合检索

复杂问题分步检索：
1. 先找相关法条
2. 再找学者对该法条的评注
3. 最后找相关案例

## 常见问题

### Q: 检索不到结果？

检查：
1. 书籍是否已正确添加（`legal_kb.py list`）
2. 法条编号格式是否正确
3. 是否使用了正确的书籍名称

### Q: 结果太多？

优化：
1. 添加 `--book` 限定书籍
2. 使用更精确的法条编号
3. 组合多个关键词

### Q: 如何导出检索结果？

```bash
python scripts/legal_kb.py search --article "第1165条" > result.json
```

## 与 Claude Desktop 集成

配置 MCP：

```json
{
  "mcpServers": {
    "legal-kb": {
      "command": "python",
      "args": ["/path/to/legal_kb/scripts/mcp_server.py"],
      "env": {
        "KB_PATH": "/path/to/your/kb"
      }
    }
  }
}
```

然后在 Claude 中直接提问：
- "查一下第1165条"
- "王泽鉴老师怎么看待无权处分"
