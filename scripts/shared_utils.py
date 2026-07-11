#!/usr/bin/env python3
"""
共享工具函数模块

将多个脚本中重复实现的工具函数统一提取到此处，避免代码漂移和维护负担。

当前消除的重复：
  - chinese_to_number: 原先在 hybrid_search.py, quality_checker.py, enhanced_index.py, merge_md.py 各有一份
  - normalize_article: 原先在 hybrid_search.py
  - YAML 配置加载: 多处零散实现
"""

import re
import yaml
from pathlib import Path
from typing import Optional, Dict, List, Any


# ─── 中文数字转换 ───

CHINESE_NUM_MAP = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
    '十': 10, '百': 100, '千': 1000, '万': 10000,
    '亿': 100000000,
}


def chinese_to_number(chinese_str: str) -> Optional[int]:
    """
    将中文数字字符串转换为阿拉伯数字。

    支持格式：
      - 纯阿拉伯数字: "123" -> 123
      - 纯中文数字: "一百二十三" -> 123
      - 含"第...条"包装: "第一百二十三条" -> 123（自动提取数字部分）
      - 支持万/亿位: "一万二千三百四十五" -> 12345

    Args:
        chinese_str: 中文数字字符串或含法条编号的字符串

    Returns:
        转换后的整数，无法解析时返回 None
    """
    if not chinese_str:
        return None

    # 如果包含"第...条"格式，提取数字部分
    match = re.search(r'第([一二三四五六七八九十百千万零\d]+)条', chinese_str)
    if match:
        num_str = match.group(1)
    else:
        # 尝试直接解析整个字符串
        num_str = chinese_str.strip()

    # 纯阿拉伯数字
    if num_str.isdigit():
        return int(num_str)

    # 中文数字转换（支持万/亿位两级累加）
    result = 0        # 最终结果
    section = 0       # 当前节（万级以内）的累计值
    temp = 0          # 当前单位以下的数字（个位累计）

    for char in num_str:
        if char not in CHINESE_NUM_MAP:
            continue
        num = CHINESE_NUM_MAP[char]
        if num >= 100000000:  # 亿
            section += temp
            result = (result + section) * num
            section = 0
            temp = 0
        elif num >= 10000:    # 万
            section += temp
            result += section * num
            section = 0
            temp = 0
        elif num >= 10:       # 十/百/千
            if temp == 0:
                temp = 1
            section += temp * num
            temp = 0
        elif num == 0:        # 零
            temp = 0
        else:                 # 一~九
            temp = temp * 10 + num if temp else num

    result += section + temp
    return result if result > 0 else None


def normalize_article(article: str) -> Optional[str]:
    """
    标准化法条编号为"第{数字}条"格式。

    Args:
        article: 法条编号字符串（如"第一百二十三条"或"第123条"）

    Returns:
        标准化后的字符串（如"第123条"），无法解析时返回 None
    """
    num = chinese_to_number(article)
    if num is not None:
        return f"第{num}条"
    return None


def number_to_chinese(num: int) -> str:
    """
    将阿拉伯数字转换为中文数字（用于搜索时的双向匹配）。

    仅支持 1-9999 范围。

    Args:
        num: 阿拉伯数字

    Returns:
        中文数字字符串
    """
    if num <= 0 or num >= 10000:
        return str(num)

    digits = '零一二三四五六七八九'

    if num < 10:
        return digits[num]
    elif num < 100:
        tens = num // 10
        ones = num % 10
        result = ''
        if tens == 1:
            result = '十'
        else:
            result = digits[tens] + '十'
        if ones > 0:
            result += digits[ones]
        return result
    elif num < 1000:
        hundreds = num // 100
        remainder = num % 100
        result = digits[hundreds] + '百'
        if remainder == 0:
            return result
        elif remainder < 10:
            result += '零' + digits[remainder]
        else:
            result += number_to_chinese(remainder)
        return result
    else:  # < 10000
        thousands = num // 1000
        remainder = num % 1000
        result = digits[thousands] + '千'
        if remainder == 0:
            return result
        elif remainder < 100:
            result += '零' + number_to_chinese(remainder)
        else:
            result += number_to_chinese(remainder)
        return result


# ─── 配置加载 ───

def load_yaml_config(path: str) -> Dict[str, Any]:
    """
    加载 YAML 配置文件。

    Args:
        path: YAML 文件路径

    Returns:
        解析后的字典，文件不存在或解析失败时返回空字典
    """
    config_path = Path(path).expanduser()
    if not config_path.exists():
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_synonym_expansion(yaml_path: str = None) -> Dict[str, List[str]]:
    """
    加载法律术语同义词扩展表。

    默认路径: <skill_root>/assets/keyword-expansion.yaml
    （相对于本文件所在 scripts/ 的父目录下 assets/）

    YAML 格式示例：
      善意取得:
        - 善意受让
        - 即时取得

    返回：
      {"善意取得": ["善意受让", "即时取得"], ...}
      同时包含反向映射：{"善意受让": ["善意取得", "即时取得"], ...}
    """
    if yaml_path is None:
        yaml_path = str(
            Path(__file__).resolve().parent.parent / "assets" / "keyword-expansion.yaml"
        )

    raw = load_yaml_config(yaml_path)
    if not raw:
        return {}

    synonym_map: Dict[str, List[str]] = {}

    for key, value in raw.items():
        # 跳过特殊键（如"学者别名"的嵌套结构）
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            # 正向：主词 -> 同义词列表
            synonym_map[key] = value
            # 反向：每个同义词 -> [主词 + 其他同义词]
            for synonym in value:
                if synonym not in synonym_map:
                    others = [key] + [s for s in value if s != synonym]
                    synonym_map[synonym] = others

    return synonym_map


# ─── 文件大小格式化 ───

def human_readable_size(size_bytes: int) -> str:
    """将字节数转为人类可读格式"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ─── 法条编号搜索模式生成 ───

def article_search_patterns(article_num: int) -> List[str]:
    """
    为给定法条编号生成多种搜索模式（用于 Grep）。

    Args:
        article_num: 法条编号（阿拉伯数字）

    Returns:
        搜索模式列表，如 ["第123条", "第一百二十三条"]
    """
    patterns = [f"第{article_num}条"]
    chinese = number_to_chinese(article_num)
    if chinese != str(article_num):
        patterns.append(f"第{chinese}条")
    return patterns


if __name__ == "__main__":
    # 自测
    assert chinese_to_number("一百二十三") == 123
    assert chinese_to_number("第六十九条") == 69
    assert chinese_to_number("1165") == 1165
    assert chinese_to_number("十") == 10
    assert chinese_to_number("二十二") == 22
    assert chinese_to_number("三百一十一") == 311
    # 万/亿位
    assert chinese_to_number("一万") == 10000
    assert chinese_to_number("一万二千三百四十五") == 12345
    assert chinese_to_number("五百万") == 5000000
    assert chinese_to_number("一亿") == 100000000
    assert normalize_article("第一千一百六十五条") == "第1165条"
    assert normalize_article("第123条") == "第123条"
    assert number_to_chinese(69) == "六十九"
    assert number_to_chinese(123) == "一百二十三"
    assert number_to_chinese(1165) == "一千一百六十五"
    print("All tests passed.")
