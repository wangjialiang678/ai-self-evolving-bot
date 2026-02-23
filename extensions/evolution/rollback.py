"""规则文件备份与回滚管理。"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RollbackManager:
    """管理规则文件的备份和回滚。"""

    def __init__(self, workspace_path: str, backup_dir: str = "backups"):
        """初始化回滚管理器。"""
        self.workspace_path = Path(workspace_path)
        self.backups_root = self.workspace_path / backup_dir
        self.backups_root.mkdir(parents=True, exist_ok=True)

    def backup(self, file_paths: list[str], proposal_id: str) -> str:
        """修改前备份指定文件。"""
        now = datetime.now()
        backup_id = self._make_backup_id(now, proposal_id)
        backup_path = self.backups_root / backup_id
        suffix = 1
        while backup_path.exists():
            backup_id = f"{self._make_backup_id(now, proposal_id)}_{suffix}"
            backup_path = self.backups_root / backup_id
            suffix += 1

        try:
            backup_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error("Failed to create backup directory %s: %s", backup_path, exc)
            raise RuntimeError(f"Failed to create backup directory: {backup_path}") from exc

        normalized_files: list[str] = []
        missing_files: list[str] = []

        for file_path in file_paths:
            rel = self._normalize_to_workspace_relative(file_path)
            if rel is None:
                logger.warning("Skip backup for out-of-workspace path: %s", file_path)
                continue

            rel_posix = rel.as_posix()
            normalized_files.append(rel_posix)
            source = self.workspace_path / rel
            target = backup_path / rel

            if not source.exists():
                missing_files.append(rel_posix)
                logger.info("File does not exist during backup (record only): %s", source)
                continue

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            except Exception as exc:
                logger.error("Failed to backup file %s -> %s: %s", source, target, exc)

        metadata = {
            "backup_id": backup_id,
            "proposal_id": proposal_id,
            "timestamp": now.replace(microsecond=0).isoformat(),
            "files": normalized_files,
            "missing_files": missing_files,
            "status": "active",
        }

        self._write_metadata(backup_path, metadata)
        return backup_id

    def rollback(self, backup_id: str) -> dict[str, Any]:
        """回滚到指定备份。"""
        result: dict[str, Any] = {
            "restored_files": [],
            "status": "failed",
            "error": None,
        }

        backup_path = self.backups_root / backup_id
        if not backup_path.exists():
            result["error"] = "backup_not_found"
            return result

        metadata = self._read_metadata(backup_path)
        if metadata is None:
            result["error"] = "metadata_not_found"
            return result

        if metadata.get("status") == "rolled_back":
            result["error"] = "already_rolled_back"
            return result

        files: list[str] = list(metadata.get("files", []))
        missing_files = set(metadata.get("missing_files", []))

        restore_errors: list[str] = []
        for rel_path in files:
            backup_file = backup_path / rel_path
            target_file = self.workspace_path / rel_path

            try:
                if backup_file.exists():
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_file, target_file)
                    result["restored_files"].append(rel_path)
                elif rel_path in missing_files:
                    if target_file.exists():
                        target_file.unlink()
                else:
                    restore_errors.append(f"missing_backup_file:{rel_path}")
            except Exception as exc:
                logger.error("Failed restoring %s: %s", rel_path, exc)
                restore_errors.append(f"restore_failed:{rel_path}")

        if restore_errors:
            result["error"] = ";".join(restore_errors)
            return result

        metadata["status"] = "rolled_back"
        metadata["rolled_back_at"] = datetime.now().replace(microsecond=0).isoformat()
        if not self._write_metadata(backup_path, metadata):
            result["error"] = "metadata_update_failed"
            return result

        result["status"] = "success"
        return result

    def list_backups(self, limit: int = 10) -> list[dict[str, Any]]:
        """列出最近的备份。"""
        entries: list[dict[str, Any]] = []

        for backup_dir in self.backups_root.iterdir():
            if not backup_dir.is_dir():
                continue

            metadata = self._read_metadata(backup_dir)
            if metadata is None:
                continue

            metadata["_mtime"] = backup_dir.stat().st_mtime
            entries.append(metadata)

        entries.sort(
            key=lambda item: (
                self._safe_parse_iso(item.get("timestamp", "")),
                item.get("_mtime", 0),
                item.get("backup_id", ""),
            ),
            reverse=True,
        )

        clean_entries: list[dict[str, Any]] = []
        for item in entries[: max(limit, 0)]:
            cleaned = dict(item)
            cleaned.pop("_mtime", None)
            clean_entries.append(cleaned)
        return clean_entries

    def cleanup(self, retention_days: int = 30):
        """清理过期备份。"""
        cutoff = datetime.now() - timedelta(days=retention_days)

        for backup_dir in self.backups_root.iterdir():
            if not backup_dir.is_dir():
                continue

            metadata = self._read_metadata(backup_dir)
            if metadata is None:
                continue

            timestamp = self._safe_parse_iso(metadata.get("timestamp", ""))
            if timestamp is None:
                logger.warning("Skip cleanup for invalid timestamp backup: %s", backup_dir.name)
                continue

            status = str(metadata.get("status", "active"))
            # active 备份在验证期内保留；超出 retention 视为过期 stale active，可清理。
            should_delete = timestamp < cutoff
            if should_delete:
                try:
                    shutil.rmtree(backup_dir)
                    logger.info("Deleted expired backup: %s (status=%s)", backup_dir.name, status)
                except Exception as exc:
                    logger.error("Failed deleting backup %s: %s", backup_dir.name, exc)

    def auto_rollback_check(
        self,
        proposal_id: str,
        current_metrics: dict[str, Any],
        baseline_metrics: dict[str, Any],
        threshold: float = 0.20,
    ) -> bool:
        """检查指标恶化并在必要时自动回滚。"""
        baseline = float(baseline_metrics.get("tasks", {}).get("success_rate", 0) or 0)
        current = float(current_metrics.get("tasks", {}).get("success_rate", 0) or 0)

        if baseline <= 0:
            return False

        degradation = (baseline - current) / baseline
        if degradation <= threshold:
            return False

        backup_id = self._find_latest_active_backup_for_proposal(proposal_id)
        if backup_id is None:
            logger.warning("No active backup found for proposal_id=%s", proposal_id)
            return False

        rollback_result = self.rollback(backup_id)
        return rollback_result.get("status") == "success"

    def _find_latest_active_backup_for_proposal(self, proposal_id: str) -> str | None:
        backups = self.list_backups(limit=1000)
        for item in backups:
            if item.get("proposal_id") == proposal_id and item.get("status") == "active":
                return str(item.get("backup_id"))
        return None

    @staticmethod
    def _make_backup_id(now: datetime, proposal_id: str) -> str:
        return f"backup_{now.strftime('%Y%m%d_%H%M%S')}_{proposal_id}"

    def _normalize_to_workspace_relative(self, file_path: str) -> Path | None:
        raw = Path(file_path)
        if raw.is_absolute():
            try:
                return raw.resolve().relative_to(self.workspace_path.resolve())
            except ValueError:
                return None
        return raw

    def _read_metadata(self, backup_dir: Path) -> dict[str, Any] | None:
        metadata_file = backup_dir / "metadata.json"
        if not metadata_file.exists():
            logger.warning("Metadata not found: %s", metadata_file)
            return None

        try:
            return json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to read metadata %s: %s", metadata_file, exc)
            return None

    def _write_metadata(self, backup_dir: Path, metadata: dict[str, Any]) -> bool:
        metadata_file = backup_dir / "metadata.json"
        try:
            metadata_file.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as exc:
            logger.error("Failed to write metadata %s: %s", metadata_file, exc)
            return False

    @staticmethod
    def _safe_parse_iso(value: str) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None
