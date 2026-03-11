# n8n MCP Integration — Setup Guide

> **O.M.N.I.A. Phase 11** — Connecting to n8n as an MCP Server

## What is n8n?

[n8n](https://n8n.io) is an open-source workflow automation platform that can
be self-hosted. Starting from n8n v1.76+, it supports the **Model Context
Protocol (MCP)** natively, allowing AI assistants to trigger n8n workflows
as MCP tools.

## Prerequisites

| Requirement | Minimum Version |
|-------------|----------------|
| n8n         | v1.76+         |
| Node.js     | v18+           |
| OMNIA       | Phase 11       |

## Quick Start

### 1. Install n8n (if not already installed)

```powershell
# Option A: npm global install
npm install -g n8n

# Option B: Docker (recommended for production)
docker run -d --name n8n -p 5678:5678 -v n8n_data:/home/node/.n8n n8nio/n8n
```

### 2. Start n8n

```powershell
# Direct
n8n start

# Or with environment variables
$env:N8N_PORT = "5678"
n8n start
```

n8n will be accessible at `http://localhost:5678`.

### 3. Enable MCP Server in n8n

1. Open n8n at `http://localhost:5678`
2. Go to **Settings** → **Community Nodes** or **MCP** section
3. Enable the **MCP Server** feature

> **Note**: In n8n v1.76+, MCP support is built-in. The MCP SSE endpoint
> is available at `http://localhost:5678/mcp/sse` once enabled.

### 4. Create Workflows as Tools

Each n8n workflow that you want to expose as an MCP tool needs:

1. An **MCP Trigger** node as the starting point
2. A descriptive **name** (this becomes the tool name)
3. Clear **input parameters** defined in the trigger
4. A **response** node at the end

Example workflow: "Send Email Notification"
- Trigger: MCP Trigger with parameters `{to: string, subject: string, body: string}`
- Action: Gmail/SMTP node sends the email
- Response: Returns `{success: true, messageId: "..."}`

### 5. Configure OMNIA

Edit `config/default.yaml` and add n8n to the MCP servers list:

```yaml
mcp:
  servers:
    - name: n8n
      transport: sse
      url: "http://localhost:5678/mcp/sse"
      enabled: true
```

### 6. Verify Connection

After restarting OMNIA:

1. Open **Settings** → **Server MCP** in the UI
2. The n8n server should show as "Connesso" (Connected)
3. Workflow tools will appear as `mcp_n8n_{workflow_name}`
4. Ask the assistant to list available tools — n8n workflows should be included

## Workflow Examples for OMNIA

### Home Automation via n8n
```
Trigger: MCP Trigger (command: string, device: string)
→ HTTP Request to Home Assistant API
→ Response: {executed: true}
```

### Send Telegram Message
```
Trigger: MCP Trigger (message: string)
→ Telegram Bot node
→ Response: {sent: true, chat_id: "..."}
```

### Web Scraping
```
Trigger: MCP Trigger (url: string)
→ HTTP Request → HTML Extract
→ Response: {title: "...", content: "..."}
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection refused | Verify n8n is running on port 5678 |
| No tools visible | Ensure workflows have MCP Trigger nodes |
| SSE endpoint not found | Update n8n to v1.76+ or enable MCP feature |
| Tools error on execution | Check n8n workflow logs at `http://localhost:5678` |

## Resources

- [n8n MCP Documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-langchain.mcpserver/)
- [n8n Self-Hosting Guide](https://docs.n8n.io/hosting/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
