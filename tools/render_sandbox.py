"""Run agent commands in short-lived Render Sandboxes when deployed there."""

from __future__ import annotations

import contextvars
import os
import shlex
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from tools.files import IGNORED_DIRECTORIES
from tools.workspace import get_workspace


REMOTE_WORKSPACE = "/workspace"
MAX_SYNC_BYTES = 100_000_000
MAX_COMMAND_SECONDS = 30
IGNORED_FILES = {
    ".env",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
}
IGNORED_SECRET_DIRECTORIES = {".ssh", ".aws", ".azure"}
_session = contextvars.ContextVar("render_sandbox_session", default=None)


def execution_mode():
    configured = os.environ.get("AGENT_EXECUTION_MODE", "").strip().lower()
    if configured:
        return configured
    return "render" if os.environ.get("RENDER") == "true" else "local"


def _is_sensitive_name(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in IGNORED_FILES
        or lowered.startswith(".env.")
        or lowered.endswith((".pem", ".key", ".p12", ".pfx", ".token", ".secret"))
    )


def _copy_workspace_to_staging(destination: Path) -> None:
    workspace = get_workspace()
    total = 0
    for directory, child_directories, filenames in os.walk(workspace, followlinks=False):
        base = Path(directory)
        relative_dir = base.relative_to(workspace)
        child_directories[:] = [
            name for name in child_directories
            if name.casefold() not in IGNORED_DIRECTORIES
            and name.casefold() not in IGNORED_SECRET_DIRECTORIES
            and not _is_sensitive_name(name)
            and not (base / name).is_symlink()
        ]
        for filename in filenames:
            source = base / filename
            if source.is_symlink() or _is_sensitive_name(filename):
                continue
            total += source.stat().st_size
            if total > MAX_SYNC_BYTES:
                raise ValueError("Workspace is too large to copy into an isolated sandbox.")
            target = destination / relative_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def _safe_extract_workspace(archive: Path, destination: Path) -> set[str]:
    extracted = set()
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            name = member.name.removeprefix("./")
            relative = PurePosixPath(name)
            if "\\" in name or relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Sandbox returned an unsafe file path.")
            if not name or member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Sandbox returned a link or special file; refusing to copy it back.")
            if any(
                part.casefold() in IGNORED_DIRECTORIES | IGNORED_SECRET_DIRECTORIES
                or _is_sensitive_name(part)
                for part in relative.parts
            ):
                continue
            if _is_sensitive_name(relative.name):
                continue
            total += member.size
            if total > MAX_SYNC_BYTES:
                raise ValueError("Sandbox output is too large to copy back safely.")
            source = bundle.extractfile(member)
            if source is None:
                continue
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.add(relative.as_posix())
    return extracted


class RenderSandboxSession:
    def __init__(self):
        from render import Render

        self.client = Render()
        self.sandbox = None

    def __enter__(self):
        return self

    def _ensure_sandbox(self):
        if self.sandbox is not None:
            return
        group_id = os.environ.get("RENDER_SANDBOX_GROUP_ID")
        options = {
            "plan": os.environ.get("RENDER_SANDBOX_PLAN", "1c-2g"),
            "timeout_seconds": 900,
            "idle_timeout_seconds": 300,
            "network_policy": "allow-list",
            "wait": True,
        }
        if group_id:
            options["sandbox_group_id"] = group_id
        from render.sandbox import EgressRule, NetworkPolicy

        options["network_policy"] = NetworkPolicy(
            type="allow-list",
            rules=[
                EgressRule(domain="pypi.org"),
                EgressRule(domain="files.pythonhosted.org"),
                EgressRule(domain="registry.npmjs.org"),
                EgressRule(domain="github.com"),
                EgressRule(domain="codeload.github.com"),
            ],
        )
        try:
            self.sandbox = self.client.sandboxes.create(**options)
        except Exception as error:
            sandbox_id = getattr(error, "sandbox_id", None)
            if sandbox_id:
                self.client.sandboxes.terminate(sandbox_id)
            raise

    def run(self, command: str) -> dict:
        self._ensure_sandbox()
        sandbox_id = self.sandbox.id
        with tempfile.TemporaryDirectory(prefix="agent-sandbox-upload-") as upload_dir:
            staged = Path(upload_dir) / "workspace"
            staged.mkdir()
            _copy_workspace_to_staging(staged)
            self.client.sandboxes.copy_to(sandbox_id, staged, REMOTE_WORKSPACE)

        wrapped = (
            "cd /workspace && timeout --signal=KILL "
            f"{MAX_COMMAND_SECONDS}s bash -lc {shlex.quote(command)}"
        )
        output_parts = []
        exit_code = -1
        from render.sandbox import SandboxExecExit, SandboxExecOutput

        output_size = 0
        for event in self.client.sandboxes.exec(sandbox_id, wrapped):
            if isinstance(event, SandboxExecOutput):
                available = max(0, 100_000 - output_size)
                if available:
                    output_parts.append(event.data[:available])
                    output_size += min(available, len(event.data))
            elif isinstance(event, SandboxExecExit):
                exit_code = event.exit_code

        with tempfile.TemporaryDirectory(prefix="agent-sandbox-download-") as download_dir:
            download_root = Path(download_dir)
            archive = download_root / "workspace.tar.gz"
            archive_command = (
                "tar -czf /tmp/agent-workspace.tar.gz -C /workspace "
                "--exclude=.git --exclude=.venv --exclude=venv "
                "--exclude=node_modules --exclude=__pycache__ "
                "--exclude=.pytest_cache --exclude=.mypy_cache "
                "--exclude=.ruff_cache --exclude=.next --exclude=.tox "
                ". && echo workspace-sync-complete"
            )
            for event in self.client.sandboxes.exec(sandbox_id, archive_command):
                if isinstance(event, SandboxExecExit) and event.exit_code != 0:
                    raise RuntimeError("Could not package sandbox workspace for safe download.")
            self.client.sandboxes.copy_from(
                sandbox_id, "/tmp/agent-workspace.tar.gz", str(archive)
            )
            if archive.stat().st_size > MAX_SYNC_BYTES:
                raise ValueError("Sandbox archive is too large to download safely.")
            extracted_root = download_root / "extracted"
            extracted_root.mkdir()
            remote_files = _safe_extract_workspace(archive, extracted_root)
            _replace_workspace_files(extracted_root, remote_files)

        output = "".join(output_parts).strip()
        if exit_code == -1:
            exit_code = 124 if "timed out" in output.casefold() else -1
        return {"exit_code": exit_code, "output": output}

    def __exit__(self, exc_type, exc_value, traceback):
        if self.sandbox is not None:
            self.client.sandboxes.terminate(self.sandbox.id)


def _replace_workspace_files(source_root: Path, remote_files: set[str]) -> None:
    workspace = get_workspace()
    workspace.mkdir(parents=True, exist_ok=True)
    for directory, child_directories, filenames in os.walk(workspace, topdown=False):
        base = Path(directory)
        relative_dir = base.relative_to(workspace)
        for filename in filenames:
            path = base / filename
            relative_path = path.relative_to(workspace)
            relative = relative_path.as_posix()
            protected_parent = any(
                part.casefold() in IGNORED_DIRECTORIES | IGNORED_SECRET_DIRECTORIES
                or _is_sensitive_name(part)
                for part in relative_path.parts[:-1]
            )
            if (
                relative not in remote_files
                and not protected_parent
                and not _is_sensitive_name(filename)
            ):
                path.unlink(missing_ok=True)
        for child in child_directories:
            path = base / child
            if (
                child.casefold() in IGNORED_DIRECTORIES
                or child.casefold() in IGNORED_SECRET_DIRECTORIES
                or _is_sensitive_name(child)
            ):
                continue
            if not any((source_root / relative_dir / child).rglob("*")):
                shutil.rmtree(path, ignore_errors=True)
    for relative in remote_files:
        source = source_root.joinpath(*PurePosixPath(relative).parts)
        destination = workspace.joinpath(*PurePosixPath(relative).parts)
        current = workspace
        for part in PurePosixPath(relative).parts[:-1]:
            current = current / part
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                current.unlink()
            current.mkdir(exist_ok=True)
        if destination.is_symlink():
            destination.unlink()
        shutil.copyfile(source, destination)


class job_execution:
    """Bind one isolated runner to a job and fail closed when deployed."""

    def __enter__(self):
        mode = execution_mode()
        if mode not in {"local", "render"}:
            raise RuntimeError("Agent execution is disabled in this deployment mode.")
        if os.environ.get("RENDER") == "true" and mode != "render":
            raise RuntimeError("Refusing to run agent commands outside a sandbox on Render.")
        if mode == "render" and not os.environ.get("RENDER_API_KEY"):
            raise RuntimeError("Set RENDER_API_KEY to enable isolated command execution.")
        self.token = _session.set(RenderSandboxSession() if mode == "render" else None)
        try:
            if mode == "render":
                _session.get().__enter__()
        except Exception:
            _session.reset(self.token)
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        session = _session.get()
        try:
            if session is not None:
                session.__exit__(exc_type, exc_value, traceback)
        finally:
            _session.reset(self.token)
