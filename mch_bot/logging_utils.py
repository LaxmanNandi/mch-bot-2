import logging
from logging import Logger
from pathlib import Path


def setup_logging(level: int = logging.INFO, log_dir: str = "logs", filename: str = "latest.log") -> None:
    """Configure console + file logging.

    Safe to call multiple times; avoids adding duplicate handlers.
    """
    fmt = "%(asctime)s %(levelname)s %(name)s - %(message)s"
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate console handlers
    has_stream = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root.handlers)
    if not has_stream:
        sh = logging.StreamHandler()
        sh.setLevel(level)
        sh.setFormatter(logging.Formatter(fmt))
        root.addHandler(sh)

    # File handler
    try:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_path = log_path / filename
        has_file = any(isinstance(h, logging.FileHandler) for h in root.handlers)
        if not has_file:
            fh = logging.FileHandler(file_path, encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter(fmt))
            root.addHandler(fh)
    except Exception:
        # If filesystem not writable, continue with console-only
        pass
