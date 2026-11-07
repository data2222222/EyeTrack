"""Normalizing the user's blocked sites and apps. Pure logic: no GUI, camera or psutil imports.

Sites are stored as bare lowercase hostnames ("reddit.com"); the extension blocks the host and every
subdomain. Apps are stored as normalized process names ("discord"); a name matches a running process
whose name starts with it. Invalid entries are dropped, never repaired into something broader.
"""
import ipaddress
import re

MAX_ENTRIES = 100
MIN_APP_CHARS = 3        # "a" or "sy" would match far too many processes
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_APP = re.compile(r"^[a-z0-9][a-z0-9 ._+-]*$")


def normalize_site(value):
    """'https://www.Reddit.com/r/all?x=1' -> 'reddit.com'; None when it is not a usable domain."""
    if not isinstance(value, str):
        return None
    text = value.strip().casefold()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = re.split(r"[/?#\s]", text, maxsplit=1)[0]
    text = text.rsplit("@", 1)[-1].rsplit(":", 1)[0].strip(".")
    if text.startswith("www."):
        text = text[4:]
    if len(text) > 253 or "." not in text:
        return None                          # single labels (localhost) are never blocked
    try:
        ipaddress.ip_address(text)
        return None                          # addresses are not "sites"
    except ValueError:
        pass
    try:
        text = text.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    return text if all(_LABEL.match(label) for label in text.split(".")) else None


def normalize_app(value):
    """'Discord.exe' -> 'discord'; None when empty, too short or not a plausible process name."""
    if not isinstance(value, str):
        return None
    name = value.strip().casefold()
    for suffix in (".exe", ".app"):
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    if len(name) < MIN_APP_CHARS or len(name) > 64 or not _APP.match(name):
        return None
    return name


def clean_list(values, normalize):
    """Normalized, de-duplicated, sorted entries from any list-like value; [] for anything else."""
    if not isinstance(values, (list, tuple)):
        return []
    return sorted({entry for entry in map(normalize, values) if entry})[:MAX_ENTRIES]


def clean_sites(values):
    return clean_list(values, normalize_site)


def clean_apps(values):
    return clean_list(values, normalize_app)
