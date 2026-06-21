# Cython Compilation for Self-Hosted Images

## Goal

Protect Python source code IP in selfhosted Docker images by compiling to native extensions.

## Approach

Compile `.py` files to `.so` (Linux) / `.pyd` (Windows) using Cython. Only compiled binaries ship in release images; dev images stay raw Python for debugging.

## What Gets Compiled

```
src/context_service/
  *.py          -> *.so (compiled)
  __init__.py   -> keep as .py (required for package structure)
  py.typed      -> remove (no type hints in compiled code)
```

Entrypoints stay as minimal `.py` stubs that import from compiled modules.

## Build Changes

### New: `docker/Dockerfile.compile`

Multi-stage build that compiles before packaging:

```dockerfile
# Stage 1: Compile Python to C extensions
FROM python:3.13-slim AS compiler

WORKDIR /build
RUN pip install cython setuptools

COPY src/ /build/src/
COPY scripts/compile_cython.py /build/

# Compile all .py (except __init__.py) to .so
RUN python compile_cython.py src/context_service

# Stage 2: Build deps (same as current)
FROM python:3.13-slim AS builder
# ... existing dep installation ...

# Stage 3: Runtime (compiled code only)
FROM python:3.13-slim

COPY --from=compiler /build/src/ /app/src/
COPY --from=builder /app/.venv /app/.venv
# ... rest of setup ...
```

### New: `scripts/compile_cython.py`

```python
#!/usr/bin/env python3
"""Compile Python source to Cython extensions."""

import os
import sys
from pathlib import Path
from Cython.Build import cythonize
from setuptools import Extension

def find_modules(src_dir: Path) -> list[Extension]:
    """Find all .py files except __init__.py."""
    extensions = []
    for py_file in src_dir.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        # Convert path to module name
        rel_path = py_file.relative_to(src_dir.parent)
        module_name = str(rel_path.with_suffix("")).replace("/", ".")
        extensions.append(Extension(module_name, [str(py_file)]))
    return extensions

def main():
    src_dir = Path(sys.argv[1])
    extensions = find_modules(src_dir)
    
    cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
        },
        build_dir="build",
        force=True,
    )
    
    # Build .so files
    from setuptools import setup
    setup(
        ext_modules=extensions,
        script_args=["build_ext", "--inplace"],
    )
    
    # Remove .py files (keep __init__.py)
    for py_file in src_dir.rglob("*.py"):
        if py_file.name != "__init__.py":
            py_file.unlink()
    
    # Remove .c intermediate files
    for c_file in src_dir.rglob("*.c"):
        c_file.unlink()

if __name__ == "__main__":
    main()
```

## Workflow Changes

### `publish-selfhosted.yml`

Use `Dockerfile.selfhosted.compiled` for release builds:

```yaml
- name: Build and push compiled API image
  uses: docker/build-push-action@v6
  with:
    file: docker/Dockerfile.selfhosted.compiled
    # ...
```

### Keep existing Dockerfiles

- `Dockerfile.api` - dev/beta, raw Python (debugging)
- `Dockerfile.selfhosted.api` - rename to `Dockerfile.selfhosted.compiled`
- Add build arg to toggle compilation for testing

## Limitations

1. **Stack traces** - line numbers won't match, debugging harder
2. **Dynamic imports** - some metaprogramming may break (test thoroughly)
3. **Type hints** - stripped at compile time (fine for runtime)
4. **Build time** - adds ~2-3 min to image build

## Testing

1. Run full test suite against compiled image
2. Verify MCP tools work
3. Verify Dagster jobs run
4. Verify FastAPI routes respond
5. Spot-check that no .py files exist in image (except __init__.py)

## Verification

```bash
# Check no source in image
docker run --rm engrammic-api:compiled \
  find /app/src -name "*.py" ! -name "__init__.py" | wc -l
# Should output: 0

# Check .so files exist
docker run --rm engrammic-api:compiled \
  find /app/src -name "*.so" | head -5
```

## Rollout

1. [ ] Create `scripts/compile_cython.py`
2. [ ] Create `docker/Dockerfile.selfhosted.compiled`
3. [ ] Test locally: `docker build -f docker/Dockerfile.selfhosted.compiled -t test .`
4. [ ] Run integration tests against compiled image
5. [ ] Update `publish-selfhosted.yml` to use compiled Dockerfile
6. [ ] Tag v0.4.1 with compiled images

## Future

- Consider Nuitka for even stronger protection (full native compilation)
- PyArmor for license-tied obfuscation if needed
