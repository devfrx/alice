"""Guard against drift between ``backend.spec`` and ``backend/plugins/``.

``backend.spec`` enumerates plugin packages explicitly in ``PLUGIN_PACKAGES``
(required for PyInstaller: ``collect_data_files`` only runs for listed
packages, so a missing entry silently drops that plugin's data files from the
bundle).  This test fails whenever the list and the filesystem diverge.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = BACKEND_DIR / "backend.spec"
PLUGINS_DIR = BACKEND_DIR / "plugins"

# Placeholder packages with an ``__init__.py`` but no real ``plugin.py`` —
# deliberately excluded from the spec (see the NOTE above PLUGIN_PACKAGES).
DELIBERATELY_EXCLUDED = {"home_automation"}


def _spec_plugin_packages() -> list[str]:
    """Extract the literal ``PLUGIN_PACKAGES`` list from ``backend.spec``."""
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PLUGIN_PACKAGES":
                    value = ast.literal_eval(node.value)
                    assert isinstance(value, list)
                    return value
    raise AssertionError("PLUGIN_PACKAGES assignment not found in backend.spec")


def _real_plugin_packages() -> set[str]:
    """Directories under ``backend/plugins`` that are real plugin packages."""
    return {
        d.name
        for d in PLUGINS_DIR.iterdir()
        if d.is_dir() and (d / "__init__.py").exists() and (d / "plugin.py").exists()
    }


def test_plugin_packages_matches_filesystem() -> None:
    listed = _spec_plugin_packages()
    real = _real_plugin_packages()

    missing = sorted(real - set(listed))
    phantom = sorted(set(listed) - real)
    assert not missing, f"Plugins on disk but absent from backend.spec PLUGIN_PACKAGES: {missing}"
    assert not phantom, f"backend.spec PLUGIN_PACKAGES entries with no real plugin: {phantom}"


def test_plugin_packages_sorted_and_unique() -> None:
    listed = _spec_plugin_packages()
    assert listed == sorted(set(listed)), "PLUGIN_PACKAGES must be sorted and duplicate-free"


def test_deliberate_exclusions_are_still_placeholders() -> None:
    """If an excluded placeholder gains a plugin.py, it must be re-added to the spec."""
    for name in DELIBERATELY_EXCLUDED:
        pkg = PLUGINS_DIR / name
        assert pkg.is_dir(), f"{name} no longer exists — drop it from DELIBERATELY_EXCLUDED"
        assert not (pkg / "plugin.py").exists(), (
            f"{name} now has a plugin.py — add it to PLUGIN_PACKAGES in backend.spec "
            "and remove it from DELIBERATELY_EXCLUDED"
        )
