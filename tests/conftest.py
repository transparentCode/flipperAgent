import shutil
from pathlib import Path


def pytest_sessionfinish(session, exitstatus):
    """
    Clean up repo-local __pycache__ directories after the test session finishes.
    """
    root_dir = Path(__file__).parent.parent
    cache_roots = [root_dir / "src", root_dir / "tests"]
    removed = 0
    failures: list[str] = []

    for cache_root in cache_roots:
        if not cache_root.exists():
            continue
        for pycache_dir in cache_root.rglob("__pycache__"):
            if not pycache_dir.is_dir():
                continue
            try:
                shutil.rmtree(pycache_dir)
                removed += 1
            except Exception as exc:
                failures.append(f"{pycache_dir.relative_to(root_dir)}: {exc}")

    if removed:
        print(f"\nRemoved {removed} repo-local __pycache__ directories")
    if failures:
        print(f"\nFailed to remove {len(failures)} __pycache__ directories")
        for failure in failures[:10]:
            print(failure)
