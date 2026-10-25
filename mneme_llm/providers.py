"""What every tier needs to reach a model or a service: calling the host's function (sync or async), posting JSON
to an API, reading JSON out of a model's reply, and resting a provider that just failed.

One policy for failures, used by every tier that calls out: a provider that fails, for whatever reason, is skipped
for `Rest.seconds` (60) instead of being waited on at every call, so a recall never pays for the same failure twice
in a minute. The last decision tier (the host's model) is never rested: there is nothing after it to fall through
to.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Union

Complete = Callable[[str, str], Union[str, Awaitable[str]]]  # complete(system, user) -> the reply's text


class Unavailable(RuntimeError):
    """A tier cannot answer right now (no key, no network, not configured)."""


async def call(function: Callable, *args) -> Any:
    """`function(*args)`, awaited if it is async; a blocking function runs in a worker thread, so the event loop
    goes on meanwhile."""
    if inspect.iscoroutinefunction(function):
        return await function(*args)
    result = await asyncio.to_thread(function, *args)
    return await result if inspect.isawaitable(result) else result


async def ask(complete: Complete | None, system: str, user: str) -> str:
    """The host's chat model's reply, as text."""
    if complete is None:
        raise Unavailable("no chat model (`complete`) was given")
    return str(await call(complete, system, user) or "")


def post_json(url: str, api_key: str, body: dict, *, timeout: float, what: str) -> dict:
    """POST `body` as JSON with a bearer key; any failure becomes `Unavailable` saying what failed."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise Unavailable(f"{what} answered {error.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise Unavailable(f"{what} unreachable: {error}") from None


def json_in(reply: str, opener: str = "[") -> Any:
    """The first JSON list (`opener="["`) or object (`"{"`) in a model's reply, or None when there is none that
    parses (prose around it is ignored; a document nested too deep counts as none)."""
    pattern = r"\[.*\]" if opener == "[" else r"\{.*\}"
    found = re.search(pattern, reply or "", re.S)
    if not found:
        return None
    try:
        return json.loads(found.group(0))
    except (ValueError, RecursionError):
        return None


class Rest:
    """Skips a provider for `seconds` after a failure (see the module's policy), and remembers the last one."""

    def __init__(self, seconds: float = 60.0):
        self.seconds, self.until, self.error = seconds, 0.0, ""

    def up(self) -> bool:
        return time.monotonic() >= self.until

    def failed(self, error: BaseException) -> None:
        self.error = f"{type(error).__name__}: {error}"[:200]
        self.until = time.monotonic() + self.seconds


def run(awaitable):
    """Run a coroutine from synchronous code (inside an event loop, await the `a…` method instead)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    awaitable.close()
    raise RuntimeError("called the synchronous form inside a running event loop; await the async form instead")
