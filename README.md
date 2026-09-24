# gl3

Fresh GridLens implementation. The [PRD](docs/product/PRD.md) defines the product, qualification tiers, daily ingestion, acceptance gates, and planned folder layout.

**Status:** Repository structure created. Ingestion, application code, cloud scheduling, and source adapters have not been implemented.

Build in order: foundation → daily Signals → Prospects → Leads → daily working release. Keep national discovery and data center construction/commissioning priority in view throughout. The folders below explain ownership; create runnable files as each milestone needs them.

**Current implementation priority:** Follow the [ingestion strategy](docs/sources/ingestion-strategy.md): validate source coverage and prove collection, evidence persistence, replay, and source health before adding n8n research workflows.
