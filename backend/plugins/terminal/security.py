"""AL\\CE — Terminal plugin security primitives (Fase 6d).

Pure input-validation primitives that gate whether an arbitrary command may run
inside a user-confined folder.  They are deliberately **side-effect free** apart
from filesystem *reads* (and the single lazy ``mkdir`` in :func:`ensure_sandbox`):
no subprocess, no config imports, no network.  That isolation is what lets them
be unit-tested adversarially and reviewed in one sitting — the whole security
story for the terminal lives here.

Design notes (every input is treated as hostile):

* The path checks **replicate** — rather than import — the proven validator
  :meth:`backend.services.scope_service.ScopeService.validate_folder`
  (UNC/device rejection, resolve-first, exists/dir).  The codebase intentionally
  duplicates these primitives so security-critical modules never couple to one
  another's internals.  The check ``validate_folder`` *lacks* — positive
  containment inside the conversation scope — is added here and is the load-
  bearing anti-escape step.
* ``Path.resolve()`` is always called **before** any containment/forbidden
  comparison.  It collapses ``..`` segments and follows symlinks, so a traversal
  or a symlink that points outside the scope both surface as a *resolved* path
  that no scope root contains — and is rejected by the same comparison.
* :func:`build_argv` parses for ``shell=False`` execution only.  With no shell
  in the loop, metacharacters (``;`` ``|`` ``&`` ``>`` ``<`` quotes) are literal
  argv tokens, never operators — that absence *is* the injection defense.  This
  module never attempts to re-implement a shell.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

__all__ = ["build_argv", "ensure_sandbox", "validate_cwd_within_scope"]


def _is_relative_to(target: Path, root: Path) -> bool:
    """Return ``True`` iff *target* is at or under *root* (never raises).

    An explicit helper (rather than :meth:`pathlib.PurePath.is_relative_to`) so
    the containment semantics stay auditable and uniform across call sites: it
    answers a pure "is *target* equal to, or nested inside, *root*?" question and
    swallows the :class:`ValueError` that :meth:`Path.relative_to` raises when it
    is not.

    Args:
        target: The already-resolved candidate path.
        root: The already-resolved root to test containment against.

    Returns:
        ``True`` when *target* is *root* itself or a descendant of it.
    """
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def validate_cwd_within_scope(
    requested_cwd: str,
    scope_roots: Sequence[Path],
    forbidden_paths: Sequence[str] = (),
) -> Path:
    """Validate an *explicit* working directory is safe and inside the scope.

    Performs, strictly in order (any failure raises — nothing partial is
    returned):

    1. reject empty / blank input;
    2. reject UNC and device paths (a leading ``\\`` or ``//``) — mirrors
       :meth:`ScopeService.validate_folder`; a single leading backslash can
       degrade into a UNC path on normalisation, so it is refused too;
    3. ``resolve()`` the path (collapsing ``..`` and following symlinks) — the
       load-bearing anti-escape step, run *before* any comparison;
    4. require the resolved path to exist and be a directory;
    5. reject anything at or under a *forbidden* root (each resolved best-effort);
    6. **containment** — require the resolved path to be at or under at least one
       of *scope_roots*; an empty *scope_roots*, or a path under none of them,
       is outside the workspace and rejected.  This is what defeats both a
       ``..`` climb and a symlink that escapes the scope: each surfaces as a
       resolved path that no root contains;
    7. return the resolved path.

    Forbidden paths are checked **before** containment, so a forbidden subtree
    is refused even when it is technically inside the scope.

    Args:
        requested_cwd: The candidate working-directory path (caller-supplied,
            therefore untrusted).
        scope_roots: The conversation's allowed roots, **already resolved** by
            :class:`~backend.services.scope_service.ScopeService`.
        forbidden_paths: Optional roots that are always out of bounds (e.g.
            configured/system roots); resolved best-effort here.

    Returns:
        The resolved, validated, in-scope directory :class:`~pathlib.Path`.

    Raises:
        ValueError: If *requested_cwd* fails any check above.
    """
    # 1. Empty / blank.
    if not requested_cwd or not requested_cwd.strip():
        raise ValueError("Empty working directory path")

    raw = requested_cwd.strip()

    # 2. UNC (``\\server\share``) / device (``\\.\dev``) / forward-slash UNC.
    if raw.startswith("\\") or raw.startswith("//"):
        raise ValueError(f"UNC and device paths are not allowed: {requested_cwd}")

    # 3. Resolve symlinks / ``..`` BEFORE any comparison.  ``strict=False`` —
    #    existence is asserted explicitly in step 4.
    try:
        resolved = Path(raw).resolve()
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid working directory path: {exc}") from exc

    # 4. Must exist and be a directory.
    if not resolved.exists():
        raise ValueError(f"Working directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Not a directory: {resolved}")

    # 5. Forbidden roots take precedence over scope membership.
    for entry in forbidden_paths:
        try:
            forbidden_root = Path(entry).resolve()
        except (OSError, ValueError):
            # A malformed forbidden entry must never weaken the check; skip it.
            continue
        if _is_relative_to(resolved, forbidden_root):
            raise ValueError(
                f"Working directory '{resolved}' is inside a forbidden root: {forbidden_root}"
            )

    # 6. Positive containment: at/under at least one resolved scope root.  An
    #    empty *scope_roots* means nothing is in-scope, so this is False and the
    #    path is rejected — exactly the desired no-scope behaviour for an
    #    *explicit* cwd (the sandbox fallback is a separate primitive).
    if not any(_is_relative_to(resolved, root) for root in scope_roots):
        raise ValueError(
            f"Working directory '{resolved}' is outside the workspace scope"
        )

    # 7. Confined and safe.
    return resolved


def ensure_sandbox(conversation_id: str, sandbox_root: str | Path) -> Path:
    """Compute and lazily create the per-conversation sandbox directory.

    The sandbox is the no-scope fallback working dir: one folder per
    conversation under *sandbox_root*.  Steps:

    1. reject an empty / blank id, and reject any id that is not a single safe
       path component — path separators (either platform's), ``..`` traversal, a
       drive / alternate-data-stream colon, or a control character all disqualify
       it.  Real ids are UUIDs, so this never rejects a legitimate id while it
       forecloses id-driven traversal;
    2. join the id onto the resolved *sandbox_root* and ``resolve()`` the result;
    3. **re-assert containment** — the joined+resolved target must stay at or
       under the resolved root (belt-and-suspenders against any step-1 bypass);
    4. create the directory (``parents=True, exist_ok=True``) — the lazy part;
    5. return the target.

    Args:
        conversation_id: The conversation identifier (expected: a UUID).  Treated
            as untrusted and validated as a single path component.
        sandbox_root: The root under which per-conversation sandboxes live.

    Returns:
        The resolved, created sandbox directory :class:`~pathlib.Path`.

    Raises:
        ValueError: If *conversation_id* is empty or not a single safe path
            component, if the computed target escapes *sandbox_root*, or if the
            sandbox directory cannot be created.
    """
    # 1. Empty / blank.
    if not conversation_id or not conversation_id.strip():
        raise ValueError("Empty conversation id")

    cid = conversation_id.strip()

    # A conversation id must be a SINGLE safe path component.  Anything that
    # could redirect the join in step 2 outside the sandbox root is refused:
    # path separators of either platform, parent-dir traversal, a drive / ADS
    # colon, or a control character (never present in the real UUID ids — their
    # presence is itself a strong signal of tampering).
    if (
        "/" in cid
        or "\\" in cid
        or ":" in cid
        or ".." in cid
        or cid in (".", "..")
        or any(ord(ch) < 32 for ch in cid)
    ):
        raise ValueError(
            f"Unsafe conversation id (must be a single path component): {conversation_id!r}"
        )

    # 2. Join onto the resolved root and resolve the result.
    base = Path(sandbox_root).resolve()
    target = (base / cid).resolve()

    # 3. Re-assert containment even after step 1 (defence in depth).
    if not _is_relative_to(target, base):
        raise ValueError(
            f"Sandbox path '{target}' escaped the sandbox root '{base}'"
        )

    # 4. Lazy creation (idempotent).  Any OS-level failure (e.g. an absurdly
    #    long id past the path limit, or a permission error) is surfaced as the
    #    documented ValueError so callers only ever catch one exception type.
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            f"Could not create sandbox directory '{target}': {exc}"
        ) from exc
    logger.debug("Terminal sandbox ready for conversation {}: {}", cid, target)

    # 5. Confined and present.
    return target


def build_argv(command: str) -> list[str]:
    """Parse *command* into an argv list for ``shell=False`` execution.

    Because the caller runs the result with ``shell=False``, shell metacharacters
    (``;`` ``|`` ``&`` ``>`` ``<``, quotes, …) are passed through as **literal**
    argv tokens — they are never interpreted as operators.  That is the whole
    injection defense; this function deliberately does *not* emulate a shell.

    Steps:

    1. reject an empty / blank command;
    2. reject control characters — newline (``\\n``), carriage return (``\\r``)
       or NUL (``\\x00``) — which are never legitimate in a command line and
       (in a shell context) can act as separators; mirrors ``pc_automation``'s
       newline/CR rejection, with NUL added;
    3. tokenise with :func:`shlex.split` using ``posix=False`` — Windows-
       appropriate splitting that keeps backslashes in paths intact; unbalanced
       quotes raise and are re-raised as a clear :class:`ValueError`;
    4. reject an empty argv (e.g. a command that was only quotes);
    5. return the argv list.

    Note on ``posix=False`` tokenisation: quote characters are **retained** in
    the emitted tokens, so ``build_argv('git commit -m "a message"')`` yields
    ``['git', 'commit', '-m', '"a message"']`` (the message stays a single token
    with its surrounding double-quotes).  This is the intended, documented
    behaviour for Windows command lines.

    Args:
        command: The raw command string (untrusted).

    Returns:
        The argv list, suitable for ``subprocess`` with ``shell=False``.

    Raises:
        ValueError: If *command* is empty, contains a control character, cannot
            be tokenised, or yields no arguments.
    """
    # 1. Empty / blank.
    if not command or not command.strip():
        raise ValueError("Empty command")

    # 2. Control characters are never legitimate on a command line.
    if "\n" in command or "\r" in command or "\x00" in command:
        raise ValueError("Control characters are not allowed in commands")

    # 3. Windows-appropriate tokenisation (keeps backslashes literal; no shell
    #    escape processing).  Unbalanced quotes surface as ValueError.
    try:
        argv = shlex.split(command, posix=False)
    except ValueError as exc:
        raise ValueError(f"Could not parse command (unbalanced quotes?): {exc}") from exc

    # 4. Nothing to run.
    if not argv:
        raise ValueError("Command produced no arguments after parsing")

    # 5. Literal-token argv for shell=False.
    return argv
