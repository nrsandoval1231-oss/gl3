# Source definitions

Group validated feeds into national, construction, corporate, utility, and discovery families. Each entry needs a stable ID, publisher, geography, cadence, retrieval method, parser, access notes, and readiness evidence. Create family YAML files only after a working feed exists.

`registry.v1.json` does not store a separate `parser` key. `id` is the stable source id. `ingestion/adapters/__init__.py` chooses the adapter from `retrieval_method`.
