"""event-ops-engine: rule-based capacity status and promotion judgement for event sessions."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("event-ops-engine")
except PackageNotFoundError:  # a source tree on sys.path without an install
    __version__ = "0+unknown"
