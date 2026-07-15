export type { CommandCapability, CommandDefinition } from './types'
export {
  CommandRegistry,
  commandRegistry,
  CommandNotFoundError,
  DuplicateCommandError
} from './registry'
export { installCoreCommands, SWITCHABLE_VIEWS } from './core'
export type { SwitchableView, ViewSwitchArgs, ConversationOpenArgs, ArtifactShowArgs } from './core'
export { installDeskCommands, DESK_COMMAND_NAMES } from './desk'
export type { WindowOpenArgs, WindowIdArgs, WindowArrangeArgs } from './desk'
export { buildCommandManifest, handleCommandRequest, sendCommandManifest } from './bridge'
export type { SendFrame } from './bridge'
export { validateCommandArgs } from './validate'
