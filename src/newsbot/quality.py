from __future__ import annotations

import re


LOW_INFORMATION_PREFIXES = (
    "在此背景下",
    "值得注意的是",
    "值得一提的是",
    "不难看出",
    "由此可见",
    "总的来看",
    "总体而言",
    "一方面",
    "另一方面",
    "对于",
)

FORBIDDEN_META_PHRASES = (
    "不代表当前排名",
    "该口径属于历史披露",
    "该说法来自历史披露",
    "理由也很充分",
    "仅供参考",
    "本文不构成",
)

UNSOURCED_RANKING_RE = re.compile(
    r"(?:行业前[一二三四五\d]|市场第[一二三四五\d]|行业第[一二三四五\d]|"
    r"头部厂商|头部平台|头部影响力|领先厂商|最大平台)"
)

CLICKBAIT_PHRASES = (
    "也扛不住了", "扛不住了", "彻底炸了", "炸裂", "杀疯了", "疯狂", "重磅",
    "突发", "大消息", "万万没想到", "没想到", "坐不住了", "要变天", "史诗级",
    "罕见", "惊现", "刷屏", "冲上热搜", "一夜之间",
)


def neutralize_headline(title: str, entity: str = "") -> str:
    value = " ".join(title.split()).replace("！", "").replace("!", "")
    question_parts = re.split(r"[？?]", value, maxsplit=1)
    if len(question_parts) == 2 and any(phrase in question_parts[0] for phrase in CLICKBAIT_PHRASES):
        value = question_parts[1]
    for phrase in CLICKBAIT_PHRASES:
        value = value.replace(phrase, "")
    replacements = (
        ("又将大幅涨价", "拟上调价格"),
        ("将大幅涨价", "拟上调价格"),
        ("大幅涨价", "上调价格"),
        ("暴增", "增长"),
        ("暴涨", "上涨"),
        ("暴跌", "下跌"),
        ("狂飙", "增长"),
        ("腰斩", "下降约一半"),
    )
    for source, target in replacements:
        value = value.replace(source, target)
    value = value.strip(" ，。；：:｜|—-？?")
    if entity and entity.lower() not in value.lower():
        value = f"{entity}{value}"
    return value or entity or title


def is_low_information_sentence(sentence: str) -> bool:
    normalized = sentence.strip(" \t\r\n，。！？；：")
    if not normalized:
        return True
    if normalized.startswith(LOW_INFORMATION_PREFIXES):
        return True
    return any(phrase in normalized for phrase in FORBIDDEN_META_PHRASES)


def quality_issues(text: str) -> list[str]:
    issues = [f"包含元叙述：{phrase}" for phrase in FORBIDDEN_META_PHRASES if phrase in text]
    headline_match = re.search(r"^###\s+(.+)$", text, re.MULTILINE)
    if headline_match:
        headline = headline_match.group(1)
        if "?" in headline or "？" in headline or any(phrase in headline for phrase in CLICKBAIT_PHRASES):
            issues.append("标题仍包含疑问式或情绪化表述")
    if UNSOURCED_RANKING_RE.search(text):
        issues.append("包含未经当前信源验证的行业排名或头部表述")
    for sentence in re.split(r"(?<=[。！？；])|\n", text):
        if sentence.strip() and is_low_information_sentence(sentence):
            issues.append("包含低信息过渡句")
            break
    return list(dict.fromkeys(issues))
