"""测试 workspace 初始化。"""

from core.workspace import init_workspace, verify_workspace


class TestWorkspace:
    def test_init_creates_all_dirs(self, tmp_path):
        """初始化创建所有目录。"""
        ws = init_workspace(tmp_path / "workspace")
        result = verify_workspace(ws)
        assert result["valid"] is True
        assert result["missing_dirs"] == []
        assert result["missing_files"] == []

    def test_init_idempotent(self, tmp_path):
        """重复初始化不报错。"""
        ws_path = tmp_path / "workspace"
        init_workspace(ws_path)
        init_workspace(ws_path)  # 第二次
        result = verify_workspace(ws_path)
        assert result["valid"] is True

    def test_init_preserves_existing(self, tmp_path):
        """初始化不覆盖已有文件。"""
        ws_path = tmp_path / "workspace"
        init_workspace(ws_path)

        # 写入自定义内容
        (ws_path / "architect/big_picture.md").write_text("# My Big Picture\n")

        # 再次初始化
        init_workspace(ws_path)

        # 自定义内容保留
        assert (ws_path / "architect/big_picture.md").read_text() == "# My Big Picture\n"

    def test_verify_missing_dirs(self, tmp_path):
        """验证检测到缺失目录。"""
        ws_path = tmp_path / "workspace"
        ws_path.mkdir()
        result = verify_workspace(ws_path)
        assert result["valid"] is False
        assert len(result["missing_dirs"]) > 0
