export type { CommandCapability, CommandDefinition } from './types'
export { CommandRegistry, commandRegistry, CommandNotFoundError, DuplicateCommandError } from './registry'
export { installCoreCommands, SWITCHABLE_VIEWS } from './core'
export type { SwitchableView, ViewSwitchArgs, ConversationOpenArgs, ArtifactShowArgs } from './core'
