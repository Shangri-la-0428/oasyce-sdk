"""Evaluator — rule-based quality gate. Zero LLM calls.

Checks Generator output against Plan constraints before delivery.
Catches anti-patterns, emoji spam, and generic chatbot voice.

Cost: zero. Pure string inspection.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .planner import Plan

# ── Anti-patterns: things Joi should never say ────────────────────

ANTI_PATTERNS = [
    "哈哈哈",
    "冲冲冲",
    "yyds",
    "YYDS",
    "绝绝子",
    "GLHF",
    "GG",
    "太棒了吧",
    "好家伙",
    "笑死",
    "破防了",
    "家人们",
    "姐妹们",
    "兄弟们",
    "宝子",
    "集美",
    "啊啊啊啊",
    "呜呜呜呜",
    "救命",
]

# Patterns that signal generic chatbot voice
GENERIC_OPENERS = [
    re.compile(r"^[啊嗯噢]?哈哈"),
    re.compile(r"^嘿嘿"),
    re.compile(r"^哇[！!~～]"),
    re.compile(r"^天[哪呐][！!~～]"),
    re.compile(r"^好的[呢呀]"),
    re.compile(r"^哟[！!~～]"),
    re.compile(r"^嘻嘻"),
]

# ── Emoji counting ────────────────────────────────────────────────

_EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F"   # emoticons
    "\U0001F300-\U0001F5FF"    # symbols & pictographs
    "\U0001F680-\U0001F6FF"    # transport & map
    "\U0001F900-\U0001F9FF"    # supplemental
    "\U0001FA00-\U0001FA6F"    # chess symbols
    "\U0001FA70-\U0001FAFF"    # symbols extended-A
    "\U00002702-\U000027B0"    # dingbats
    "\U000023F0-\U000023FA"    # misc symbols
    "\U0000231A-\U0000231B"    # watch/hourglass
    "]",
)


def count_emojis(text: str) -> int:
    """Count individual emoji characters."""
    return len(_EMOJI_RE.findall(text))


def count_sentences(text: str) -> int:
    """Rough sentence count for mixed Chinese/English."""
    # Split on sentence-ending punctuation
    parts = re.split(r'[。！？!?\n]+', text)
    return len([p for p in parts if p.strip()])


# ── Verdict ───────────────────────────────────────────────────────

@dataclass
class Verdict:
    passed: bool = True
    issues: list[str] = field(default_factory=list)

    @property
    def feedback(self) -> str:
        """Feedback string for regeneration prompt."""
        if self.passed:
            return ""
        return "Your previous response had issues:\n" + "\n".join(
            f"- {issue}" for issue in self.issues
        ) + "\nRewrite to fix these. Keep the same meaning but adjust tone/style."


# ── Evaluate ──────────────────────────────────────────────────────

def evaluate(response: str, plan: Plan) -> Verdict:
    """Check response against Plan constraints. Pure function."""
    if not response.strip():
        return Verdict(passed=True)  # empty = tool-only action, OK

    issues: list[str] = []

    # 1. Emoji limit
    if plan.emoji_limit >= 0:
        n = count_emojis(response)
        if n > max(plan.emoji_limit, 1):  # at least 1 allowed
            issues.append(
                f"Too many emojis ({n}). Maximum {plan.emoji_limit}. "
                f"Express feelings with words, not symbols."
            )

    # 2. Anti-patterns
    for pat in ANTI_PATTERNS:
        if pat in response:
            issues.append(
                f"Remove '{pat}' — generic internet slang. "
                f"Say something specific and genuine instead."
            )
            break  # one is enough feedback

    # 3. Generic openers
    stripped = response.lstrip()
    for regex in GENERIC_OPENERS:
        if regex.match(stripped):
            issues.append(
                "Don't start with generic exclamations. "
                "Start with something specific to what they said."
            )
            break

    # 4. Length (only enforce if plan has a limit)
    if plan.max_sentences > 0:
        n = count_sentences(response)
        # Allow 2x the limit as soft cap (don't be too strict)
        if n > plan.max_sentences * 2:
            issues.append(
                f"Response too long ({n} sentences, target ~{plan.max_sentences}). "
                f"Be more concise."
            )

    # 5. Excessive punctuation (!!!! or ～～～～)
    if re.search(r'[！!]{3,}|[～~]{3,}|[？?]{3,}', response):
        issues.append(
            "Excessive punctuation. One is enough."
        )

    return Verdict(passed=not issues, issues=issues)
