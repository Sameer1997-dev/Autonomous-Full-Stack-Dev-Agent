import os
from pathlib import Path


WORKSPACE = Path("workspace").resolve()
MAX_FILE_SIZE_BYTES = 1_000_000
IGNORED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".next",
    "node_modules",
}


def _workspace_path(filename):
    normalized = str(filename).replace("\\", "/")

    if normalized.startswith("workspace/"):
        normalized = normalized[len("workspace/") :]

    candidate = Path(normalized)

    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Path must stay inside the workspace.")

    path = (WORKSPACE / candidate).resolve()

    try:
        path.relative_to(WORKSPACE)
    except ValueError as error:
        raise ValueError("Path must stay inside the workspace.") from error

    return path


def list_files():
    """Return files inside the agent workspace."""
    if not WORKSPACE.exists():
        WORKSPACE.mkdir(parents=True)

    files = []

    for directory, child_directories, filenames in os.walk(WORKSPACE):
        child_directories[:] = [
            name
            for name in child_directories
            if name.casefold() not in IGNORED_DIRECTORIES
            and not (Path(directory) / name).is_symlink()
        ]

        for filename in filenames:
            path = Path(directory) / filename

            if (
                path.suffix.casefold() not in {".pyc", ".pyo"}
                and path.resolve().is_relative_to(WORKSPACE)
            ):
                files.append(path.relative_to(WORKSPACE).as_posix())

    return files


def read_file(filename):
    """Read a file from the workspace."""
    path = _workspace_path(filename)

    if not path.is_file():
        return f"File not found: {filename}"

    if path.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File exceeds the {MAX_FILE_SIZE_BYTES}-byte read limit: {filename}"
        )

    return path.read_text(encoding="utf-8")


def write_file(filename, content):
    """Create or overwrite a file in the workspace."""
    if len(content.encode("utf-8")) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"Content exceeds the {MAX_FILE_SIZE_BYTES}-byte write limit."
        )

    path = _workspace_path(filename)

    path.parent.mkdir(parents=True, exist_ok=True)

    path = _workspace_path(filename)
    path.write_text(content, encoding="utf-8")

    return f"File written successfully: {filename}"