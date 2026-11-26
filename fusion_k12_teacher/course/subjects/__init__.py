"""Subject implementation package — each subject's SubjectModule registers here.

Adding a subject:
1. Create a subjects/{subject_id}/ package implementing SubjectModule
   (inherits course.base.SubjectModule).
2. Add one line to the _BUILTIN registry below.
3. Zero changes to the platform (engines/serve/gui).

Currently registered: math. Planned: physics / chemistry / english / chinese.
"""

from __future__ import annotations

from ..base import SubjectModule


def get_builtin_subjects() -> list[type[SubjectModule]]:
    """Return the list of built-in subject module classes. Imports stay inside the
    function to avoid a hard platform-layer dependency on specific subjects."""
    subjects: list[type[SubjectModule]] = []
    try:
        from .math import MathSubject
        subjects.append(MathSubject)
    except ImportError as exc:
        import logging
        logging.getLogger(__name__).warning("subjects: math subject import failed: %s", exc)
    return subjects
