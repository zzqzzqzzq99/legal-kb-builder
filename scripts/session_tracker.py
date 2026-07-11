#!/usr/bin/env python3
"""
会话追踪器

记录跨会话的查询历史、缓存命中率和检索性能，
用于智能推荐 FAST/DEEP 模式。

使用方式：
    from session_tracker import SessionTracker

    tracker = SessionTracker(Path("~/.cache/clusters"))
    tracker.log_query("善意取得", mode='fast', result_count=5,
                      confidence=0.85, duration_ms=200, cache_hit=True)

    suggested = tracker.suggest_mode("善意取得")  # 'fast' or 'deep'
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SessionTracker:
    """
    会话追踪器

    Args:
        tracker_path: 追踪数据存储目录
    """

    def __init__(self, tracker_path: Path):
        self._path = Path(tracker_path)
        self._path.mkdir(parents=True, exist_ok=True)
        self._log_file = self._path / 'session_log.json'
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def log_query(
        self,
        query: str,
        mode: str,
        result_count: int,
        confidence: float,
        duration_ms: int,
        cache_hit: bool,
    ) -> None:
        """记录一次查询事件"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'query': query,
            'mode': mode,
            'result_count': result_count,
            'confidence': confidence,
            'duration_ms': duration_ms,
            'cache_hit': cache_hit,
        }
        self._entries.append(entry)
        self._save()

    def suggest_mode(self, query: str) -> str:
        """
        基于历史数据推荐 FAST 或 DEEP 模式。

        逻辑：
        - 相似查询历史中 FAST 模式置信度高 -> 推荐 fast
        - 主题全新（无相似历史） -> 推荐 deep
        - 相似查询 FAST 置信度低 -> 推荐 deep
        """
        if not self._entries:
            return 'deep'  # 无历史，保守选择

        # 查找相似查询的历史
        query_tokens = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
        similar_entries = []

        for entry in self._entries:
            entry_tokens = set(re.findall(r'[\u4e00-\u9fff]{2,}', entry['query']))
            if query_tokens and entry_tokens:
                overlap = len(query_tokens & entry_tokens) / len(query_tokens | entry_tokens)
                if overlap > 0.5:
                    similar_entries.append(entry)

        if not similar_entries:
            return 'deep'  # 全新主题

        # 分析相似查询的 FAST 模式表现
        fast_entries = [e for e in similar_entries if e['mode'] == 'fast']
        if fast_entries:
            avg_confidence = sum(e['confidence'] for e in fast_entries) / len(fast_entries)
            if avg_confidence >= 0.7:
                return 'fast'
            else:
                return 'deep'

        return 'fast'  # 有相似历史但无 fast 记录，尝试 fast

    def get_query_patterns(self) -> Dict[str, Any]:
        """分析查询历史模式"""
        if not self._entries:
            return {"total_queries": 0}

        total = len(self._entries)
        fast_count = sum(1 for e in self._entries if e['mode'] == 'fast')
        deep_count = sum(1 for e in self._entries if e['mode'] == 'deep')
        cache_hits = sum(1 for e in self._entries if e.get('cache_hit'))

        # 提取常见主题
        all_tokens: Dict[str, int] = {}
        for entry in self._entries:
            tokens = re.findall(r'[\u4e00-\u9fff]{2,4}', entry['query'])
            for t in tokens:
                all_tokens[t] = all_tokens.get(t, 0) + 1

        top_topics = sorted(all_tokens.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_queries": total,
            "fast_queries": fast_count,
            "deep_queries": deep_count,
            "cache_hit_rate": round(cache_hits / total, 2) if total > 0 else 0,
            "avg_confidence": round(
                sum(e['confidence'] for e in self._entries) / total, 2
            ) if total > 0 else 0,
            "avg_duration_ms": round(
                sum(e.get('duration_ms', 0) for e in self._entries) / total
            ) if total > 0 else 0,
            "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        }

    def get_performance_report(self) -> Dict[str, Any]:
        """生成性能报告"""
        patterns = self.get_query_patterns()

        fast_entries = [e for e in self._entries if e['mode'] == 'fast']
        deep_entries = [e for e in self._entries if e['mode'] == 'deep']

        report = {
            **patterns,
            "fast_avg_duration_ms": round(
                sum(e.get('duration_ms', 0) for e in fast_entries) / len(fast_entries)
            ) if fast_entries else 0,
            "deep_avg_duration_ms": round(
                sum(e.get('duration_ms', 0) for e in deep_entries) / len(deep_entries)
            ) if deep_entries else 0,
            "fast_avg_confidence": round(
                sum(e['confidence'] for e in fast_entries) / len(fast_entries), 2
            ) if fast_entries else 0,
            "deep_avg_confidence": round(
                sum(e['confidence'] for e in deep_entries) / len(deep_entries), 2
            ) if deep_entries else 0,
        }

        return report

    # ─── 存储 ───

    def _load(self) -> None:
        if not self._log_file.exists():
            self._entries = []
            return
        try:
            with open(self._log_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._entries = data.get('entries', [])
        except (json.JSONDecodeError, TypeError):
            self._entries = []

    def _save(self) -> None:
        data = {
            'version': 'v1',
            'updated_at': datetime.now().isoformat(),
            'entry_count': len(self._entries),
            'entries': self._entries[-1000:],  # 保留最近 1000 条
        }
        # 原子写入：先写临时文件再 rename，防止中途中断损坏数据
        import os
        tmp_path = self._log_file.with_suffix('.json.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(str(tmp_path), str(self._log_file))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        import tempfile, shutil
        tmp = Path(tempfile.mkdtemp())

        tracker = SessionTracker(tmp)
        tracker.log_query("善意取得", 'fast', 5, 0.85, 200, True)
        tracker.log_query("违约责任", 'deep', 8, 0.90, 5000, False)
        tracker.log_query("善意取得构成要件", 'fast', 3, 0.75, 300, True)

        mode = tracker.suggest_mode("善意取得的法律效果")
        print(f"Suggested mode: {mode}")

        patterns = tracker.get_query_patterns()
        print(f"Patterns: {json.dumps(patterns, ensure_ascii=False)}")

        report = tracker.get_performance_report()
        print(f"Report: {json.dumps(report, ensure_ascii=False)}")

        shutil.rmtree(tmp)
        print("All tests completed.")
    else:
        print("用法: python session_tracker.py --test")
