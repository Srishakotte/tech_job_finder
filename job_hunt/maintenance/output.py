"""Safe cleanup helpers for generated job-post assets.

No completed-job archive is kept. Files are retained only while a job is actively
waiting for approval or publishing; callers delete them when that workflow ends.
On process startup, output files from the previous process are cleared because
pending job state is in memory and cannot survive a restart. Paths are constrained
strictly to OUTPUT_DIR.
"""
from pathlib import Path
import logging
import stat
import time

from ..config import OUTPUT_DIR

logger = logging.getLogger(__name__)
MAX_AGE_SECONDS = 6 * 60 * 60
MAX_COMPLETED_JOBS = 0
JOB_ARTIFACT_SUFFIXES = (
    "_reel.mp4",
    "_card.png",
    "_caption.txt",
    "_company_logo.png",
    "_static_reel.png",
)


def _output_root():
    if OUTPUT_DIR.is_symlink():
        raise OSError(f"Refusing to clean symlinked output directory: {OUTPUT_DIR}")
    if not OUTPUT_DIR.is_dir():
        raise FileNotFoundError(f"Output directory does not exist: {OUTPUT_DIR}")
    return OUTPUT_DIR.resolve()


def _safe_output_file(path, root):
    """Return a resolved in-output file path, or None for unsafe paths."""
    candidate = Path(path)
    if candidate.is_symlink():
        logger.warning("Skipping symlink during output cleanup: %s", candidate)
        return None
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as error:
        logger.warning("Cannot resolve output path %s: %s", candidate, error)
        return None
    if resolved == root or root not in resolved.parents:
        logger.warning("Skipping path outside OUTPUT_DIR during cleanup: %s", candidate)
        return None
    return resolved


def cleanup_output_files(paths, protected_paths=()):
    """Delete explicitly named temporary files inside OUTPUT_DIR only.

    Returns the number of files removed. Protected files and symlinks are skipped.
    Cleanup failure is logged rather than interrupting Reel generation/publishing.
    """
    root = _output_root()
    protected = set()
    for path in protected_paths:
        if path:
            resolved = _safe_output_file(path, root)
            if resolved is not None:
                protected.add(resolved)

    removed = 0
    for path in paths:
        if not path:
            continue
        resolved = _safe_output_file(path, root)
        if resolved is None or resolved in protected:
            continue
        try:
            if resolved.is_file():
                resolved.unlink()
                removed += 1
        except OSError as error:
            logger.warning("Could not remove temporary output %s: %s", resolved, error)
    return removed


def _completed_prefixes(root):
    reels = []
    for path in root.glob("*_reel.mp4"):
        try:
            if not path.is_symlink() and path.is_file():
                reels.append((path.stat().st_mtime, path.name[:-len("_reel.mp4")]))
        except OSError as error:
            logger.warning("Could not inspect generated Reel %s: %s", path, error)
    reels.sort(reverse=True)
    return [prefix for _, prefix in reels]


def _prefix_from_artifact(path):
    name = Path(path).name
    for suffix in JOB_ARTIFACT_SUFFIXES:
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return None


def prune_completed_outputs(max_jobs=MAX_COMPLETED_JOBS, protected_paths=()):
    """Keep the newest completed Reel bundles plus bundles still in use.

    A bundle consists of its final Reel, caption, card and any saved static card.
    Jobs protected by a pending workflow are kept even if they are older than the
    newest `max_jobs` jobs.
    """
    root = _output_root()
    max_jobs = max(0, int(max_jobs))
    prefixes = _completed_prefixes(root)
    keep_prefixes = set(prefixes[:max_jobs])
    for path in protected_paths:
        if path:
            prefix = _prefix_from_artifact(path)
            if prefix:
                keep_prefixes.add(prefix)

    removed = 0
    for prefix in prefixes:
        if prefix in keep_prefixes:
            continue
        for suffix in JOB_ARTIFACT_SUFFIXES:
            path = root / f"{prefix}{suffix}"
            try:
                if path.is_symlink():
                    continue
                if path.is_file():
                    path.unlink()
                    removed += 1
            except OSError as error:
                logger.warning("Could not prune old job artifact %s: %s", path, error)
    return removed


def clean_expired_output(now=None, max_jobs=MAX_COMPLETED_JOBS):
    """Clear generated output left by a previous process.

    The bot stores approval/publishing state only in memory. After a process
    restart that state is gone, so old output files cannot be resumed safely and
    are removed instead of retaining a local history. The `now` and `max_jobs`
    parameters remain for compatibility with older callers.
    """
    root = _output_root()
    removed = 0
    failures = []
    entries = list(root.rglob("*"))

    # Remove deepest files/directories first. Never follow or delete symlinks.
    for path in sorted(entries, key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_symlink():
                continue
            if path.is_file():
                path.unlink()
                removed += 1
            elif path.is_dir():
                try:
                    mode = stat.S_IMODE(path.stat().st_mode)
                    path.chmod(mode | stat.S_IWUSR | stat.S_IXUSR)
                except OSError:
                    pass
                if not any(path.iterdir()):
                    path.rmdir()
                    removed += 1
        except OSError as error:
            failures.append(f"{path}: {error}")

    if failures:
        logger.warning("Some previous output entries could not be cleaned: %s", " | ".join(failures))
    return removed


if __name__ == "__main__":
    print(f"Removed {clean_expired_output()} expired output entries.")
