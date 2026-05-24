import shutil
from pathlib import Path

def pytest_sessionfinish(session, exitstatus):
    """
    Clean up __pycache__ directories globally after the test session finishes.
    """
    root_dir = Path(__file__).parent.parent
    
    for pycache_dir in root_dir.rglob("__pycache__"):
        if pycache_dir.is_dir():
            try:
                shutil.rmtree(pycache_dir)
                print(f"\nRemoved cache directory: {pycache_dir.relative_to(root_dir)}")
            except Exception as e:
                print(f"\nFailed to remove {pycache_dir.relative_to(root_dir)}: {e}")
