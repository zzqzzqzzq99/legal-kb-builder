#!/usr/bin/env python3
"""
法条关联图谱模块（GraphRAG for Legal）

从法律文本中抽取实体（法条号、法律概念、案例案号）和关系（引用、适用、解释），
构建知识图谱，支持多跳查询，作为第四路检索融入 RRF 融合。

核心能力：
  1. 实体抽取：法条号（第X条）、法律概念、案例案号
  2. 关系抽取：引用关系（A法条引用B法条）、适用关系（案例适用法条）
  3. 图谱构建：用 networkx 存储（可选依赖，未安装时降级为简单字典）
  4. 多跳查询：给定法条，找引用它的判例/学说
  5. 社区检测：Leiden/Louvain 算法发现法条主题聚类（可选）

存储格式：
  - _graph.json: 图谱序列化（节点+边）
  - _graph_communities.json: 社区摘要（可选，需 networkx）

使用方式：
    from graph_rag import GraphRAG

    graph = GraphRAG()
    graph.build_from_kb(kb_path)          # 从知识库构建图谱
    results = graph.search("第311条")      # 多跳查询
    # -> [{"node": "...", "relation": "...", "depth": 1}, ...]
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# 可选依赖：networkx（用于图算法和社区检测）
try:
    import networkx as nx
    HAS_NX = True
except ImportError:
    HAS_NX = False


# ─── 常量 ───

# 法条号正则（匹配"第X条"、"第X条第Y款"、"第X条之Y"）
ARTICLE_PATTERN = re.compile(
    r'第([一二三四五六七八九十百千万零\d]+)条'
    r'(?:之([一二三四五六七八九十\d]+))?'
    r'(?:第([一二三四五六七八九十\d]+)款)?'
    r'(?:第([一二三四五六七八九十\d]+)项)?'
)

# 案例案号正则（匹配"(2023)京01民终123号"等）
CASE_NUMBER_PATTERN = re.compile(
    r'[\(（](\d{4})[\)）]'
    r'([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁]'
    r'[0-9]{2})'
    r'(民|刑|行|执|商|知|破)?'
    r'(初|终|再|抗|监)?'
    r'(\d+)号'
)

# 法律名称正则（匹配常见法律名）
LAW_NAME_PATTERN = re.compile(
    r'(中华人民共和国)?(民法典|刑法|民事诉讼法|刑事诉讼法|行政诉讼法|'
    r'合同法|物权法|侵权责任法|公司法|婚姻法|继承法|担保法|'
    r'劳动法|劳动合同法|商标法|专利法|著作权法|电子商务法|'
    r'个人信息保护法|数据安全法|网络安全法)'
)

# 中文数字转阿拉伯（统一使用 shared_utils 实现）
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from shared_utils import chinese_to_number as _chinese_to_number


def chinese_to_num(cn: str) -> int:
    """中文数字转阿拉伯数字（兼容包装：空/无法解析时返回 0）"""
    result = _chinese_to_number(cn)
    return result if result is not None else 0


class GraphRAG:
    """
    法条关联图谱检索器

    图谱结构：
      节点类型: article(法条), concept(法律概念), case(案例), law(法律名称)
      边类型: references(引用), applies(适用), explains(解释), mentions(提及)
    """

    def __init__(self):
        self._graph_data: Dict[str, Any] = {
            'nodes': {},   # {node_id: {type, label, ...}}
            'edges': [],   # [{source, target, relation, ...}]
        }
        self._nx_graph = None  # networkx 图（可选）

    # ─── 构建图谱 ───

    def build_from_kb(self, kb_path: Path) -> Dict[str, int]:
        """
        从知识库目录构建法条关联图谱。

        扫描所有 .md 文件，抽取法条号、案例案号、法律名称，
        建立引用和适用关系。

        Args:
            kb_path: 知识库根目录

        Returns:
            {"nodes": 节点数, "edges": 边数, "files": 文件数}
        """
        kb_path = Path(kb_path)
        md_files = sorted(
            f for f in kb_path.glob("*.md")
            if not f.name.startswith("_")
        )

        # 先清空
        self._graph_data = {'nodes': {}, 'edges': []}

        # 第一遍：抽取所有实体
        file_entities: Dict[str, Dict[str, List]] = {}
        for md_file in md_files:
            content = md_file.read_text(encoding='utf-8')
            entities = self._extract_entities(content)
            file_entities[md_file.name] = entities

            # 把实体加入图谱节点
            for article in entities['articles']:
                node_id = f"article:{article['full']}"
                if node_id not in self._graph_data['nodes']:
                    self._graph_data['nodes'][node_id] = {
                        'type': 'article',
                        'label': article['full'],
                        'article_num': article['num'],
                        'clause': article.get('clause'),
                        'item': article.get('item'),
                        'mentions': 0,
                    }
                self._graph_data['nodes'][node_id]['mentions'] += 1

            for case in entities['cases']:
                node_id = f"case:{case['full']}"
                if node_id not in self._graph_data['nodes']:
                    self._graph_data['nodes'][node_id] = {
                        'type': 'case',
                        'label': case['full'],
                        'year': case['year'],
                        'court': case['court'],
                        'mentions': 0,
                    }
                self._graph_data['nodes'][node_id]['mentions'] += 1

            for law in entities['laws']:
                node_id = f"law:{law}"
                if node_id not in self._graph_data['nodes']:
                    self._graph_data['nodes'][node_id] = {
                        'type': 'law',
                        'label': law,
                        'mentions': 0,
                    }
                self._graph_data['nodes'][node_id]['mentions'] += 1

        # 第二遍：建立关系（文件中同时出现的实体间建立共现关系，
        # 文件标题若是案例则建立案例→法条的适用关系）
        for md_file in md_files:
            entities = file_entities[md_file.name]

            # 案例→法条：适用关系
            for case in entities['cases']:
                for article in entities['articles']:
                    self._add_edge(
                        f"case:{case['full']}",
                        f"article:{article['full']}",
                        'applies',
                        source_file=md_file.name,
                    )

            # 法条→法律：属于关系
            for article in entities['articles']:
                for law in entities['laws']:
                    self._add_edge(
                        f"article:{article['full']}",
                        f"law:{law}",
                        'belongs_to',
                        source_file=md_file.name,
                    )

            # 法条→法条：同文档共现（可能存在引用关系）
            article_list = entities['articles']
            for i, a1 in enumerate(article_list):
                for a2 in article_list[i+1:]:
                    self._add_edge(
                        f"article:{a1['full']}",
                        f"article:{a2['full']}",
                        'co_occurs',
                        source_file=md_file.name,
                    )

        # 构建 networkx 图（用于图算法）
        if HAS_NX:
            self._build_nx_graph()

        stats = {
            'nodes': len(self._graph_data['nodes']),
            'edges': len(self._graph_data['edges']),
            'files': len(md_files),
        }
        print(f"[GraphRAG] 图谱构建完成: {stats['nodes']} 节点, {stats['edges']} 边")
        return stats

    def save(self, kb_path: Path) -> Path:
        """保存图谱到知识库目录"""
        kb_path = Path(kb_path)
        graph_path = kb_path / '_graph.json'
        with open(graph_path, 'w', encoding='utf-8') as f:
            json.dump(self._graph_data, f, ensure_ascii=False, indent=2)
        print(f"[GraphRAG] 图谱已保存: {graph_path}")
        return graph_path

    def load(self, kb_path: Path) -> bool:
        """从知识库目录加载图谱"""
        kb_path = Path(kb_path)
        graph_path = kb_path / '_graph.json'
        if not graph_path.exists():
            return False
        with open(graph_path, 'r', encoding='utf-8') as f:
            self._graph_data = json.load(f)
        if HAS_NX:
            self._build_nx_graph()
        print(f"[GraphRAG] 图谱已加载: {len(self._graph_data['nodes'])} 节点")
        return True

    # ─── 查询 ───

    def search(
        self,
        query: str,
        max_depth: int = 2,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        图谱多跳查询：从查询中抽取法条/概念，做多跳邻居检索。

        Args:
            query: 查询字符串（如"第311条"或"善意取得"）
            max_depth: 最大跳数（默认 2）
            top_k: 返回前 K 个结果

        Returns:
            [{"node_id", "label", "type", "relation", "depth", "path"}, ...]
        """
        # 从查询中抽取种子节点
        seeds = self._extract_seeds(query)
        if not seeds:
            # 尝试模糊匹配节点标签
            for nid, node in self._graph_data['nodes'].items():
                if query in node.get('label', ''):
                    seeds.append(nid)
                    break

        if not seeds:
            return []

        # 多跳 BFS 搜索
        visited = set()
        results = []
        queue = [(s, 0, []) for s in seeds]

        while queue and len(results) < top_k * 3:
            node_id, depth, path = queue.pop(0)

            if node_id in visited or depth > max_depth:
                continue
            visited.add(node_id)

            node = self._graph_data['nodes'].get(node_id)
            if not node:
                continue

            if depth > 0:  # 不把种子自身加入结果
                results.append({
                    'node_id': node_id,
                    'label': node.get('label', ''),
                    'type': node.get('type', ''),
                    'mentions': node.get('mentions', 0),
                    'depth': depth,
                    'path': path,
                })

            # 扩展邻居
            if depth < max_depth:
                for edge in self._graph_data['edges']:
                    neighbor = None
                    relation = edge.get('relation', '')
                    if edge.get('source') == node_id:
                        neighbor = edge.get('target')
                    elif edge.get('target') == node_id:
                        neighbor = edge.get('source')

                    if neighbor and neighbor not in visited:
                        new_path = path + [{'node': node_id, 'relation': relation}]
                        queue.append((neighbor, depth + 1, new_path))

        # 按深度和提及次数排序
        results.sort(key=lambda x: (x['depth'], -x['mentions']))
        return results[:top_k]

    def get_related_articles(self, article: str) -> List[Dict]:
        """获取与指定法条相关的所有节点"""
        return self.search(article, max_depth=2, top_k=20)

    def get_article_cases(self, article: str) -> List[Dict]:
        """获取适用某法条的案例"""
        results = self.search(article, max_depth=1, top_k=20)
        return [r for r in results if r.get('type') == 'case']

    # ─── 社区检测（可选，需 networkx） ───

    def detect_communities(self) -> Dict[str, List[str]]:
        """
        社区检测：发现法条主题聚类。

        需 networkx。用 Louvain 算法（nx.community.louvain_communities）。
        若不可用降级为连通分量。
        """
        if not HAS_NX or self._nx_graph is None:
            return {}

        try:
            # 尝试 Louvain（networkx >= 3.0）
            communities = nx.community.louvain_communities(self._nx_graph)
        except (AttributeError, Exception):
            # 降级：连通分量
            communities = list(nx.connected_components(self._nx_graph))

        result = {}
        for i, comm in enumerate(communities):
            nodes = list(comm)
            if len(nodes) < 2:
                continue
            result[f"community_{i}"] = {
                'size': len(nodes),
                'nodes': nodes[:20],  # 只取前20个做摘要
                'labels': [
                    self._graph_data['nodes'].get(n, {}).get('label', n)
                    for n in nodes[:10]
                ],
            }
        return result

    # ─── 内部方法 ───

    def _extract_entities(self, text: str) -> Dict[str, List]:
        """从文本中抽取实体"""
        articles = []
        for m in ARTICLE_PATTERN.finditer(text):
            num_str = m.group(1)
            num = chinese_to_num(num_str)
            articles.append({
                'full': m.group(0),
                'num': num,
                'clause': m.group(3) if m.group(3) else None,
                'item': m.group(4) if m.group(4) else None,
            })

        cases = []
        for m in CASE_NUMBER_PATTERN.finditer(text):
            cases.append({
                'full': m.group(0),
                'year': m.group(1),
                'court': m.group(2),
                'type': m.group(3) or '',
                'stage': m.group(4) or '',
                'number': m.group(5),
            })

        laws = list(set(LAW_NAME_PATTERN.findall(text)))
        # findall 返回元组（因有分组），取第二个元素（法律名）
        law_names = []
        for match in LAW_NAME_PATTERN.finditer(text):
            law_name = match.group(2)  # 第二个分组是法律名
            if law_name and law_name not in law_names:
                law_names.append(law_name)

        return {'articles': articles, 'cases': cases, 'laws': law_names}

    def _extract_seeds(self, query: str) -> List[str]:
        """从查询中抽取种子节点 ID（支持中阿数字互转匹配）"""
        seeds = []

        # 抽取法条号，并尝试中文/阿拉伯数字互转匹配
        for m in ARTICLE_PATTERN.finditer(query):
            raw = m.group(0)
            # 直接匹配
            node_id = f"article:{raw}"
            if node_id in self._graph_data['nodes']:
                seeds.append(node_id)
                continue

            # 数字归一化匹配：把查询中的法条号转成数字，再与图谱节点比对
            query_num = chinese_to_num(m.group(1))
            for nid, node in self._graph_data['nodes'].items():
                if nid.startswith('article:') and node.get('article_num') == query_num:
                    seeds.append(nid)
                    break

        # 抽取案例案号
        for m in CASE_NUMBER_PATTERN.finditer(query):
            node_id = f"case:{m.group(0)}"
            if node_id in self._graph_data['nodes']:
                seeds.append(node_id)

        # 抽取法律名
        for m in LAW_NAME_PATTERN.finditer(query):
            node_id = f"law:{m.group(2)}"
            if node_id in self._graph_data['nodes']:
                seeds.append(node_id)

        return list(dict.fromkeys(seeds))  # 去重保序

    def _add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        source_file: str = "",
    ) -> None:
        """添加边（去重）"""
        # 检查是否已存在
        for edge in self._graph_data['edges']:
            if (edge['source'] == source and edge['target'] == target
                    and edge['relation'] == relation):
                return  # 已存在，跳过
        self._graph_data['edges'].append({
            'source': source,
            'target': target,
            'relation': relation,
            'source_file': source_file,
        })

    def _build_nx_graph(self) -> None:
        """构建 networkx 图"""
        if not HAS_NX:
            return
        self._nx_graph = nx.Graph()
        for nid in self._graph_data['nodes']:
            self._nx_graph.add_node(nid)
        for edge in self._graph_data['edges']:
            self._nx_graph.add_edge(edge['source'], edge['target'])

    @property
    def node_count(self) -> int:
        return len(self._graph_data['nodes'])

    @property
    def edge_count(self) -> int:
        return len(self._graph_data['edges'])


# ─── CLI ───

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python graph_rag.py build <kb_path>          # 构建图谱")
        print("  python graph_rag.py search <kb_path> <query> # 多跳查询")
        print("  python graph_rag.py communities <kb_path>    # 社区检测")
        print("  python graph_rag.py --test                   # 自测")
        sys.exit(0)

    if sys.argv[1] == '--test':
        print(f"networkx: {'yes' if HAS_NX else 'no'}")
        # 测试实体抽取
        sample = "依据民法典第311条规定，(2023)京01民终123号案例中..."
        g = GraphRAG()
        entities = g._extract_entities(sample)
        print(f"法条: {[a['full'] for a in entities['articles']]}")
        print(f"案例: {[c['full'] for c in entities['cases']]}")
        print(f"法律: {entities['laws']}")
        # 测试中文数字转换
        print(f"'三百一十一' -> {chinese_to_num('三百一十一')}")
        print(f"'十' -> {chinese_to_num('十')}")
        print(f"'二十五' -> {chinese_to_num('二十五')}")
        print("自测完成")
        sys.exit(0)

    command = sys.argv[1]
    if command == 'build' and len(sys.argv) >= 3:
        g = GraphRAG()
        stats = g.build_from_kb(Path(sys.argv[2]))
        g.save(Path(sys.argv[2]))
        print(f"节点: {stats['nodes']}, 边: {stats['edges']}, 文件: {stats['files']}")

    elif command == 'search' and len(sys.argv) >= 4:
        g = GraphRAG()
        if not g.load(Path(sys.argv[2])):
            print("图谱不存在，请先运行 build")
            sys.exit(1)
        results = g.search(sys.argv[3])
        for r in results:
            print(f"  [d{r['depth']}] {r['type']}: {r['label']} (mentions={r['mentions']})")

    elif command == 'communities' and len(sys.argv) >= 3:
        g = GraphRAG()
        if not g.load(Path(sys.argv[2])):
            print("图谱不存在，请先运行 build")
            sys.exit(1)
        communities = g.detect_communities()
        print(f"发现 {len(communities)} 个社区:")
        for cid, info in communities.items():
            print(f"\n  {cid} (size={info['size']}):")
            for label in info['labels']:
                print(f"    - {label}")

    else:
        print("未知命令")
