"""生成した事件の保存・読み込み(`data/cases/<id>.json`)。"""

from pathlib import Path

from llm_court.domain import Case


class CaseNotFoundError(Exception):
    pass


class CaseStore:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def path(self, case_id: str) -> Path:
        if not case_id.isalnum():
            raise CaseNotFoundError(case_id)
        return self._dir / f"{case_id}.json"

    def save(self, case: Case) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self.path(case.id)
        path.write_text(case.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, case_id: str) -> Case:
        path = self.path(case_id)
        if not path.exists():
            raise CaseNotFoundError(case_id)
        return Case.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[Case]:
        if not self._dir.is_dir():
            return []
        cases = [
            Case.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self._dir.glob("*.json")
        ]
        return sorted(cases, key=lambda c: c.created_at)
