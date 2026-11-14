"""Guards for the account-list read path that took ~2 minutes at 40k projects.

Measured on a synthetic 40,000-project corpus (see
docs/engineering/account-list-read-performance-20261112.md): the contact-candidate query
re-scanned the whole ``assigned`` CTE for every candidate row, and PostgreSQL JIT added
about 2.5 s to each large CTE read.
"""

import inspect

from test_saved_browse import saved_db  # noqa: F401

from gridlens.api.app import _begin_consistent_read
from gridlens.intelligence import customer_results


def test_consistent_reads_disable_jit_for_the_transaction_only(saved_db):  # noqa: F811
    with saved_db() as session:
        _begin_consistent_read(session)
        assert session.connection().exec_driver_sql("SHOW jit").scalar() == "off"
        session.rollback()
        assert session.connection().exec_driver_sql("SHOW jit").scalar() != "off"


def test_account_contact_query_keeps_its_scale_safe_shape():
    """Pin the query shape: the 40k-project regression came from its absence.

    The page's few resolved groups are selected first (a materialized CTE the planner
    cannot nested-loop over the whole corpus), and the per-asset project list is
    aggregated once instead of by a correlated subquery per candidate row.
    """
    source = inspect.getsource(customer_results._account_contact_projects)
    assert "include_commercial_projects=False" in source
    assert "contact_assigned AS MATERIALIZED" in source
    assert "FROM contact_assigned a" in source
    assert "ARRAY(SELECT ar2.project_id" not in source
