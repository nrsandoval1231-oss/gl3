"""Stage a private selective wrapper; it never executes or installs it."""

from __future__ import annotations

import argparse
import ast
import errno
import hashlib
import os
import stat
from pathlib import Path

EXPECTED_WRAPPER_SHA256 = "1cedfc857f6e29e818098f5fbd2e7ae3c691221467864779e350768b1dfd1920"
EXPECTED_WRAPPER_AST_SHA256 = "f70761b76d98087a2e2d90c1569c05bfbf3dd102c5e41e7ef47cf5a79ba4f88c"
EXPECTED_COMMAND_AST_SHA256 = "a40c5cc646adaae3b23c3d5f8fb81cf1792eacfd1322320bd0a922651f34d3b8"
EXPECTED_ALL_SERVICE_SUFFIX = ("up", "-d", "--no-build")


def _ast_digest(node: ast.AST) -> str:
    return hashlib.sha256(
        ast.dump(node, annotate_fields=True, include_attributes=False).encode()
    ).hexdigest()


def _offset(source: str, line: int, column: int = 0) -> int:
    return sum(len(part) for part in source.splitlines(keepends=True)[: line - 1]) + column


def _literal_tail(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, ast.List):
        return None
    result = []
    for value in node.elts[-3:]:
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return None
        result.append(value.value)
    return tuple(result)


def _render(source: str) -> str:
    tree = ast.parse(source)
    if _ast_digest(tree) != EXPECTED_WRAPPER_AST_SHA256:
        raise ValueError("wrapper AST identity is not authorized")
    main = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"),
        None,
    )
    if main is None or len(main.body) < 5:
        raise ValueError("wrapper shape is not authorized")
    command = next(
        (
            node
            for node in main.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "command" for target in node.targets
            )
        ),
        None,
    )
    env = next(
        (
            node
            for node in main.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "env" for target in node.targets)
        ),
        None,
    )
    validate = next(
        (
            node
            for node in main.body
            if isinstance(node, ast.If) and "--validate-only" in ast.unparse(node.test)
        ),
        None,
    )
    no_arguments = next(
        (
            node
            for node in main.body
            if isinstance(node, ast.If)
            and node is not validate
            and "sys.argv" in ast.unparse(node.test)
        ),
        None,
    )
    if not all((command, env, validate, no_arguments)):
        raise ValueError("wrapper control flow is not authorized")
    if _ast_digest(command.value) != EXPECTED_COMMAND_AST_SHA256:
        raise ValueError("wrapper command identity is not authorized")
    if _literal_tail(command.value) != EXPECTED_ALL_SERVICE_SUFFIX:
        raise ValueError("wrapper command suffix is not the observed all-service startup")
    if not isinstance(command.value, ast.List):
        raise ValueError("wrapper command must be a literal list")
    command_prefix = ast.unparse(ast.List(elts=command.value.elts[:-3]))
    before_dispatch = source[: _offset(source, validate.end_lineno + 1)]
    env_source = ast.get_source_segment(source, env)
    execute = next(
        (
            node
            for node in main.body
            if isinstance(node, ast.Expr) and "execvpe" in ast.unparse(node)
        ),
        None,
    )
    module_guard = next(
        (node for node in tree.body if isinstance(node, ast.If) and node is not main),
        None,
    )
    if not env_source or execute is None or module_guard is None:
        raise ValueError("wrapper execution shape is not authorized")
    execute_source = ast.get_source_segment(source, execute)
    guard_source = ast.get_source_segment(source, module_guard)
    if not execute_source or not guard_source:
        raise ValueError("wrapper source segments are unavailable")
    dispatch = """    if not sys.argv[1:]:
        raise SystemExit("explicit operation required")
    operation, *arguments = sys.argv[1:]
    static_operations = {
        "stop-app": ["stop", "api", "worker", "browse", "web"],
        "migrate": ["run", "--rm", "--no-deps", "migrate"],
        "rebuild-browse": [
            "run",
            "--rm",
            "--no-deps",
            "browse",
            "uv",
            "run",
            "python",
            "-m",
            "gridlens.jobs.browse",
            "rebuild",
        ],
        "browse-status": [
            "run", "--rm", "--no-deps", "browse", "uv", "run", "python", "-m",
            "gridlens.jobs.browse", "status",
        ],
        "stage-browse": [
            "run", "--rm", "--no-deps", "browse", "uv", "run", "python", "-m",
            "gridlens.jobs.browse", "stage-recovery",
        ],
        "start-canary": ["up", "-d", "--no-build", "--no-deps", "api", "web"],
        "start-workers": ["up", "-d", "--no-build", "--no-deps", "worker", "browse"],
    }
    generation_operations = {
        "inspect-browse": "inspect-recovery",
        "publish-browse": "publish-recovery",
    }
    if operation in generation_operations:
        if len(arguments) != 1:
            raise SystemExit(operation + " requires exactly one generation UUID")
        import uuid
        try:
            generation = str(uuid.UUID(arguments[0]))
        except ValueError:
            raise SystemExit(operation + " generation must be a canonical UUID") from None
        if generation != arguments[0]:
            raise SystemExit(operation + " generation must be a canonical UUID")
        suffix = [
            "run",
            "--rm",
            "--no-deps",
            "browse",
            "uv",
            "run",
            "python",
            "-m",
            "gridlens.jobs.browse",
            generation_operations[operation],
            "--generation",
            generation,
        ]
    elif operation in static_operations and not arguments:
        suffix = static_operations[operation]
    else:
        raise SystemExit("operation is not authorized")
"""
    return (
        '"""Protected selective release wrapper; staged locally and not installed."""\n'
        + before_dispatch
        + dispatch
        + "    "
        + env_source
        + "\n    command = "
        + command_prefix
        + " + suffix\n    "
        + execute_source
        + "\n\n"
        + guard_source
        + "\n"
    )


def stage_release_wrapper(input_path: Path, output_path: Path) -> None:
    if not input_path.is_file() or input_path.is_symlink():
        raise ValueError("input must be an ordinary file")
    raw_source = input_path.read_bytes()
    if hashlib.sha256(raw_source).hexdigest() != EXPECTED_WRAPPER_SHA256:
        raise ValueError("wrapper byte identity is not authorized")
    try:
        source = raw_source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("wrapper is not valid UTF-8") from error
    staged = _render(source)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(output_path, flags, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as error:
        if error.errno == errno.EEXIST:
            raise FileExistsError("refusing to replace an existing output") from None
        raise
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(staged)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage_release_wrapper(args.input, args.output)
    print("staged selective wrapper locally; it was not executed or installed")


if __name__ == "__main__":
    main()
