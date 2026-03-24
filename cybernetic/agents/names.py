"""Funny trading-themed name generation for agents."""
import random
import re

_ADJECTIVES = [
    "diamond",
    "golden",
    "stealth",
    "quantum",
    "turbo",
    "rogue",
    "alpha",
    "sigma",
    "cosmic",
    "velvet",
    "atomic",
    "shadow",
    "thunder",
    "neon",
    "savage",
    "iron",
    "crystal",
    "hyper",
    "blazing",
    "silent",
    "phantom",
    "lunar",
    "solar",
    "rapid",
    "supreme",
    "mystic",
    "omega",
    "titan",
    "frost",
    "crimson",
]

_NOUNS = [
    "hands",
    "wizard",
    "whale",
    "bull",
    "bear",
    "oracle",
    "prophet",
    "candle",
    "degen",
    "ape",
    "hawk",
    "fox",
    "shark",
    "wolf",
    "cobra",
    "falcon",
    "tiger",
    "yolo",
    "hodler",
    "sniper",
    "samurai",
    "viking",
    "ninja",
    "pirate",
    "knight",
    "phoenix",
    "dragon",
    "maverick",
    "rocket",
    "legend",
]

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")


def generate_funny_name() -> str:
    """Return a random trading-themed name like ``diamond-hands-42``."""
    adj = random.choice(_ADJECTIVES)
    noun = random.choice(_NOUNS)
    num = random.randint(10, 99)
    return f"{adj}-{noun}-{num}"


def validate_agent_name(name: str) -> bool:
    """Return True if *name* is a valid agent name (lowercase alphanumeric + hyphens, 3-30 chars)."""
    if not name or len(name) < 3 or len(name) > 30:
        return False
    return bool(_NAME_RE.match(name))
