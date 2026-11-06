"""The helper workspace owns its runtime dependencies independently of AI archives."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AppWorkspaceTests(unittest.TestCase):
    def test_retired_entry_points_are_outside_the_workspace(self):
        for relative in ('src', 'start.py', 'run_web.py', '.venv-amago', 'artifacts/rl'):
            self.assertFalse((ROOT / relative).exists(), relative)
        for path in (ROOT / 'lab').glob('*.py'):
            self.assertFalse(path.stem.startswith(('rl_', 'amago', 'metamon')),
                             path.relative_to(ROOT).as_posix())

    def test_helper_imports_resolve_to_retained_modules(self):
        for path in (ROOT / 'lab').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if not isinstance(node, ast.ImportFrom):
                    continue
                name = node.module or ''
                if node.level:
                    name = 'lab.' + name if name else 'lab'
                if name == 'lab':
                    modules = ['lab.' + alias.name for alias in node.names if alias.name != '*']
                elif name.startswith('lab.'):
                    modules = [name]
                else:
                    continue
                for module in modules:
                    target = ROOT / module.replace('.', '/')
                    self.assertTrue(target.with_suffix('.py').is_file() or target.is_dir(),
                                    f'{path.name}:{node.lineno} imports {module}')
