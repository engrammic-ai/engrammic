"""Worker entrypoint for the Taskiq reaction worker process.

Exposes the broker instance that the ``taskiq worker`` CLI references as a
module-level object. All silos share the same queue; silo isolation is enforced
at the task level via the ``silo_id`` kwarg passed to each handler.

Usage::

    taskiq worker context_service.reactions.worker_entrypoint:broker --workers 4

The ``configure_worker`` call applies logging and tracing middleware, registers
the WORKER_STARTUP / WORKER_SHUTDOWN hooks, and marks the broker as a worker
process so middleware activates correctly.
"""

from __future__ import annotations

from context_service.reactions.broker import get_broker
from context_service.reactions.worker import configure_worker

broker = get_broker()
configure_worker(broker)
