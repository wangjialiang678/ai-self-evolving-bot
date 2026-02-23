"""Bootstrap 首次对话引导流程。"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

STAGES = ["background", "projects", "preferences"]

STAGE_PROMPTS = {
    "background": (
        "欢迎！在开始之前，我想了解一下你的背景。\n\n"
        "请告诉我：\n"
        "1. 你的称呼是什么？\n"
        "2. 你的角色（开发者/产品/设计等）？\n"
        "3. 技术经验水平（初级/中级/高级）？\n"
        "4. 常用的编程语言？\n"
        "5. 当前关注的技术方向？"
    ),
    "projects": (
        "很好！接下来，请告诉我你正在做的项目：\n\n"
        "1. 项目名称？\n"
        "2. 项目描述（一两句话）？\n"
        "3. 使用的技术栈？\n"
        "4. 当前所处阶段（探索/开发/上线/维护）？"
    ),
    "preferences": (
        "最后，配置一下你的使用偏好：\n\n"
        "1. 回复风格（简洁/详细/自适应）？\n"
        "2. 对话语言（中文/英文/双语）？\n"
        "3. 通知级别（minimal/normal/verbose）？"
    ),
    "completed": "引导已完成，系统已为你完成个性化配置。",
    "not_started": "引导尚未开始。",
}

STATE_FILE = ".bootstrap_state.json"


class BootstrapFlow:
    """首次对话引导流程。"""

    def __init__(self, workspace_path: str | Path):
        self._root = Path(workspace_path)

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return self._root / STATE_FILE

    def _load_state(self) -> dict:
        p = self._state_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {
            "current_stage": "not_started",
            "completed_stages": [],
            "started_at": None,
            "completed_at": None,
        }

    def _save_state(self, state: dict) -> None:
        self._state_path().write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def is_bootstrapped(self) -> bool:
        """检查是否已完成引导（workspace/USER.md 存在且非空）。"""
        user_md = self._root / "USER.md"
        return user_md.exists() and user_md.stat().st_size > 0

    def get_current_stage(self) -> str:
        """获取当前引导阶段。

        Returns:
            "not_started" | "background" | "projects" | "preferences" | "completed"
        """
        if self.is_bootstrapped():
            return "completed"
        state = self._load_state()
        return state["current_stage"]

    async def process_stage(self, stage: str, user_input: dict) -> dict:
        """处理一个引导阶段。

        Args:
            stage: 阶段名
            user_input: 用户输入数据

        Returns:
            {
                "stage": str,
                "next_stage": str | None,
                "prompt": str,
                "completed": bool,
            }
        """
        state = self._load_state()

        if state["current_stage"] == "not_started":
            state["current_stage"] = stage
            state["started_at"] = datetime.now().isoformat()

        if stage == "background":
            self.save_user_profile(user_input)
            next_stage = "projects"

        elif stage == "projects":
            project_name = user_input.get("project_name", "unnamed")
            self.save_project_config(project_name, user_input)
            next_stage = "preferences"

        elif stage == "preferences":
            prefs = []
            for key in ("response_style", "language", "notification_level"):
                val = user_input.get(key)
                if val:
                    prefs.append(f"{key}: {val}")
            self.save_preferences(prefs)
            next_stage = None

        else:
            raise ValueError(f"Unknown stage: {stage}")

        # 更新状态
        if stage not in state["completed_stages"]:
            state["completed_stages"].append(stage)

        if next_stage:
            state["current_stage"] = next_stage
            prompt = self.get_stage_prompt(next_stage)
            completed = False
        else:
            state["current_stage"] = "completed"
            state["completed_at"] = datetime.now().isoformat()
            prompt = self.get_stage_prompt("completed")
            completed = True

        self._save_state(state)

        return {
            "stage": stage,
            "next_stage": next_stage,
            "prompt": prompt,
            "completed": completed,
        }

    def get_stage_prompt(self, stage: str) -> str:
        """获取某阶段的引导提示词。"""
        return STAGE_PROMPTS.get(stage, f"未知阶段: {stage}")

    # ------------------------------------------------------------------
    # 保存方法
    # ------------------------------------------------------------------

    def save_user_profile(self, profile: dict) -> Path:
        """保存用户档案到 workspace/USER.md。"""
        name = profile.get("name", "")
        role = profile.get("role", "")
        experience = profile.get("experience", "")
        languages = profile.get("languages", "")
        focus = profile.get("focus", "")
        date = datetime.now().strftime("%Y-%m-%d")

        content = (
            "# 用户档案\n\n"
            f"- **称呼**: {name}\n"
            f"- **角色**: {role}\n"
            f"- **经验**: {experience}\n"
            f"- **常用语言**: {languages}\n"
            f"- **关注方向**: {focus}\n\n"
            f"> 由 Bootstrap 流程生成于 {date}\n"
        )

        target = self._root / "USER.md"
        target.write_text(content, encoding="utf-8")
        logger.info(f"User profile saved to {target}")
        return target

    def save_project_config(self, project_name: str, config: dict) -> Path:
        """保存项目配置到 workspace/memory/projects/{name}/context.md。"""
        project_dir = self._root / "memory" / "projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        description = config.get("description", "")
        tech_stack = config.get("tech_stack", "")
        current_phase = config.get("current_phase", "")
        date = datetime.now().strftime("%Y-%m-%d")

        content = (
            f"# {project_name}\n\n"
            f"- **描述**: {description}\n"
            f"- **技术栈**: {tech_stack}\n"
            f"- **当前阶段**: {current_phase}\n\n"
            f"> 由 Bootstrap 流程生成于 {date}\n"
        )

        target = project_dir / "context.md"
        target.write_text(content, encoding="utf-8")
        logger.info(f"Project config saved to {target}")
        return target

    def save_preferences(self, preferences: list[str]) -> Path:
        """保存偏好到 workspace/memory/user/preferences.md。"""
        user_dir = self._root / "memory" / "user"
        user_dir.mkdir(parents=True, exist_ok=True)

        date = datetime.now().strftime("%Y-%m-%d")
        lines = "\n".join(f"- {p}" for p in preferences)
        content = (
            "# 用户偏好\n\n"
            f"{lines}\n\n"
            f"> 由 Bootstrap 流程生成于 {date}\n"
        )

        target = user_dir / "preferences.md"
        target.write_text(content, encoding="utf-8")
        logger.info(f"Preferences saved to {target}")
        return target
