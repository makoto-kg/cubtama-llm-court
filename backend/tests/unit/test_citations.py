from llm_court.domain import ResearchReport
from llm_court.engine.citations import (
    check_citations,
    extract_citations,
    normalize_evidence_ids,
)


def test_extract_citations_formats() -> None:
    text = "実験では影響が小さい[EV-01]。財源は【EV-02】。両方[EV-1, EV-02]。全角［ＥＶ－０１］"
    assert extract_citations(text) == ["EV-01", "EV-02"]


def test_extract_citations_none() -> None:
    assert extract_citations("出典はありません [注1]") == []


def test_normalize_evidence_ids() -> None:
    assert normalize_evidence_ids(["ev-1", "EV-02", "不明", "EV-02"]) == ["EV-01", "EV-02"]


def _kinds(text: str, report: ResearchReport) -> list[str]:
    evidence = {e.id: e for e in report.evidence}
    return [i.kind for i in check_citations("S-01", text, evidence)]


def test_valid_citation_and_quote(research_report: ResearchReport) -> None:
    text = (
        "実験では「雇用には大きな効果は見られなかった」とされます。[EV-01] 財源が課題です[EV-02]。"
    )
    assert _kinds(text, research_report) == []


def test_unknown_evidence(research_report: ResearchReport) -> None:
    assert _kinds("根拠があります[EV-09]。", research_report) == ["unknown_evidence"]


def test_no_citation(research_report: ResearchReport) -> None:
    assert _kinds("一般論として導入すべきです。", research_report) == ["no_citation"]


def test_unsupported_quote(research_report: ResearchReport) -> None:
    text = "証拠によれば「就業率が大きく下がった」のです【EV-01】。"
    issues = check_citations("S-01", text, {e.id: e for e in research_report.evidence})
    assert [i.kind for i in issues] == ["unsupported_quote"]
    assert issues[0].evidence_id == "EV-01"


def test_unverified_fact_is_not_a_valid_source(research_report: ResearchReport) -> None:
    # 未検証の事実の引用は裏付けにならない
    assert _kinds("「就業率が半減した」のです[EV-01]。", research_report) == ["unsupported_quote"]


def test_quote_without_citation_in_sentence_is_ignored(research_report: ResearchReport) -> None:
    # 出典のない文の「」は相手の発言の引用などとみなして検査しない
    text = "相手は「導入すれば誰も働かなくなる」と述べました。しかし影響は小さい[EV-01]。"
    assert _kinds(text, research_report) == []


def test_quote_checked_against_all_cited_in_sentence(research_report: ResearchReport) -> None:
    text = "「年間約150兆円が必要になります」という試算があります[EV-01][EV-02]。"
    assert _kinds(text, research_report) == []
