import argparse
import ast
import contextlib
import io
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_function(filename, name, namespace):
    # Isolate these functions from optional MCP, retrieval and server dependencies.
    source = ROOT / 'scripts' / filename
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace[name]


class RegressionTests(unittest.TestCase):
    def test_native_path_separator_preserves_drive_letters(self):
        parse = load_function('mcp_server.py', '_parse_kb_paths',
                              dict(argparse=argparse, os=os, sys=sys, Path=Path))
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / 'one', Path(directory) / 'two']
            for path in paths:
                path.mkdir()
            with patch.object(sys, 'argv', ['server', '--kb-paths', os.pathsep.join(map(str, paths))]):
                self.assertEqual(parse(), [path.resolve() for path in paths])
            with patch.object(sys, 'argv', ['server', '--kb', str(paths[0])]):
                self.assertEqual(parse(), [paths[0].resolve()])

    def test_mixed_case_groups_preserve_original_prefix(self):
        group = load_function('scan_library.py', 'suggest_search_groups', dict(re=re))
        result = group([{'name': 'Civil_Part 1.md', 'relative_path': 'a.md'},
                        {'name': 'Civil_CHAPTER 2.md', 'relative_path': 'b.md'}])
        self.assertEqual(result, [{'group': 'Civil', 'files': ['a.md', 'b.md'], 'count': 2}])

    def test_loopback_default_and_explicit_public_warning(self):
        uvicorn = Mock()
        main = load_function('api_server.py', 'main',
                             dict(argparse=argparse, sys=sys, uvicorn=uvicorn, _init_kb_paths=Mock()))
        for args, expected, warning in [([], '127.0.0.1', False), (['--host', '0.0.0.0'], '0.0.0.0', True)]:
            with self.subTest(args=args), patch.object(sys, 'argv', ['server', *args]):
                output = io.StringIO()
                with contextlib.redirect_stderr(output):
                    main()
                self.assertEqual(uvicorn.run.call_args.kwargs['host'], expected)
                self.assertEqual('不含鉴权' in output.getvalue(), warning)


if __name__ == '__main__':
    unittest.main()
