# ByteAndBite

Essensvorschläge mit Rezepten, Nährwerten und digitalem Vorratsschrank – als Agentenanwendung.

> by HDL GmbH

## Monorepo-Struktur

```
byteandbite/
├── apps/
│   ├── backend/        # Python: Rezept-Pipeline, Agent-Tools, DB (FastAPI geplant)
│   └── mobile/         # React Native + Expo App (Frontend)
├── packages/
│   └── shared-types/   # Geteilte API-Typen (aus OpenAPI generiert) – FE ↔ BE
├── docs/
│   └── adr/            # Architecture Decision Records
└── docker-compose.yml  # Postgres (+ Backend) für lokale Entwicklung – geplant
```

**Konvention:** `apps/` = eigenständig deploybare Anwendungen, `packages/` = geteilter
Code. Jede App verwaltet ihre Dependencies selbst (`pyproject.toml` bzw. `package.json`).

## Quickstart

### Backend (`apps/backend`)
```bash
cd apps/backend
uv venv && uv sync          # virtuelle Umgebung + Dependencies
python main.py --help       # Rezept-Pipeline-CLI
```

### Mobile (`apps/mobile`)
```bash
cd apps/mobile
npx create-expo-app@latest . # einmalig: Expo-Projekt initialisieren
npx expo start
```
