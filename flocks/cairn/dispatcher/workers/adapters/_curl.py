from __future__ import annotations

import shlex


def curl_healthcheck(url: str, timeout: int = 10) -> list[str]:
    return [
        "curl",
        "--max-time", str(timeout),
        "--connect-timeout", str(timeout),
        "-fsSL",
        url,
    ]


def curl_healthcheck_human(url: str, timeout: int = 10) -> str:
    return shlex.join(curl_healthcheck(url, timeout))