import { describe, expect, it } from 'vitest'
import { validateCommandArgs } from './validate'

const schema = {
  type: 'object',
  properties: {
    view: { type: 'string', enum: ['board', 'assistant'] },
    count: { type: 'integer' },
    flag: { type: 'boolean' }
  },
  required: ['view']
}

describe('validateCommandArgs', () => {
  it('accepts conforming args', () => {
    expect(validateCommandArgs(schema, { view: 'board', count: 2, flag: true })).toBeNull()
  })

  it('rejects a missing required arg', () => {
    expect(validateCommandArgs(schema, {})).toMatch(/Missing required arg: view/)
  })

  it('rejects an unknown arg', () => {
    expect(validateCommandArgs(schema, { view: 'board', nope: 1 })).toMatch(/Unknown arg: nope/)
  })

  it('rejects a wrong primitive type', () => {
    expect(validateCommandArgs(schema, { view: 42 })).toMatch(/must be a string/)
    expect(validateCommandArgs(schema, { view: 'board', count: 1.5 })).toMatch(/must be an integer/)
    expect(validateCommandArgs(schema, { view: 'board', flag: 'yes' })).toMatch(/must be a boolean/)
  })

  it('rejects a value outside the enum', () => {
    expect(validateCommandArgs(schema, { view: 'nope' })).toMatch(/must be one of/)
  })

  it('is permissive without a usable schema', () => {
    expect(validateCommandArgs(undefined, { anything: 1 })).toBeNull()
    expect(validateCommandArgs({ type: 'string' }, { anything: 1 })).toBeNull()
  })
})
