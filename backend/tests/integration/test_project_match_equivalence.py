"""The indexed candidate matcher must make exactly the decisions the full-scan matcher made."""

import ast
import itertools
import random
from pathlib import Path
from types import SimpleNamespace

import pytest
from db_reset import reset_test_database
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from gridlens.ingestion import service
from gridlens.ingestion.service import (
    _all_project_ids,
    _full_scan_projects,
    _full_scan_structured_match,
    _retained_candidate_lock_ids,
    _retained_candidates,
    _retained_identity_decisions,
    _retained_identity_match,
    _structured_decision_project_ids,
    _structured_match,
    _StructuredMatchContext,
)
from gridlens.intelligence.project_identity import labeled_sites
from gridlens.persistence.models import Project, Source
from gridlens.settings import settings

NAMES = [
    "Alpha Data Center",
    "ALPHA data-center",
    "Alpha Data Center LLC",
    "alpha datacenter",
    "Beta Compressor Station",
    "Beta Compressor Station, Phase 2",
    "Gamma Well Pad",
    "Delta Campus",
    "",
]
SITES = [
    "100 Main Street, Austin, TX",
    "100 Main St, Austin, TX",
    "100 MAIN STREET Austin TX",
    "200 Oak Road, Houston, TX",
    "300 Pine Avenue, Dallas, OK",
    None,
]
LOCATIONS = ["Austin, TX", "Houston, TX", "100 Main Street, Austin, TX", "Tulsa, OK", None, ""]
ASSETS = ["unknown", "data_center", "upstream_well", "compressor_station"]
ASSET_IDENTITIES = [None, ["us_well_api", "42101123450000"], ["rrc:permit_project", "alpha one"]]
ALIASES = [[], ["Alpha One"], ["Beta Hub", "alpha data center"], ["Gamma"]]
SCOPES = [None, "phase 1 alpha", "phase 1 beta"]


@pytest.fixture
def session():
    target = make_url(settings.test_database_url)
    application = make_url(settings.database_url)
    assert target.database and (target.database == "test" or target.database.endswith("_test"))
    assert (target.host, target.port, target.database) != (
        application.host,
        application.port,
        application.database,
    ), "Refusing to reset application database"
    engine = create_engine(settings.test_database_url)
    reset_test_database(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        for source_id in ("s1", "s2"):
            db.add(
                Source(
                    id=source_id,
                    publisher=source_id,
                    endpoint="https://example.invalid/",
                    family="permits",
                    geography="US",
                    industries=[],
                    retrieval_method="socrata-permits",
                    cadence_hours=1,
                    enabled=True,
                    health={},
                )
            )
        db.commit()
        yield db
    engine.dispose()


def build_corpus(db) -> list[Project]:
    rng = random.Random(20261111)
    projects: list[Project] = []
    combos = list(itertools.product(range(len(NAMES)), range(len(SITES)), range(len(LOCATIONS))))
    rng.shuffle(combos)
    for index, (n, s, loc) in enumerate(combos[:150]):
        facts: dict = {"project_aliases": rng.choice(ALIASES)}
        if SITES[s] and index % 4 != 0:
            facts["site"] = SITES[s]
        asset_identity = rng.choice(ASSET_IDENTITIES)
        if asset_identity:
            facts["asset_identity"] = asset_identity
        scope = rng.choice(SCOPES)
        if scope:
            facts["facility_scope"] = scope
            facts["facility_source_address"] = rng.choice([s for s in SITES if s] or [""])
        if index % 11 == 0:
            facts["phase"] = "2"
        project = Project(
            identity_key=f"corpus-{index}",
            name=NAMES[n],
            location=LOCATIONS[loc] or (SITES[s] if index % 3 == 0 else LOCATIONS[loc]),
            source_id=rng.choice(["s1", "s2"]),
            external_id=f"ext-{index}",
            asset_type=rng.choice(ASSETS),
            identity_facts=facts,
        )
        db.add(project)
        projects.append(project)
    # Odd shapes the matcher tolerates: string aliases, empty site, missing facts.
    for index, facts in enumerate(
        [
            {"project_aliases": "Alpha"},
            {"site": ""},
            {},
            {"project_aliases": ["Alpha Data Center", 3]},
        ]
    ):
        project = Project(
            identity_key=f"odd-{index}",
            name="Alpha Data Center",
            location="100 Main Street, Austin, TX",
            source_id="s1",
            external_id=f"odd-{index}",
            identity_facts=facts,
        )
        db.add(project)
        projects.append(project)
    # Single-fact projects: each can be a candidate through exactly one key.
    for tag, name, location, facts in (
        (
            "loc-only",
            "Unrelated Loc",
            "100 Main Street, Austin, TX",
            {"site": "999 Elm Road, Austin, TX", "project_aliases": []},
        ),
        (
            "asset-only",
            "Unrelated Asset",
            "Elsewhere, TX",
            {"asset_identity": ["us_well_api", "42101999990000"], "project_aliases": []},
        ),
        (
            "site-only",
            "Unrelated Site",
            "Elsewhere, TX",
            {"site": "200 Oak Road, Houston, TX", "project_aliases": []},
        ),
        ("alias-only", "Unrelated Alias", None, {"project_aliases": ["Solo Alias"]}),
    ):
        project = Project(
            identity_key=f"single-{tag}",
            name=name,
            location=location,
            source_id="s1",
            external_id=tag,
            identity_facts=facts,
        )
        db.add(project)
        projects.append(project)
    db.commit()
    # Projects written by raw SQL (seeds, older app versions) carry no keys at all.
    db.execute(
        text("update projects set match_keys = NULL where identity_key ~ '[05]$' or name = ''")
    )
    for index in range(6):
        db.execute(
            text(
                "insert into projects(id, identity_key, name, location, source_id, external_id,"
                " identity_facts) values (gen_random_uuid(), :k, :n, :l, 's2', :k,"
                " CAST(:f AS jsonb))"
            ),
            {
                "k": f"raw-{index}",
                "n": NAMES[index],
                "l": "100 Main Street, Austin, TX",
                "f": '{"site": "100 Main Street, Austin, TX", "project_aliases": ["Alpha One"]}',
            },
        )
    db.commit()
    return list(db.scalars(select(Project)).all())


def structured_contexts() -> list[_StructuredMatchContext]:
    classification = SimpleNamespace(asset_type=SimpleNamespace(value="data_center"))
    contexts = []
    rng = random.Random(7)
    for name, location, alias, asset, scope in itertools.product(
        NAMES[:6] + ["Totally New Project"],
        LOCATIONS + SITES[:4],
        [None, "Alpha One", "Beta Hub"],
        ASSET_IDENTITIES,
        SCOPES,
    ):
        if rng.random() > 0.2:
            continue
        contexts.append(
            _StructuredMatchContext(
                project_name=name,
                permit_alias=alias,
                project_location=location,
                facility_scope=scope,
                source_id=rng.choice(["s1", "s2"]),
                facility_source_address=rng.choice(SITES) if scope else None,
                asset_identity=tuple(asset) if asset else None,  # type: ignore[arg-type]
                event_asset_type=rng.choice([None, classification]),
            )
        )
    # Contexts whose only link to the corpus is a single key: nothing ambiguous, so the
    # candidate set cannot be rescued by the full-scan fallback.
    for location in [*LOCATIONS, *SITES]:
        for asset, alias in (
            (None, None),
            (("us_well_api", "42101999990000"), None),
            (None, "Solo Alias"),
        ):
            contexts.append(
                _StructuredMatchContext(
                    project_name="Zed Unique",
                    permit_alias=alias,
                    project_location=location,
                    facility_scope=None,
                    source_id="s1",
                    facility_source_address=None,
                    asset_identity=asset,
                    event_asset_type=None,
                )
            )
    return contexts


def describe(decisions, ids):
    return {
        p.id: (d.decision, d.reason, tuple(d.matched_facts))
        for p, d in decisions
        if p.id in ids and (d.decision == "matched" or d.matched_facts or True)
    }


def test_structured_matcher_equals_full_scan(session):
    corpus = build_corpus(session)
    assert any(p.match_keys is None for p in session.scalars(select(Project)))
    assert any(p.match_keys for p in session.scalars(select(Project)))
    contexts = structured_contexts()
    assert len(contexts) > 150
    ambiguous = narrowed = matched_single = 0
    for ctx in contexts:
        old_rows, old_decisions, old_supported = _full_scan_structured_match(session, ctx)
        new_rows, new_decisions, new_supported = _structured_match(session, ctx)
        old_ids = _structured_decision_project_ids(old_rows, old_decisions, old_supported)
        new_ids = _structured_decision_project_ids(new_rows, new_decisions, new_supported)
        assert new_ids == old_ids, ctx
        assert {p.id for p, _ in new_supported} == {p.id for p, _ in old_supported}, ctx
        assert describe(new_decisions, new_ids) == describe(old_decisions, old_ids), ctx
        if len(old_supported) == 1:
            assert new_supported[0][0].id == old_supported[0][0].id
            matched_single += 1
        ambiguous += len(old_supported) > 1
        narrowed += len(new_rows) < len(corpus)
    # The corpus must exercise the single-match, ambiguous and narrowed paths.
    assert matched_single > 5 and ambiguous > 5 and narrowed > 50


RETAINED_TITLES = [
    ("Alpha Data Center plans campus", "Site address: 100 Main Street, Austin, TX."),
    ("alpha data-center update", "Project site is 200 Oak Road, Houston, TX and also"),
    ("Beta Compressor Station expansion", None),
    ("Alpha Data Center", "Address: 100 Main St, Austin, TX. Site: 200 Oak Road, Houston, TX."),
    ("Unrelated Warehouse", "Site address: 100 Main Street, Austin, TX."),
    ("Gamma Well Pad drilling data center", "No address given"),
]


def test_retained_news_matcher_equals_full_scan(session):
    build_corpus(session)
    everything = _full_scan_projects(session)
    keys = [p.identity_key for p in everything]
    checked = ambiguous = single = 0
    for (title, abstract), subject, location, admitted, target in itertools.product(
        RETAINED_TITLES,
        NAMES[:5] + ["Alpha One", "Solo Alias", "Unrelated Loc", "New Thing"],
        ["Austin, TX", "Houston, TX", "100 Main Street, Austin, TX", "Tulsa, OK"],
        [True, False],
        [None, keys[3], "no-such-key"],
    ):
        observation = SimpleNamespace(title=title, abstract=abstract)
        claim = {"decision": "accepted", "subject": subject, "location": location}
        old_ids = _retained_candidate_lock_ids(everything, observation, claim, admitted, target)
        narrowed = _retained_candidates(session, observation, claim, target)
        new_ids = _retained_candidate_lock_ids(
            narrowed, observation, claim, admitted, target, _all_project_ids(session)
        )
        assert new_ids == old_ids, (title, subject, location, admitted, target)
        site_claims = labeled_sites(f"{title} {abstract or ''}")
        site_claim = site_claims[0] if len(site_claims) == 1 else None
        old_decisions, old_matching = _retained_identity_decisions(
            everything, observation, claim, site_claim, len(site_claims) > 1
        )
        new_decisions, new_matching = _retained_identity_match(
            session, narrowed, observation, claim, site_claim, len(site_claims) > 1
        )
        assert {p.id for p, _ in new_matching} == {p.id for p, _ in old_matching}
        if len(old_matching) > 1:
            ambiguous += 1
            write_old = {p.id: d for p, d in old_decisions}
            write_new = {p.id: d for p, d in new_decisions}
            assert write_new == write_old
        else:
            single += len(old_matching)
            fact_rows = lambda decisions: {  # noqa: E731
                p.id: d for p, d in decisions if d.matched_facts
            }
            assert fact_rows(new_decisions) == fact_rows(old_decisions)
        # The news-supplement loop only needs the narrowed set to contain every match.
        assert {p.id for p, _ in old_matching} <= {p.id for p in narrowed}
        checked += 1
    assert checked > 1000 and ambiguous > 10 and single > 10


def test_null_key_rows_are_always_candidates(session):
    build_corpus(session)
    observation = SimpleNamespace(title="Zzz", abstract=None)
    claim = {"decision": "accepted", "subject": "Nothing Like Anything", "location": "Nowhere"}
    narrowed = _retained_candidates(session, observation, claim, None)
    unset = {p.id for p in session.scalars(select(Project).where(Project.match_keys.is_(None)))}
    assert unset and {p.id for p in narrowed} == unset


def test_match_keys_follow_orm_writes(session):
    project = Project(
        identity_key="k1",
        name="Alpha Data Center",
        location="100 Main Street, Austin, TX",
        source_id="s1",
        external_id="e1",
        identity_facts={"project_aliases": ["Alpha One"]},
    )
    session.add(project)
    session.commit()
    assert "n:alpha one" in project.match_keys
    assert "s:100 main street austin tx" in project.match_keys
    project.identity_facts = {"project_aliases": ["Alpha Two"], "site": "9 Elm Road, Austin, TX"}
    session.commit()
    session.refresh(project)
    assert "n:alpha two" in project.match_keys and "n:alpha one" not in project.match_keys
    assert "s:9 elm road austin tx" in project.match_keys


def test_no_unfiltered_project_scan_on_ingestion_paths():
    """Bare ``select(Project)`` (no where/filter) may only appear in the test-oracle helper."""
    source = Path(service.__file__).read_text()
    tree = ast.parse(source)
    allowed = {"_full_scan_projects"}
    offenders = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.function: list[str] = []

        def visit_FunctionDef(self, node):  # noqa: N802
            self.function.append(node.name)
            self.generic_visit(node)
            self.function.pop()

        def visit_Call(self, node):  # noqa: N802
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "select"
                and [getattr(a, "id", None) for a in node.args] == ["Project"]
            ):
                offenders.append((self.function[-1] if self.function else "<module>", node))
            self.generic_visit(node)

    Visitor().visit(tree)
    # A select(Project) is "bare" when its chain never applies .where() before executing.
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    bare = []
    for function, node in offenders:
        current = node
        filtered = False
        while current in parents:
            parent = parents[current]
            if isinstance(parent, ast.Attribute) and parent.attr in {
                "where",
                "filter",
                "filter_by",
            }:
                filtered = True
                break
            if not isinstance(parent, ast.Attribute | ast.Call):
                break
            current = parent
        if not filtered and function not in allowed:
            bare.append((function, node.lineno))
    assert not bare, f"unfiltered select(Project) outside the test oracle: {bare}"
