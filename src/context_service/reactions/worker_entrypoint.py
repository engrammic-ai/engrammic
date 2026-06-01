"""Worker entrypoint for the Taskiq reaction worker process.

Exposes a default broker instance that the ``taskiq worker`` CLI can reference
as a module-level object. Silo-specific routing is handled at task dispatch time
via the ``silo_id`` kwarg passed to each task; the worker itself does not need
to be silo-aware at startup.

Usage::

    taskiq worker context_service.reactions.worker_entrypoint:broker --workers 4

The ``configure_worker`` call applies logging and tracing middleware, registers
the WORKER_STARTUP / WORKER_SHUTDOWN hooks, and marks the broker as a worker
process so middleware activates correctly.
"""

from __future__ import annotations

from context_service.reactions.broker import get_broker
from context_service.reactions.worker import configure_worker

# Default broker for the worker process.  Actual silo routing happens via
# task kwargs at dispatch time, not at the broker level.
broker = get_broker("default")
configure_worker(broker)
