"""Docker sandbox executor — the untrusted-code boundary (T5).

Given a language, a model's code, and a problem's hidden tests, runs them inside
a locked-down, resource-capped, network-isolated Docker container and returns an
:class:`~bench.types.ExecResult`. This is the harness's core safety guarantee:
LLM-generated code never touches the host.

Per-language filenames, import forms, and test runners are defined by the
INVOCATION ABI documented in :mod:`bench.types`.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from bench.types import ExecResult, Language

# Directory holding the bundled Dockerfiles (docker/Dockerfile.<lang>).
_DOCKER_DIR = Path(__file__).resolve().parent.parent / "docker"


@dataclass(frozen=True)
class LangAdapter:
    """How to lay out files and run tests for one language inside the sandbox."""

    image: str
    dockerfile: str
    solution_file: str
    test_file: str
    tmpfs_size: str
    # A `sh -c` command run inside the container. It copies the two source files
    # from the read-only /workspace mount into a writable tmpfs and runs the
    # tests there (so the container root fs can stay --read-only).
    run_script: str


_ADAPTERS: dict[Language, LangAdapter] = {
    Language.python: LangAdapter(
        image="llm-codebench-python",
        dockerfile="Dockerfile.python",
        solution_file="solution.py",
        test_file="test_solution.py",
        tmpfs_size="128m",
        run_script=(
            "mkdir -p /tmp/work && "
            "cp /workspace/solution.py /workspace/test_solution.py /tmp/work/ && "
            "cd /tmp/work && "
            "python -m pytest -q -p no:cacheprovider test_solution.py"
        ),
    ),
    Language.typescript: LangAdapter(
        image="llm-codebench-typescript",
        dockerfile="Dockerfile.typescript",
        solution_file="solution.ts",
        test_file="tests.ts",
        tmpfs_size="128m",
        run_script=(
            "mkdir -p /tmp/work && "
            "cp /workspace/solution.ts /workspace/tests.ts /tmp/work/ && "
            "cd /tmp/work && "
            "tsx tests.ts"
        ),
    ),
    Language.csharp: LangAdapter(
        image="llm-codebench-csharp",
        dockerfile="Dockerfile.csharp",
        solution_file="Solution.cs",
        test_file="Tests.cs",
        tmpfs_size="512m",
        run_script=(
            "cp -r /app /tmp/work && "
            "cp /workspace/Solution.cs /workspace/Tests.cs /tmp/work/ && "
            "rm -f /tmp/work/Program.cs && "
            "cd /tmp/work && "
            "DOTNET_CLI_HOME=/tmp dotnet run --no-restore -c Release"
        ),
    ),
    Language.bash: LangAdapter(
        image="llm-codebench-bash",
        dockerfile="Dockerfile.bash",
        solution_file="solution.sh",
        test_file="tests.sh",
        tmpfs_size="64m",
        run_script=(
            "mkdir -p /tmp/work && "
            "cp /workspace/solution.sh /workspace/tests.sh /tmp/work/ && "
            "cd /tmp/work && "
            "bash tests.sh"
        ),
    ),
}


class SandboxError(RuntimeError):
    """Raised for environment problems (Docker missing, image build failed)."""


async def _run(*argv: str, timeout: float | None = None) -> tuple[int, str, str]:
    """Run a subprocess, returning ``(exit_code, stdout, stderr)``."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def docker_available() -> bool:
    """Return True if the Docker daemon is reachable."""
    try:
        code, _, _ = await _run("docker", "info", timeout=30)
        return code == 0
    except (FileNotFoundError, asyncio.TimeoutError):
        return False


async def _image_exists(tag: str) -> bool:
    try:
        code, _, _ = await _run("docker", "image", "inspect", tag, timeout=30)
        return code == 0
    except (FileNotFoundError, asyncio.TimeoutError):
        return False


async def ensure_images(languages: list[Language] | None = None) -> None:
    """Build any missing per-language sandbox images. Idempotent.

    Raises :class:`SandboxError` if Docker is unavailable or a build fails, with
    a message pointing at the offending Dockerfile.
    """
    if not await docker_available():
        raise SandboxError(
            "Docker is not available. Install Docker and ensure the daemon is "
            "running (the sandbox executes untrusted model code — it is required "
            "for anything but --dry-run)."
        )

    targets = languages or list(Language)
    for language in targets:
        adapter = _ADAPTERS[language]
        if await _image_exists(adapter.image):
            continue
        dockerfile = _DOCKER_DIR / adapter.dockerfile
        if not dockerfile.is_file():
            raise SandboxError(f"missing Dockerfile: {dockerfile}")
        code, out, err = await _run(
            "docker", "build", "-t", adapter.image,
            "-f", str(dockerfile), str(_DOCKER_DIR),
            timeout=1800,
        )
        if code != 0:
            raise SandboxError(
                f"failed to build sandbox image {adapter.image!r} from "
                f"{dockerfile}:\n{(err or out)[-2000:]}"
            )


def _docker_run_argv(adapter: LangAdapter, image: str, workspace: Path, name: str) -> list[str]:
    """Assemble the hardened `docker run` command for one execution."""
    return [
        "docker", "run", "--rm",
        "--name", name,
        "--network", "none",
        "--memory", "256m",
        "--cpus", "1",
        "--pids-limit", "512",
        "--read-only",
        "--tmpfs", f"/tmp:size={adapter.tmpfs_size},exec",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{workspace}:/workspace:ro",
        "-w", "/workspace",
        image,
        "sh", "-c", adapter.run_script,
    ]


async def run_in_sandbox(
    language: Language,
    code: str,
    tests: str,
    *,
    timeout: float,
    image_tag: str | None = None,
) -> ExecResult:
    """Execute ``code`` against ``tests`` in an isolated container.

    ``timeout`` is the wall-clock budget in seconds; if exceeded the container is
    killed and ``timed_out=True`` is returned. ``image_tag`` overrides the
    default per-language image (``Problem.image_tag``).
    """
    adapter = _ADAPTERS[language]
    image = image_tag or adapter.image
    name = f"llm-codebench-{uuid.uuid4().hex[:16]}"

    tmpdir = Path(tempfile.mkdtemp(prefix="llm-codebench-sandbox-"))
    try:
        (tmpdir / adapter.solution_file).write_text(code, encoding="utf-8")
        (tmpdir / adapter.test_file).write_text(tests, encoding="utf-8")

        argv = _docker_run_argv(adapter, image, tmpdir, name)
        start = time.perf_counter()
        try:
            exit_code, stdout, stderr = await _run(*argv, timeout=timeout)
            timed_out = False
        except asyncio.TimeoutError:
            # Best-effort kill; container is --rm so it cleans itself up.
            await _run("docker", "kill", name, timeout=30)
            exit_code, stdout, stderr, timed_out = 124, "", (
                f"execution exceeded {timeout:.1f}s wall-clock timeout"
            ), True
        duration_ms = (time.perf_counter() - start) * 1000.0

        return ExecResult(
            passed=(exit_code == 0 and not timed_out),
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


__all__ = [
    "run_in_sandbox",
    "ensure_images",
    "docker_available",
    "SandboxError",
    "LangAdapter",
]
