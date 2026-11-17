# Feature organization

Findie keeps independently deployed applications at their existing roots. Inside each application, feature code lives together so a workflow can be located without searching several technical-layer folders. Shared infrastructure remains explicit.

## Feature map

| Workflow | Web source | API source |
| --- | --- | --- |
| Sign-in and profile | `apps/web/src/features/account/` | `apps/api/Features/Authentication/`, `apps/api/Features/Users/` |
| Administration | `apps/web/src/features/admin/` | `apps/api/Features/Admin/` |
| Item publishing and review | `apps/web/src/features/items/` | `apps/api/Features/Items/`, `apps/api/Features/Images/` |
| Search and saved searches | `apps/web/src/features/search/` | `apps/api/Features/Search/`, `apps/api/Features/SavedSearches/` |
| Claims, conversations and return | `apps/web/src/features/recovery/` | `apps/api/Features/Claims/`, `apps/api/Features/Conversations/`, `apps/api/Shared/RecoveryWorkflow.cs` |
| Hub intake and custody | `apps/web/src/features/hubs/` | `apps/api/Features/Intakes/`, `apps/api/Features/ReceptionPoints/` |
| Notifications | `apps/web/src/features/notifications/` | `apps/api/Features/Notifications/` |

## Web

Pages, feature-specific helpers, styles and unit tests are colocated in `src/features/<feature>/`. `App.tsx` composes routes; `main.tsx` loads the application. Generic UI components, hooks, HTTP/image/pagination helpers and global styles live in `src/shared/`. Static images and fonts remain in `src/assets/`; browser tests remain in `apps/web/e2e/`.

Use direct relative imports as in the existing code. Add a helper to its feature unless multiple features actually share it. No new barrel exports or path aliases are needed for this layout.

## API

Each `Features/<Feature>/` folder holds its controllers, services, request/response contracts, models and repositories where applicable. File moves preserve the existing .NET namespaces, public declarations, routes and dependency registrations. This avoids unnecessary caller and migration changes.

`Shared/` holds cross-feature recovery orchestration, common paging/error types, aggregate recovery persistence, and AI/outbox/idempotency models. `Infrastructure/` holds model, RabbitMQ and storage adapters, maintenance jobs, health checks and local seed helpers. `Security/` contains shared authorization and Identity integration. `Data/` retains the EF context, design-time factory and migration history.

Do not move migrations or change entity identities just to match a folder name. API smoke and integration harnesses remain under `apps/api/tests/`.

## AI worker

| Package or entrypoint | Contents |
| --- | --- |
| `findie_ai/search/` | Search projection/store, schema, candidate ranking, reranking, caches, public materials and quality checks |
| `findie_ai/privacy/` | Image decoding limits, normalization, redaction and metadata removal |
| `findie_ai/inference/` | Authenticated Ollama-compatible model gateway client |
| `findie_ai/worker.py` | RabbitMQ orchestration across the feature packages |
| `findie_ai/main.py` | FastAPI application and lifecycle |
| `findie_ai/migrate.py` | Search database migration entrypoint |
| `findie_ai/evaluate.py` | Offline evaluation entrypoint |
| `findie_ai/config.py`, `contracts.py` | Shared configuration and validated wire contracts |

`search/schema.sql` stays next to `search/store.py`, which loads it relative to its own file. Existing commands such as `uvicorn findie_ai.main:app` and `python -m findie_ai.migrate` remain valid. AI tests remain in `services/ai/tests/`; patch targets use the feature-package imports.

## Repository support folders

- `scripts/`: development setup, runner, doctor, model import, migrations and security hooks.
- `infra/aws/`: CloudFormation generation and release tooling.
- `notebooks/colab/`: GPU experiments and the full-stack inference gateway notebook.
- `tests/`: repository tooling, notebook, gateway and deployment checks.
- `docs/`: product, architecture, database, API, security, design and development references.

The public environment template is `.env.example`. Secret environment files are not source documentation and must never be committed or inspected by agents. Raw user uploads remain transient; reorganizing code does not change Findie's processed-output-only storage policy.
