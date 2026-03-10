"""Temporary debug script for file_search test failure."""
import asyncio
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch


async def test():
    from backend.plugins.file_search.plugin import FileSearchPlugin
    from backend.core.config import OmniaConfig
    from backend.core.plugin_models import ExecutionContext

    plugin = FileSearchPlugin()

    config = OmniaConfig()

    class MockCtx:
        pass

    ctx = MockCtx()
    ctx.config = config
    plugin.ctx = ctx
    plugin._allowed_paths = [Path("/tmp/allowed")]
    plugin._forbidden_paths = []

    target = Path("/tmp/allowed/readme.txt").resolve()

    s = MagicMock()
    s.st_size = 2048
    s.st_mtime = 1700000000.0
    s.st_ctime = 1700000000.0

    exec_ctx = ExecutionContext(plugin_name="file_search", user_input="test", config={})

    with (
        patch.object(Path, "resolve", return_value=target),
        patch.object(Path, "exists", return_value=True),
        patch.object(Path, "is_file", return_value=True),
        patch.object(Path, "is_dir", return_value=False),
        patch.object(Path, "stat", return_value=s),
    ):
        try:
            result = await plugin._exec_get_file_info({"path": str(target)})
            print("Success:", result)
        except Exception as e:
            print("ERROR:", type(e).__name__, e)
            traceback.print_exc()


asyncio.run(test())
