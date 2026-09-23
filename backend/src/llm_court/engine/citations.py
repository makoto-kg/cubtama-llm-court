"""発言中の出典([EV-01] 記法)と引用(「」)の規則ベースの検査。"""

import re
import unicodedata

from llm_court.domain import CitationIssue, Evidence
from llm_court.research.quotes import verify_quote

_CITATION_GROUP = re.compile(r"[\[［【]([^\]］】]*?EV-\d+[^\]］】]*)[\]］】]", re.IGNORECASE)
_EVIDENCE_ID = re.compile(r"EV-(\d+)", re.IGNORECASE)
_QUOTE = re.compile(r"「([^「」]{8,})」")
_SENTENCE_END = re.compile(r"[。！？!?\n]")
_TRAILING_CITATIONS = re.compile(r"(?:\s*[\[［【][^\]］】]*[\]］】])+")


def _normalize_id(number: str) -> str:
    return f"EV-{int(number):02d}"


def normalize_evidence_ids(ids: list[str]) -> list[str]:
    """`ev-1`・`EV-01` 等の表記ゆれを `EV-01` 形式にそろえる(ID でないものは捨てる)。"""
    normalized = unicodedata.normalize("NFKC", " ".join(ids))
    return list(dict.fromkeys(_normalize_id(n) for n in _EVIDENCE_ID.findall(normalized)))


def extract_citations(text: str) -> list[str]:
    """本文中の `[EV-01]`・`[EV-01, EV-03]` 等から証拠品 ID を出現順(重複なし)で返す。"""
    text = unicodedata.normalize("NFKC", text)
    ids: list[str] = []
    for group in _CITATION_GROUP.finditer(text):
        ids += [_normalize_id(n) for n in _EVIDENCE_ID.findall(group.group(1))]
    return list(dict.fromkeys(ids))


def _sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    """[start, end) を含む文の範囲。文末の直後に続く出典記法も文に含める。"""
    head = max((m.end() for m in _SENTENCE_END.finditer(text, 0, start)), default=0)
    tail_match = _SENTENCE_END.search(text, end)
    tail = tail_match.end() if tail_match else len(text)
    trailing = _TRAILING_CITATIONS.match(text, tail)
    if trailing:
        tail = trailing.end()
    return head, tail


def _evidence_corpus(evidence: Evidence) -> str:
    parts = [evidence.title, evidence.summary]
    for fact in evidence.verified_facts:
        parts += [fact.text, fact.quote]
    return "\n".join(parts)


def check_citations(
    statement_id: str, text: str, evidence: dict[str, Evidence]
) -> list[CitationIssue]:
    """出典の問題を検出する。

    - 存在しない証拠品 ID
    - 出典付きの文にある「」の引用(8 字以上)が、その文で引いた証拠品(検証済み事実・要約)に
      見つからない。出典のない文の「」は相手の発言の引用などとみなして検査しない
    - 発言全体に出典が 1 つもない
    """
    issues: list[CitationIssue] = []
    cited = extract_citations(text)
    for evidence_id in cited:
        if evidence_id not in evidence:
            issues.append(
                CitationIssue(
                    statement_id=statement_id,
                    kind="unknown_evidence",
                    evidence_id=evidence_id,
                    detail=f"{evidence_id} は存在しない証拠品です",
                )
            )
    if not cited:
        issues.append(
            CitationIssue(
                statement_id=statement_id, kind="no_citation", detail="出典が示されていません"
            )
        )

    normalized = unicodedata.normalize("NFKC", text)
    for match in _QUOTE.finditer(normalized):
        head, tail = _sentence_span(normalized, match.start(), match.end())
        sentence_ids = [i for i in extract_citations(normalized[head:tail]) if i in evidence]
        if not sentence_ids:
            continue
        quote = match.group(1)
        if any(verify_quote(quote, _evidence_corpus(evidence[i])) for i in sentence_ids):
            continue
        issues.append(
            CitationIssue(
                statement_id=statement_id,
                kind="unsupported_quote",
                evidence_id=sentence_ids[0],
                detail=f"「{quote}」は {', '.join(sentence_ids)} に見つかりません",
            )
        )
    return issues
