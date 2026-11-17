# Findie documentation

Start with the [project README](../README.md) for the architecture and complete local setup. Use the [feature organization guide](guides/feature-organization.md) to locate application code.

## Architecture and data

- [System overview image](architecture/system-overview.png) and [editable draw.io source](architecture/system-overview.drawio).
- [AWS deployment image](architecture/aws-deployment.png) and [editable draw.io source](architecture/aws-deployment.drawio).
- [Detailed system architecture](architecture/system-architecture.md).
- [Database design](database/database-design.md).
- [AWS deployment runbook](../infra/aws/README.md).
- Historical bootstrap artifacts: [column dictionary](database/database-column-dictionary.md), [DDL](database/database-schema.sql), [SQL checks](database/database-check.sql), [ERD source](database/findie-erd.drawio), and [ERD image](assets/findie-erd-overview.png). These snapshots predate the current search schema and processed-output-only policy; use EF migrations and the AI search schema for runtime changes.

## Development and API

- [Feature organization](guides/feature-organization.md).
- [Development guide](guides/development.md).
- [.NET API](api/README.md), [API tests](api/testing.md), [recovery](api/recovery.md), [media/search](api/media-search.md), and [saved searches](api/saved-searches.md).
- [AMQP contracts](api/amqp.md).
- [AI service](guides/ai-service.md), [Colab](guides/colab.md), and [search evaluation](guides/search-evaluation.md).
- [AWS database operations](guides/aws-database.md).
- [Testing report](TESTING_REPORT.md), [Playwright guide](guides/e2e-testing-guide.md), and [test improvement plan](guides/test-improvement-plan.md).
- [Security report](security/SECURITY_REPORT.md) and [security plan](security/SECURITY_PLAN.md).

## Product and design

- Product specification: [Markdown](product/DAC_TA_FINDIE.md), [Word](product/DAC_TA_FINDIE.docx), and [PDF](product/DAC_TA_FINDIE.pdf).
- [Project overview](BAO_CAO_TONG_QUAN_DU_AN.md) and [UI/UX improvement plan](KE_HOACH_TOI_UU_UI_UX.md).
- [Stitch design references](design/stitch/README.md).
- [Feature specifications and plans](specs/001-project-bootstrap/spec.md).
- [Project constitution](../.specify/memory/constitution.md).
- [Demo summary](demo/findie-dang-bai/TOM_TAT_FINDIE.txt) and [demo video](demo/findie-dang-bai/findie-demo.mp4).

The project README, this index and the feature guide are in English. Historical specifications and detailed reference documents may be in Vietnamese.

## Diagram sources

The English system overview and AWS deployment diagrams were extracted from the supplied draw.io PNGs. Open their `.drawio` files in diagrams.net to edit and export them. The existing ERD source remains at `database/findie-erd.drawio`; the older architecture SVG remains at `assets/kien-truc-he-thong.svg`.

The existing local ERD and legacy SVG render scripts use the Codex runtime's Playwright installation and local Google Chrome:

```sh
python3 scripts/docs/erd/build_erd.py
node scripts/docs/erd/render_local.cjs
node scripts/docs/render_architecture.cjs
```

These commands regenerate the historical assets rather than the new supplied-diagram exports.
