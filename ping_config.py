"""Atomic ping-target persistence, independent of Tk and application defaults."""
import configparser
import os
from pathlib import Path
import tempfile


def save_ping_settings(path, **settings):
    """Write only requested ping keys; never serialize application defaults."""
    save_settings(path, "ping", settings, remove=("targets",))


def save_window_settings(path, **settings):
    save_settings(path, "window", settings)


def save_settings(path, section, settings, remove=()):
    """Shared atomic selective persistence for ping and window preferences."""
    path = Path(path)
    cfg = configparser.ConfigParser()
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            cfg.read_file(stream)
    if not cfg.has_section(section):
        cfg.add_section(section)
    for key in remove:
        cfg.remove_option(section, key)
    for key, value in settings.items():
        cfg[section][key] = str(value)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            cfg.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
