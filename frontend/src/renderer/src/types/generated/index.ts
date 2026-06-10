/**
 * Hand-written aliases over the GENERATED OpenAPI types (./api).
 *
 * `./openapi.json` and `./api.d.ts` are build artifacts: regenerate them with
 * `scripts/gen-contracts.ps1` — NEVER edit them by hand. This index is the only
 * hand-written file in this directory.
 */
import type { components } from './api'

/** Resolve a backend Pydantic model by its OpenAPI component name. */
export type ApiSchema<K extends keyof components['schemas']> = components['schemas'][K]
