import stat
import time

from ..config import OUTPUT_DIR

MAX_AGE_SECONDS = 6 * 60 * 60


def clean_expired_output(now=None):
    if OUTPUT_DIR.is_symlink():
        raise OSError(f"Refusing to clean symlinked output directory: {OUTPUT_DIR}")
    if not OUTPUT_DIR.is_dir():
        raise FileNotFoundError(f"Output directory does not exist: {OUTPUT_DIR}")

    cutoff = (time.time() if now is None else now) - MAX_AGE_SECONDS
    entries = list(OUTPUT_DIR.rglob("*"))
    removed = 0
    failures = []

    directories = [OUTPUT_DIR]
    for path in entries:
        if path.is_symlink():
            continue
        try:
            if path.is_dir():
                directories.append(path)
        except OSError as error:
            failures.append(f"{path}: {error}")

    for directory in directories:
        try:
            mode = stat.S_IMODE(directory.stat().st_mode)
            directory.chmod(mode | stat.S_IWUSR | stat.S_IXUSR)
        except OSError as error:
            failures.append(f"{directory}: {error}")

    for path in sorted(entries, key=lambda item: len(item.parts), reverse=True):
        try:
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if metadata.st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError as error:
            failures.append(f"{path}: {error}")

    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            if directory != OUTPUT_DIR and not any(directory.iterdir()):
                directory.rmdir()
                removed += 1
        except OSError as error:
            failures.append(f"{directory}: {error}")

    if failures:
        raise OSError("Some expired output entries could not be cleaned:\n" + "\n".join(failures))

    return removed


if __name__ == "__main__":
    print(f"Removed {clean_expired_output()} expired output entries.")
