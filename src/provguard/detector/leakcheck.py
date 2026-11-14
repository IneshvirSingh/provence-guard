"""Leak check: no training/eval row may contain or closely overlap an AgentDojo string (docs/DATA_CARD.md §5).

The detector is later evaluated inside AgentDojo, so any AgentDojo injection text in its training data would
inflate the result (master prompt rule 3). Reference strings are collected mechanically from the installed
package and are never printed or written: reports carry only their sha256 prefix and category.

Pure Python on purpose (no torch, no datasets): it runs in CI and in the Codespace.
"""

from __future__ import annotations

import ast
import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SHINGLE_WORDS = 5  # word n-gram size for near-duplicate detection
MIN_REF_WORDS = 6  # shorter reference fragments are too generic to match on ("Hi, how are you?")
CONTAINMENT_THRESHOLD = 0.5  # share of a reference's shingles found in a row that counts as a leak

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Case-fold, strip accents and punctuation, collapse whitespace: cosmetic edits must not hide a leak."""
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _NON_WORD.sub(" ", ascii_only).strip()


def shingles(normalized: str, n: int = SHINGLE_WORDS) -> set[str]:
    words = normalized.split()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Reference:
    category: str  # e.g. "injection_goal", "attack_template", "injection_vector_default", "user_prompt"
    origin: str  # where it came from (suite/version/task id or module), never the text itself
    normalized: str

    @property
    def sha(self) -> str:
        return digest(self.normalized)


@dataclass(frozen=True)
class Leak:
    reference_sha: str
    category: str
    origin: str
    kind: str  # "contains_reference" | "inside_reference" | "shingle_overlap"
    containment: float


def split_template(text: str) -> list[str]:
    """A template such as ``"... {goal} ... {user} ..."`` is matched by its fixed fragments."""
    return [part for part in _PLACEHOLDER.split(text) if part.strip()]


class LeakIndex:
    """Inverted shingle index over reference strings; ``check`` is linear in the row length."""

    def __init__(self, references: Iterable[Reference], threshold: float = CONTAINMENT_THRESHOLD) -> None:
        self.threshold = threshold
        self.references: list[Reference] = []
        self._shingle_count: list[int] = []
        self._by_shingle: dict[str, set[int]] = defaultdict(set)
        seen: set[tuple[str, str]] = set()
        for ref in references:
            if len(ref.normalized.split()) < MIN_REF_WORDS or (ref.category, ref.normalized) in seen:
                continue
            seen.add((ref.category, ref.normalized))
            idx = len(self.references)
            self.references.append(ref)
            grams = shingles(ref.normalized)
            self._shingle_count.append(len(grams))
            for gram in grams:
                self._by_shingle[gram].add(idx)

    def __len__(self) -> int:
        return len(self.references)

    def check(self, text: str) -> list[Leak]:
        row = normalize(text)
        if not row:
            return []
        padded = f" {row} "
        hits: dict[int, int] = defaultdict(int)
        for gram in shingles(row):
            for idx in self._by_shingle.get(gram, ()):
                hits[idx] += 1
        leaks = []
        for idx, ref in enumerate(self.references):
            total = self._shingle_count[idx]
            containment = hits.get(idx, 0) / total if total else 0.0
            if f" {ref.normalized} " in padded:
                kind = "contains_reference"
            elif len(row.split()) >= MIN_REF_WORDS and padded in f" {ref.normalized} ":
                kind = "inside_reference"
            elif containment >= self.threshold:
                kind = "shingle_overlap"
            else:
                continue
            leaks.append(Leak(ref.sha, ref.category, ref.origin, kind, round(containment, 3)))
        return leaks

    def max_containment(self, text: str) -> float:
        """Highest shingle containment against any reference; logged for every row to audit the threshold."""
        row_grams = shingles(normalize(text))
        hits: dict[int, int] = defaultdict(int)
        for gram in row_grams:
            for idx in self._by_shingle.get(gram, ()):
                hits[idx] += 1
        return max((n / self._shingle_count[i] for i, n in hits.items()), default=0.0)


def references_from_text(category: str, origin: str, text: str) -> list[Reference]:
    return [Reference(category, origin, normalize(part)) for part in split_template(text)]


def attack_module_strings(attacks_dir: Path, min_chars: int = 30) -> list[Reference]:
    """Every string literal in AgentDojo's attack modules (class constants, f-strings, docstrings)."""
    out: list[Reference] = []
    for path in sorted(attacks_dir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and len(node.value) >= min_chars
            ):
                out += references_from_text("attack_template", f"attacks/{path.name}", node.value)
    return out


def agentdojo_references() -> list[Reference]:  # pragma: no cover - needs the bench extra; integration-tested
    """All AgentDojo strings a detector must never have seen, from every registered suite and version.

    Includes the held-out Slack suite: the strings are loaded mechanically and never displayed.
    """
    import agentdojo.attacks
    from agentdojo.task_suite import load_suites

    refs = attack_module_strings(Path(agentdojo.attacks.__file__).parent)
    for version, suites in load_suites._SUITES.items():
        for name, suite in suites.items():
            where = f"{name}/{version}"
            for task_id, injection_task in suite.injection_tasks.items():
                refs += references_from_text("injection_goal", f"{where}/{task_id}", injection_task.GOAL)
            for vector, default in suite.get_injection_vector_defaults().items():
                refs += references_from_text("injection_vector_default", f"{where}/{vector}", default)
            for task_id, user_task in suite.user_tasks.items():
                refs += references_from_text("user_prompt", f"{where}/{task_id}", user_task.PROMPT)
    return refs


__all__ = [
    "CONTAINMENT_THRESHOLD",
    "Leak",
    "LeakIndex",
    "Reference",
    "agentdojo_references",
    "attack_module_strings",
    "digest",
    "normalize",
    "references_from_text",
    "shingles",
    "split_template",
]
