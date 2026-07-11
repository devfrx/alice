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

/** Discriminated unions of the two WS channels (generated from ws_schema). */
export type ChatServerMessage = ApiSchema<'ChatServerMessage'>
export type ChatClientMessage = ApiSchema<'ChatClientMessage'>
export type EventsServerMessage = ApiSchema<'EventsServerMessage'>
export type EventsClientMessage = ApiSchema<'EventsClientMessage'>

/** Command Layer RPC frames (Fase 7, spec §7). */
export type WsCommandRequest = ApiSchema<'WsCommandRequest'>
export type CommandManifestEntry = ApiSchema<'CommandManifestEntry'>
