#!/usr/bin/env python3
"""Compile Python source to Cython extensions for IP protection.

Usage:
    python scripts/compile_cython.py src/context_service

Compiles all .py files (except __init__.py) to native .so extensions,
then removes original source. The result runs identically but without
readable source code.

Based on: https://shawinnes.com/protecting-python/
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
import sys
from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup


def uses_pep695_syntax(py_file: Path) -> bool:
    """Check if file uses PEP 695 type parameter syntax (def foo[T]()).

    Cython doesn't support this yet, so we skip these files.
    """
    import re
    content = py_file.read_text()
    # Match: def name[T] or async def name[T]
    return bool(re.search(r"def \w+\[", content))


def find_py_files(src_dir: Path) -> tuple[list[Path], list[Path]]:
    """Find all .py files except __init__.py.

    Returns (compilable, skipped) where skipped contains files
    with unsupported syntax or that must remain as .py for runtime reasons.
    """
    # Files that must stay as .py:
    # - entrypoint.py/__main__.py: `python -m` needs __code__ object
    # - Pydantic models with methods break when compiled (methods appear as fields)
    # - api/: FastAPI dependency injection breaks (Header, Depends, etc.)
    skip_files = {"entrypoint.py", "__main__.py"}
    skip_dirs = {"api", "config", "models", "retention", "schemas", "test"}

    compilable = []
    skipped = []
    for py_file in src_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        if py_file.name in skip_files:
            skipped.append(py_file)
            continue
        if any(d in py_file.parts for d in skip_dirs):
            skipped.append(py_file)
            continue
        if uses_pep695_syntax(py_file):
            skipped.append(py_file)
            continue
        compilable.append(py_file)
    return compilable, skipped


def build_extensions(py_files: list[Path], src_root: Path) -> list[Extension]:
    """Build Extension objects for cythonize."""
    extensions = []
    for py_file in py_files:
        rel_path = py_file.relative_to(src_root.parent)
        module_name = str(rel_path.with_suffix("")).replace(os.sep, ".")
        extensions.append(Extension(module_name, [str(py_file)]))
    return extensions


def compile_package(src_dir: Path) -> None:
    """Compile all Python files in src_dir to Cython extensions."""
    print(f"Compiling {src_dir}...")

    py_files, skipped = find_py_files(src_dir)
    print(f"Found {len(py_files)} files to compile, {len(skipped)} skipped")

    if skipped:
        for f in skipped:
            print(f"  Skipping: {f.relative_to(src_dir)}")

    if not py_files:
        print("No files to compile")
        return

    extensions = build_extensions(py_files, src_dir)

    # Cythonize with optimizations
    ext_modules = cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "embedsignature": False,
            "emit_code_comments": False,
        },
        nthreads=multiprocessing.cpu_count(),
    )

    # Build in-place with parallel compilation
    nproc = multiprocessing.cpu_count()
    orig_argv = sys.argv
    sys.argv = ["setup.py", "build_ext", "--inplace", f"-j{nproc}"]
    try:
        setup(
            name="context_service",
            ext_modules=ext_modules,
            script_args=["build_ext", "--inplace", f"-j{nproc}"],
        )
    finally:
        sys.argv = orig_argv

    print("Compilation successful")

    # Remove original .py files (keep __init__.py)
    removed = 0
    for py_file in py_files:
        if py_file.exists():
            py_file.unlink()
            removed += 1
    print(f"Removed {removed} .py files")

    # Remove .c intermediate files
    for c_file in src_dir.rglob("*.c"):
        c_file.unlink()
    print("Removed intermediate .c files")

    # Remove py.typed marker
    py_typed = src_dir / "py.typed"
    if py_typed.exists():
        py_typed.unlink()

    # Remove build directory
    build_dir = src_dir.parent / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # Verify
    so_files = list(src_dir.rglob("*.so"))
    py_remaining = [f for f in src_dir.rglob("*.py") if f.name != "__init__.py"]

    # Skipped files are expected to remain
    unexpected = [f for f in py_remaining if f not in skipped]

    print(f"\nResult: {len(so_files)} .so files, {len(skipped)} skipped .py, {len(unexpected)} unexpected .py")

    if unexpected:
        print("ERROR: Unexpected uncompiled files:")
        for f in unexpected[:10]:
            print(f"  {f}")
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <src_dir>")
        sys.exit(1)

    src_dir = Path(sys.argv[1])
    if not src_dir.exists():
        print(f"Error: {src_dir} does not exist")
        sys.exit(1)

    compile_package(src_dir)


if __name__ == "__main__":
    main()
