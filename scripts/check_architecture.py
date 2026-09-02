"""Enforce repository boundaries that are easy to regress in review."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SET_CONFIG = ROOT / "app" / "db" / "rls.py"


def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item for item in result.stdout.decode().split("\0") if item]


def python_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.py"))


def main() -> int:
    violations: list[str] = []

    set_config_paths = [
        path
        for path in python_paths(ROOT / "app")
        if "set_config" in path.read_text(encoding="utf-8")
    ]
    if set_config_paths != [ALLOWED_SET_CONFIG]:
        violations.append(
            "set_config must appear only in app/db/rls.py: "
            + ", ".join(str(path.relative_to(ROOT)) for path in set_config_paths)
        )

    tenant_filter = re.compile(r"\btenant_id\s*==")
    repository_paths = python_paths(ROOT / "app" / "repositories")
    for path in repository_paths:
        if tenant_filter.search(path.read_text(encoding="utf-8")):
            violations.append(f"repository contains a tenant_id filter: {path.relative_to(ROOT)}")

    runtime_paths = python_paths(ROOT / "app")
    for path in runtime_paths:
        if "service_role" in path.read_text(encoding="utf-8"):
            violations.append(f"runtime code references service_role: {path.relative_to(ROOT)}")

    secret_patterns = (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    )
    for path in tracked_paths():
        name = path.name.lower()
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            violations.append(f"environment file is tracked: {path.relative_to(ROOT)}")
        if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            violations.append(f"credential file is tracked: {path.relative_to(ROOT)}")
        if path.is_file():
            content = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(content) for pattern in secret_patterns):
                violations.append(f"secret-like value is tracked: {path.relative_to(ROOT)}")

    if violations:
        print("Architecture checks failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1

    print("Architecture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
