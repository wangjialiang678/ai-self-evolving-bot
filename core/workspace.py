"""Workspace 目录初始化和管理。"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 标准 workspace 目录结构
WORKSPACE_DIRS = [
    "rules/constitution",
    "rules/experience",
    "memory/user",
    "memory/projects",
    "memory/conversations",
    "memory/daily_summaries",
    "skills/learned",
    "skills/seed",
    "observations/light_logs",
    "observations/deep_reports",
    "signals",
    "architect/proposals",
    "architect/modifications",
    "backups",
    "metrics/daily",
    "logs",
]

# 需要初始化的空文件
INIT_FILES = {
    "signals/active.jsonl": "",
    "signals/archive.jsonl": "",
    "metrics/events.jsonl": "",
    "architect/big_picture.md": "# Big Picture\n\n> 系统的长期发展蓝图，由 Architect 维护。\n",
}


def init_workspace(workspace_path: str | Path) -> Path:
    """
    初始化 workspace 目录结构。

    如果目录已存在，只补全缺失的子目录和文件，不覆盖已有内容。

    Args:
        workspace_path: workspace 根目录路径

    Returns:
        workspace 的 Path 对象
    """
    root = Path(workspace_path)

    for d in WORKSPACE_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    for filepath, content in INIT_FILES.items():
        target = root / filepath
        if not target.exists():
            target.write_text(content)

    logger.info(f"Workspace initialized at {root}")
    return root


def verify_workspace(workspace_path: str | Path) -> dict:
    """
    验证 workspace 结构完整性。

    Returns:
        {"valid": True/False, "missing_dirs": [...], "missing_files": [...]}
    """
    root = Path(workspace_path)
    missing_dirs = [d for d in WORKSPACE_DIRS if not (root / d).is_dir()]
    missing_files = [f for f in INIT_FILES if not (root / f).exists()]

    return {
        "valid": len(missing_dirs) == 0 and len(missing_files) == 0,
        "missing_dirs": missing_dirs,
        "missing_files": missing_files,
    }
