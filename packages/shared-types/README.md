# shared-types

Geteilte API-Typen zwischen Backend und Mobile-App.

**Quelle der Wahrheit:** die Pydantic-Modelle im Backend (`apps/backend/models/`).
FastAPI generiert daraus ein OpenAPI-Schema, aus dem hier TypeScript-Typen
erzeugt werden (z.B. via `openapi-typescript`). Inhalt dieses Pakets ist also
generierter Code – nicht von Hand pflegen.

Noch leer: wird befüllt, sobald das Backend eine FastAPI-Schnittstelle bereitstellt.
