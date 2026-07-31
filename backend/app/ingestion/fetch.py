"""Corpus acquisition — architecture.md §10.1.

A shallow clone into a local cache, refreshed on later runs. Shallow because
the corpus is ~35 MB of text and no history is needed; refresh rather than
re-clone so a second ingest costs a fetch instead of a download.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

CORPUS_URL = "https://github.com/ChatPRD/lennys-podcast-transcripts.git"
DEFAULT_CACHE = Path("data/corpus")
EPISODES_SUBDIR = "episodes"


class FetchError(RuntimeError):
    """The corpus could not be obtained."""


def _run(args: list[str], cwd: Path | None = None) -> None:
    try:
        subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError as exc:
        raise FetchError("git is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise FetchError("git timed out fetching the corpus.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()
        raise FetchError(f"git failed: {detail[-1] if detail else exc.returncode}") from exc


def ensure_corpus(
    cache_dir: Path = DEFAULT_CACHE, *, url: str = CORPUS_URL, refresh: bool = True
) -> Path:
    """Clone or refresh the corpus. Returns the `episodes/` directory."""
    cache_dir = Path(cache_dir)

    if (cache_dir / ".git").is_dir():
        if refresh:
            log.info("refreshing corpus", extra={"path": str(cache_dir)})
            try:
                _run(["git", "fetch", "--depth", "1", "origin"], cwd=cache_dir)
                _run(["git", "reset", "--hard", "origin/HEAD"], cwd=cache_dir)
            except FetchError as exc:
                # A refresh failure must not block ingesting what we already
                # have — offline runs are a supported case.
                log.warning("corpus refresh failed, using cached copy",
                            extra={"error": str(exc)})
    else:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        log.info("cloning corpus", extra={"url": url, "path": str(cache_dir)})
        _run(["git", "clone", "--depth", "1", "--quiet", url, str(cache_dir)])

    episodes = cache_dir / EPISODES_SUBDIR
    if not episodes.is_dir():
        raise FetchError(
            f"expected '{EPISODES_SUBDIR}/' inside the corpus at {cache_dir}; "
            "the upstream layout may have changed."
        )
    return episodes


def local_corpus(path: Path) -> Path:
    """Use an already-present corpus directory, skipping any network access."""
    path = Path(path)
    episodes = path / EPISODES_SUBDIR if (path / EPISODES_SUBDIR).is_dir() else path
    if not episodes.is_dir():
        raise FetchError(f"no episodes directory found at {path}")
    return episodes
