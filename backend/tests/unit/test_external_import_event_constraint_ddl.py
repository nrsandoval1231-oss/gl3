from sqlalchemy import CheckConstraint, Column, MetaData, String, Table, Text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from gridlens.persistence.models import ExternalImportEvent


def test_metadata_reparse_event_check_is_postgresql_only_ddl():
    model_constraint = next(
        constraint
        for constraint in ExternalImportEvent.__table__.constraints
        if constraint.name == "ck_external_import_event_action"
    )
    probe = Table(
        "external_import_event_ddl_probe",
        MetaData(),
        Column("action", String(20)),
        Column("details", Text),
        CheckConstraint(
            model_constraint.sqltext,
            name=model_constraint.name,
        ).ddl_if(dialect="postgresql"),
    )

    sqlite_ddl = str(CreateTable(probe).compile(dialect=sqlite.dialect()))
    postgres_ddl = str(CreateTable(probe).compile(dialect=postgresql.dialect()))

    assert "ck_external_import_event_action" not in sqlite_ddl
    assert "jsonb_typeof" not in sqlite_ddl
    assert "ck_external_import_event_action" in postgres_ddl
    assert "jsonb_typeof" in postgres_ddl
