from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from tests.test_demo_e2e_acceptance import (
    test_demo_e2e_chat_task_and_search_flow,
    test_demo_e2e_file_workspace_and_rag_flow,
    test_demo_e2e_research_submit_and_poll,
)


def main() -> None:
    cases = [
        ("chat_task_search", test_demo_e2e_chat_task_and_search_flow),
        ("file_workspace_rag", test_demo_e2e_file_workspace_and_rag_flow),
        ("research_polling", test_demo_e2e_research_submit_and_poll),
    ]
    for name, case in cases:
        with TemporaryDirectory(prefix=f"taskmate-{name}-") as temp_dir:
            case(Path(temp_dir))
        print(f"[PASS] {name}")
    print("All demo end-to-end flows passed.")


if __name__ == "__main__":
    main()
