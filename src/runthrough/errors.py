"""The faults the modules below the command layer raise.

A module reports what went wrong and stops there. Only `cli.main` decides that a
fault ends the process, which stream its message goes to, and the exit status.
"""

from __future__ import annotations


class RunthroughError(Exception):
    """A fault whose message is written for the person running the command."""


class ModelFailed(RunthroughError):
    """`claude` failed, or its reply held no tape or list to read."""


class ModelTimedOut(ModelFailed):
    """`claude` ran past its deadline. Asking again would wait as long a second time,
    so `request_tape` lets this through instead of retrying it."""


class GuardRefused(RunthroughError):
    """A command the model wrote is one the guard will not run."""


class StepTimedOut(RunthroughError):
    """A tape step was still running at its deadline, so the recording stopped."""
