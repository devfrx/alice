/**
 * Minimal JSON-Schema-subset validator for agent-supplied command args
 * (Fase 7). Agent args arrive over the wire as UNTRUSTED JSON: the registry's
 * `execute` does not validate, so the bridge MUST (fase 6 backlog).
 *
 * Deliberately dependency-free: registry schemas only use this subset —
 * object root, `properties` with primitive `type` and optional `enum`,
 * `required`. Unknown args are rejected (mirrors the backend's
 * `extra="forbid"` stance).
 */

type PropertySchema = Record<string, unknown>

/**
 * @returns `null` when `args` conforms to `schema`, else a human-readable
 *   error message (returned to the agent as the command failure).
 */
export function validateCommandArgs(
  schema: Record<string, unknown> | undefined,
  args: Record<string, unknown>
): string | null {
  if (!schema || schema.type !== 'object') return null
  const properties = (schema.properties ?? {}) as Record<string, PropertySchema>
  const required = Array.isArray(schema.required) ? (schema.required as string[]) : []
  // Own-property semantics everywhere: `key in args` / plain lookups would
  // traverse the prototype chain, letting arg names like `constructor` or
  // `toString` satisfy required keys or dodge the unknown-arg rejection.
  for (const key of required) {
    if (!Object.hasOwn(args, key)) return `Missing required arg: ${key}`
  }
  for (const [key, value] of Object.entries(args)) {
    const prop = Object.hasOwn(properties, key) ? properties[key] : undefined
    if (!prop) return `Unknown arg: ${key}`
    const error = validateValue(key, value, prop)
    if (error) return error
  }
  return null
}

function validateValue(key: string, value: unknown, prop: PropertySchema): string | null {
  switch (prop.type) {
    case 'string':
      if (typeof value !== 'string') return `Arg '${key}' must be a string`
      break
    case 'number':
      if (typeof value !== 'number') return `Arg '${key}' must be a number`
      break
    case 'integer':
      if (typeof value !== 'number' || !Number.isInteger(value))
        return `Arg '${key}' must be an integer`
      break
    case 'boolean':
      if (typeof value !== 'boolean') return `Arg '${key}' must be a boolean`
      break
    case 'object':
      if (typeof value !== 'object' || value === null || Array.isArray(value))
        return `Arg '${key}' must be an object`
      break
    case 'array':
      if (!Array.isArray(value)) return `Arg '${key}' must be an array`
      break
  }
  const allowed = prop.enum
  if (Array.isArray(allowed) && !allowed.includes(value)) {
    return `Arg '${key}' must be one of: ${allowed.join(', ')}`
  }
  return null
}
