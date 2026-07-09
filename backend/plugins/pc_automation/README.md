# PC Automation Plugin

Plugin for controlling the local Windows PC through whitelisted, sandboxed automation tools.

## Architecture

```
pc_automation/
├── __init__.py       # Plugin registration in PLUGIN_REGISTRY
├── constants.py      # Whitelists, forbidden paths, lockout settings
├── security.py       # Validation functions + ScreenshotLockout
├── validators.py     # Safe subprocess wrapper + input sanitization
├── executor.py       # Async execution wrappers (asyncio.to_thread)
├── plugin.py         # PcAutomationPlugin (BasePlugin subclass)
└── README.md         # This file
```

## Security Model

All PC automation tools are security-sensitive. The plugin implements multiple layers of protection:

### 1. Whitelists (constants.py)
- **Applications**: Only pre-approved apps can be opened/closed
- **Commands**: Only safe, read-only commands can be executed
- **Key combos**: Dangerous shortcuts (Ctrl+Alt+Del, Win+R) are blocked
- **Paths**: System directories (C:\Windows, C:\Program Files) are protected

### 2. Risk Levels
| Tool | Risk Level | Confirmation Required |
|------|-----------|----------------------|
| get_active_window | safe | No |
| get_running_apps | safe | No |
| open_application | medium | Yes |
| close_application | medium | Yes |
| type_text | medium | Yes |
| press_keys | medium | Yes |
| take_screenshot | medium | Yes |
| move_mouse | medium | Yes |
| click | medium | Yes |
| execute_command | dangerous | Yes |

### 3. Post-Screenshot Lockout
After `take_screenshot` is called, `execute_command` is blocked for 60 seconds to prevent prompt injection attacks that could exfiltrate screenshot data.

### 4. FORBIDDEN Enforcement
Tools with `risk_level="forbidden"` are blocked at the tool loop level and cannot be executed under any circumstances.

### 5. Subprocess Security
- Always `shell=False` (no shell injection)
- Arguments passed as list (no command concatenation)
- Timeout enforcement (30s default)
- Output truncation (500 chars max)
- Shell metacharacters blocked (`;`, `|`, `&`, `` ` ``, etc.)

## Configuration

```yaml
# config/default.yaml
pc_automation:
  screenshot_lockout_s: 60
  command_timeout_s: 30
  max_command_output_chars: 500
  confirmations_enabled: true
```

## Dependencies

Optional (imported lazily):
- `pyautogui` — mouse/keyboard automation
- `pywinauto` — Windows GUI automation
- `pywin32` — Windows API access

The plugin degrades gracefully if dependencies are missing.

## Audit Trail

All tool confirmations (approved/rejected) are logged to the `tool_confirmation_audit` database table with:
- Tool name and arguments
- Risk level
- User decision (approved/rejected)
- LLM reasoning/thinking content
- Timestamp

Query via: `GET /api/audit/confirmations`
