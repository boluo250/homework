from __future__ import annotations

from pathlib import Path


class SkillsLoader:
    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or Path(__file__).resolve().parent.parent / "skills"

    def load_skill(self, skill_name: str) -> str:
        skill_path = self.root_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            return ""
        return skill_path.read_text(encoding="utf-8").strip()

    def select_router_skills(self, *, message: str, file_ids: list[str]) -> list[str]:
        names = ["task_os"]
        lowered = message.lower()
        if file_ids:
            names.append("file_rag")
        if any(token in lowered for token in ("研究", "调研", "方案", "tradeoff", "compare")):
            names.append("research_orchestrator")
        return names

    def render_router_instructions(self, *, message: str, file_ids: list[str]) -> str:
        sections = []
        for skill_name in self.select_router_skills(message=message, file_ids=file_ids):
            content = self.load_skill(skill_name)
            if content:
                sections.append(f"[skill:{skill_name}]\n{content}")
        return "\n\n".join(sections).strip()
