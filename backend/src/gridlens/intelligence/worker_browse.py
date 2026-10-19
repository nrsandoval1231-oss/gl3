"""Keep bounded worker writes and their canonical browse publication atomic."""

import logging
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import event, select, text

from gridlens.persistence.models import BrowseGeneration, BrowseState
from gridlens.settings import settings

logger = logging.getLogger(__name__)


def _before_commit(session):
    if (
        not settings.saved_browse_enabled
        or session.in_nested_transaction()
        or session.info.get("worker_browse_refresh")
    ):
        return
    # Ingestion deliberately commits evidence before interpretation/checkpoints.
    # Flush before the savepoint: failure of derived work must retain those writes
    # and their transactional invalidation, including already-flushed/bulk DML.
    session.flush()
    # Only this transaction's actual canonical DML may request publication.
    # The trigger flag rolls back with savepoints and clears at transaction end;
    # unrelated lease/heartbeat commits must never repair an existing backlog.
    if session.scalar(text("SELECT current_setting('gridlens.browse_dirty', true)")) != "1":
        return
    from gridlens.intelligence.saved_browse import POLICY_VERSION, refresh_project_changes

    now = datetime.now(UTC)
    eligible = session.scalar(
        select(BrowseState.id)
        .join(BrowseGeneration, BrowseGeneration.id == BrowseState.generation_id)
        .where(
            BrowseState.id == 1,
            BrowseState.input_revision != BrowseGeneration.input_revision,
            BrowseState.full_revision <= BrowseGeneration.input_revision,
            BrowseGeneration.policy_version == POLICY_VERSION,
            BrowseGeneration.valid_from <= now,
            BrowseGeneration.valid_until > now,
        )
    )
    # Queue/heartbeat commits need neither the publication lock nor reconstruction.
    if eligible is None:
        return
    session.info["worker_browse_refresh"] = True
    try:
        # The shared refresh expires canonical objects after acquiring its fence;
        # API callers and reused worker sessions get the same current-input rule.
        with session.begin_nested():
            deadline = min(
                monotonic() + 60,
                session.info.get("browse_publication_deadline", float("inf")),
            )
            refresh_project_changes(
                session, max_projects=1000, max_needs=1000, execution_deadline=deadline
            )
    except Exception:
        logger.warning(
            "Saved browse refresh failed; canonical change retained, qualification pending"
        )
    finally:
        session.info.pop("worker_browse_refresh", None)


def install_worker_publication(factory):
    """Register only in the worker process; builders retain their own fencing."""
    if not event.contains(factory, "before_commit", _before_commit):
        event.listen(factory, "before_commit", _before_commit)
