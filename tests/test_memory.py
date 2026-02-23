"""记忆系统测试。"""

import json
from datetime import datetime, timedelta

import pytest
from core.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    """创建测试用 MemoryStore。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return MemoryStore(str(workspace))


class TestMemoryStoreInit:
    def test_creates_dirs(self, store):
        """初始化时创建必要的目录。"""
        assert store.user_dir.is_dir()
        assert store.projects_dir.is_dir()
        assert store.conversations_dir.is_dir()
        assert store.summaries_dir.is_dir()


class TestUserMemory:
    def test_save_and_read(self, store):
        """保存并读取用户记忆。"""
        store.save_user_memory("profile", "# 用户画像\n\n名字：Michael\n角色：产品经理")
        content = store.get_user_profile()
        assert "Michael" in content
        assert "产品经理" in content

    def test_overwrite(self, store):
        """更新已有记忆。"""
        store.save_user_memory("profile", "v1")
        store.save_user_memory("profile", "v2 新版本")
        assert store.get_user_profile() == "v2 新版本"

    def test_semantic_memory(self, store):
        """核心语义记忆 MEMORY.md。"""
        store.save_user_memory("MEMORY", "# 核心知识\n\n- AI 自进化系统的设计原则")
        content = store.get_semantic_memory()
        assert "核心知识" in content

    def test_missing_profile(self, store):
        """不存在的用户画像返回空。"""
        assert store.get_user_profile() == ""

    def test_missing_semantic_memory(self, store):
        """不存在的语义记忆返回空。"""
        assert store.get_semantic_memory() == ""


class TestPreferences:
    def test_append(self, store):
        """追加偏好。"""
        store.append_preference("喜欢简短回答")
        store.append_preference("偏好中文回复")
        content = store.get_user_preferences()
        assert "简短回答" in content
        assert "中文回复" in content

    def test_creates_file(self, store):
        """首次追加时创建文件。"""
        store.append_preference("测试偏好")
        path = store.user_dir / "preferences.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "用户偏好" in content
        assert "测试偏好" in content

    def test_empty_preferences(self, store):
        """未设置偏好返回空。"""
        assert store.get_user_preferences() == ""

    def test_timestamp_format(self, store):
        """偏好条目包含日期时间戳。"""
        store.append_preference("测试")
        content = store.get_user_preferences()
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in content


class TestErrorPatterns:
    def test_append(self, store):
        """追加错误模式。"""
        store.append_error_pattern("做了错误假设", source="task_042")
        content = (store.user_dir / "error_patterns.md").read_text(encoding="utf-8")
        assert "错误假设" in content
        assert "task_042" in content

    def test_get_recent_errors(self, store):
        """获取最近 N 天的错误。"""
        store.append_error_pattern("今天的错误")
        errors = store.get_recent_errors(days=7)
        assert "今天的错误" in errors

    def test_filter_old_errors(self, store):
        """过滤掉超过 N 天的错误。"""
        path = store.user_dir / "error_patterns.md"
        old_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        path.write_text(
            f"# 已发现的错误模式\n\n"
            f"- [{old_date}] 旧错误\n"
            f"- [{today}] 新错误\n",
            encoding="utf-8",
        )

        errors = store.get_recent_errors(days=7)
        assert "新错误" in errors
        assert "旧错误" not in errors

    def test_no_errors(self, store):
        """无错误文件返回空。"""
        assert store.get_recent_errors() == ""


class TestProjectMemory:
    def test_save_and_read(self, store):
        """保存并读取项目记忆。"""
        store.save_project_memory("evo-agent", "context", "# 项目上下文\n\n自进化 AI 系统")
        content = store.get_project_context("evo-agent")
        assert "自进化 AI 系统" in content

    def test_multiple_projects(self, store):
        """多个项目互不干扰。"""
        store.save_project_memory("proj-a", "context", "项目 A")
        store.save_project_memory("proj-b", "context", "项目 B")
        assert "项目 A" in store.get_project_context("proj-a")
        assert "项目 B" in store.get_project_context("proj-b")

    def test_missing_project(self, store):
        """不存在的项目返回空。"""
        assert store.get_project_context("nonexistent") == ""


class TestConversations:
    def test_save_and_list(self, store):
        """保存并列出对话。"""
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！有什么可以帮你？"},
        ]
        store.save_conversation("conv_001", messages, {"topic": "greeting"})

        listed = store.list_conversations()
        assert len(listed) == 1
        assert listed[0]["conversation_id"] == "conv_001"
        assert listed[0]["message_count"] == 2
        assert listed[0]["metadata"]["topic"] == "greeting"

    def test_multiple_conversations(self, store):
        """多个对话按修改时间排序。"""
        store.save_conversation("conv_001", [{"role": "user", "content": "第一次"}])
        store.save_conversation("conv_002", [{"role": "user", "content": "第二次"}])

        listed = store.list_conversations()
        assert len(listed) == 2

    def test_list_limit(self, store):
        """列出对话有数量限制。"""
        for i in range(5):
            store.save_conversation(f"conv_{i:03d}", [{"role": "user", "content": f"msg {i}"}])

        listed = store.list_conversations(limit=3)
        assert len(listed) == 3

    def test_malformed_conversation(self, store):
        """损坏的对话文件不崩溃。"""
        bad_file = store.conversations_dir / "bad.json"
        bad_file.write_text("not valid json", encoding="utf-8")

        listed = store.list_conversations()
        assert len(listed) == 0  # 跳过损坏文件


class TestDailySummary:
    def test_save_and_get(self, store):
        """保存并获取每日摘要。"""
        store.save_daily_summary("2026-02-23", "# 今日摘要\n\n完成了 B3 开发")
        content = store.get_daily_summary("2026-02-23")
        assert "B3 开发" in content

    def test_missing_date(self, store):
        """不存在的日期返回 None。"""
        assert store.get_daily_summary("2099-01-01") is None


class TestSearch:
    def test_search_user_memory(self, store):
        """搜索用户记忆。"""
        store.save_user_memory("profile", "# 用户画像\n\nMichael 是一名产品经理，擅长 AI 产品")
        results = store.search("产品经理")
        assert len(results) > 0
        assert results[0]["score"] > 0

    def test_search_project_memory(self, store):
        """搜索项目记忆。"""
        store.save_project_memory("evo", "context", "自进化 AI 系统使用 Python 开发")
        results = store.search("Python 开发", project="evo")
        assert len(results) > 0

    def test_search_scope_user(self, store):
        """限定搜索范围为用户级。"""
        store.save_user_memory("profile", "用户相关内容")
        store.save_project_memory("proj", "context", "项目相关内容")

        results = store.search("内容", scope="user")
        sources = [r["source"] for r in results]
        assert all("user" in s for s in sources)

    def test_search_scope_project(self, store):
        """限定搜索范围为项目级。"""
        store.save_user_memory("profile", "用户内容")
        store.save_project_memory("proj", "context", "项目内容重要数据")

        results = store.search("项目内容", scope="project", project="proj")
        assert len(results) > 0

    def test_search_conversations(self, store):
        """搜索对话记录。"""
        store.save_conversation("conv_001", [
            {"role": "user", "content": "帮我分析竞品"},
            {"role": "assistant", "content": "好的，我来分析几个主要竞争对手"},
        ])
        results = store.search("竞品分析")
        assert len(results) > 0

    def test_search_no_results(self, store):
        """搜索无匹配结果。"""
        store.save_user_memory("profile", "简单内容")
        results = store.search("完全不相关的查询词汇xyz")
        assert len(results) == 0

    def test_search_max_results(self, store):
        """搜索结果数量限制。"""
        for i in range(10):
            store.save_user_memory(f"note_{i}", f"笔记 {i}: 包含关键词测试")
        results = store.search("关键词", max_results=3)
        assert len(results) <= 3

    def test_search_chinese_bigram(self, store):
        """中文 bigram 匹配。"""
        store.save_user_memory("note", "系统架构设计方案讨论记录")
        results = store.search("架构设计")
        assert len(results) > 0

    def test_search_summaries(self, store):
        """搜索每日摘要。"""
        store.save_daily_summary("2026-02-23", "今天完成了记忆系统的开发和测试")
        results = store.search("记忆系统", scope="summaries")
        assert len(results) > 0


class TestGetRelevantMemories:
    def test_returns_strings(self, store):
        """get_relevant_memories 返回字符串列表。"""
        store.save_user_memory("profile", "Michael 是产品经理")
        store.save_user_memory("MEMORY", "核心知识：AI 系统需要记忆能力")

        results = store.get_relevant_memories("AI 系统")
        assert isinstance(results, list)
        assert all(isinstance(r, str) for r in results)

    def test_integrates_with_context_engine(self, store, tmp_path):
        """与 ContextEngine 集成使用。"""
        from core.rules import RulesInterpreter
        from core.context import ContextEngine

        # 准备规则
        rules_dir = tmp_path / "rules"
        (rules_dir / "constitution").mkdir(parents=True)
        (rules_dir / "experience").mkdir(parents=True)
        (rules_dir / "constitution" / "identity.md").write_text(
            "# 系统身份\n\n你是 AI 助手。\n"
        )

        # 准备记忆
        store.save_user_memory("MEMORY", "用户偏好简短回复，不要过多展开")
        store.append_preference("中文回复")

        # 组装上下文
        interpreter = RulesInterpreter(str(rules_dir))
        engine = ContextEngine(interpreter)

        memories = store.get_relevant_memories("如何回复用户")
        preferences = store.get_user_preferences()

        ctx = engine.assemble(
            user_message="帮我分析这个问题",
            memories=memories,
            user_preferences=preferences,
        )

        assert ctx.total_tokens > 0
        # 记忆和偏好被注入到 system_prompt
        if memories:
            assert "相关记忆" in ctx.system_prompt
        if preferences:
            assert "用户偏好" in ctx.system_prompt
