# Cairn Quick Start Guide

## Prerequisites

- Flocks server running (default: `http://localhost:8000`)
- WebUI accessible (default: `http://localhost:5173`)
- Python 3.10+ with required dependencies

## Step 1: Verify Installation

Check that Cairn module is properly installed:

```bash
python -c "from flocks.cairn.models import Project; print('✅ Cairn models loaded')"
```

## Step 2: Start the Server

If not already running:

```bash
cd d:\Project\Cybersecurity\flocks
flocks serve
```

The server will automatically:
- Initialize Cairn SQLite database at `~/.flocks/cairn.db`
- Register `/api/cairn/*` routes
- Make Cairn available in WebUI

## Step 3: Access WebUI

Open your browser and navigate to:
```
http://localhost:5173/cairn
```

You should see:
- Empty state with "Create Project" button
- Navigation menu includes "Cairn Projects" under AI Workbench

## Step 4: Create Your First Project via API

### Using curl

```bash
curl -X POST http://localhost:8000/api/cairn/projects \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Security Incident Analysis",
    "origin": "Detected unusual outbound traffic on port 443 from internal server 192.168.1.100",
    "goal": "Identify root cause, assess impact, and recommend mitigation steps",
    "hints": [
      {
        "content": "Check recent firewall rule changes in the past 48 hours",
        "creator": "security-analyst"
      },
      {
        "content": "Review DNS query logs for suspicious domain resolutions",
        "creator": "network-team"
      }
    ]
  }'
```

Response:
```json
{
  "id": "proj_01HXYZ...",
  "title": "Security Incident Analysis",
  "status": "active",
  "createdAt": "2026-05-30T11:36:15Z"
}
```

### Using Python

```python
import requests
import json

base_url = "http://localhost:8000/api/cairn"

# Create project
response = requests.post(f"{base_url}/projects", json={
    "title": "Network Anomaly Investigation",
    "origin": "Multiple failed login attempts detected across 15 servers",
    "goal": "Determine if this is a coordinated attack or misconfiguration",
    "hints": [
        {"content": "Check if all servers share the same authentication provider", "creator": "ops-team"}
    ]
})

project = response.json()
print(f"Created project: {project['id']}")
```

## Step 5: Explore the Project

### Get Project Details

```bash
curl http://localhost:8000/api/cairn/projects/proj_01HXYZ... | jq
```

This returns the complete graph including:
- Facts (origin, goal)
- Intents (empty initially)
- Hints (from creation)

### Create an Intent

Intents represent exploration directions. Let's create one to investigate firewall rules:

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_01HXYZ.../intents \
  -H "Content-Type: application/json" \
  -d '{
    "from": ["origin"],
    "description": "Analyze firewall configuration changes in the past 48 hours",
    "creator": "analyst-1",
    "worker": "firewall-agent"
  }'
```

Response:
```json
{
  "id": "i01HXYZ...",
  "from": ["origin"],
  "to": null,
  "description": "Analyze firewall configuration changes in the past 48 hours",
  "creator": "analyst-1",
  "worker": "firewall-agent",
  "lastHeartbeatAt": "2026-05-30T11:40:00Z",
  "createdAt": "2026-05-30T11:40:00Z",
  "concludedAt": null
}
```

### Heartbeat (Claim/Renew)

Workers must heartbeat intents to maintain ownership:

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_01HXYZ.../intents/i01HXYZ.../heartbeat \
  -H "Content-Type: application/json" \
  -d '{"worker": "firewall-agent"}'
```

### Conclude an Intent

When the worker completes its task, it concludes the intent with a new fact:

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_01HXYZ.../intents/i01HXYZ.../conclude \
  -H "Content-Type: application/json" \
  -d '{
    "worker": "firewall-agent",
    "description": "Found 3 unauthorized firewall rule additions allowing outbound traffic to known C2 IPs"
  }'
```

Response includes both the new fact and updated intent:
```json
{
  "fact": {
    "id": "f01HXYZ...",
    "description": "Found 3 unauthorized firewall rule additions allowing outbound traffic to known C2 IPs"
  },
  "intent": {
    "id": "i01HXYZ...",
    "from": ["origin"],
    "to": "f01HXYZ...",
    "description": "Analyze firewall configuration changes in the past 48 hours",
    "creator": "analyst-1",
    "worker": "firewall-agent",
    "concludedAt": "2026-05-30T11:45:00Z"
  }
}
```

### Add More Hints

Users can add strategic hints during exploration:

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_01HXYZ.../hints \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Cross-reference C2 IPs with threat intelligence feeds",
    "creator": "threat-intel-team"
  }'
```

## Step 6: Complete the Project

When the goal is achieved, mark the project as completed:

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_01HXYZ.../complete \
  -H "Content-Type: application/json" \
  -d '{
    "from": ["f01HXYZ..."],
    "description": "Confirmed APT group TTPs match observed behavior. Recommend immediate isolation of affected servers and forensic analysis.",
    "worker": "lead-analyst"
  }'
```

This creates a completion intent linking findings to the goal.

## Step 7: Export Project Data

Export the complete exploration as YAML for documentation or sharing:

```bash
curl http://localhost:8000/api/cairn/projects/proj_01HXYZ.../export?format=yaml \
  -o security_incident_analysis.yaml
```

Example output:
```yaml
project:
  title: Security Incident Analysis
  origin: Detected unusual outbound traffic on port 443 from internal server 192.168.1.100
  goal: Identify root cause, assess impact, and recommend mitigation steps

hints:
  - content: Check recent firewall rule changes in the past 48 hours
    creator: security-analyst
    created_at: '2026-05-30 11:36:15'

facts:
  - id: origin
    description: Detected unusual outbound traffic on port 443 from internal server 192.168.1.100
  - id: goal
    description: Identify root cause, assess impact, and recommend mitigation steps
  - id: f01HXYZ...
    description: Found 3 unauthorized firewall rule additions allowing outbound traffic to known C2 IPs

intents:
  - from:
    - origin
    to: f01HXYZ...
    description: Analyze firewall configuration changes in the past 48 hours
    creator: analyst-1
    worker: firewall-agent
    created_at: '2026-05-30 11:40:00'
    concluded_at: '2026-05-30 11:45:00'
```

## Step 8: View in WebUI

Refresh the WebUI page (`http://localhost:5173/cairn`) to see:
- Project card with statistics
- Fact count: 3 (origin, goal, discovered fact)
- Intent count: 1 (concluded)
- Hint count: 2
- Status: completed

Click the project card to view details (detail page implementation coming in Phase 4).

## Advanced Usage

### Concurrent Workers

Multiple workers can claim different intents simultaneously:

```bash
# Worker 1 claims intent A
curl -X POST http://localhost:8000/api/cairn/projects/proj_xxx/intents/i_aaa/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"worker": "network-analyzer"}'

# Worker 2 claims intent B
curl -X POST http://localhost:8000/api/cairn/projects/proj_xxx/intents/i_bbb/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"worker": "malware-analyzer"}'
```

### Timeout Handling

If a worker doesn't heartbeat within 5 minutes, another worker can claim the intent:

```bash
# After 5+ minutes of inactivity, worker-2 can claim
curl -X POST http://localhost:8000/api/cairn/projects/proj_xxx/intents/i_ccc/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"worker": "backup-worker"}'
```

### Reopening Completed Projects

If new information emerges, reopen with feedback:

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_01HXYZ.../reopen \
  -H "Content-Type: application/json" \
  -d '{
    "description": "New evidence suggests additional compromised systems in subnet 192.168.2.0/24",
    "creator": "incident-commander"
  }'
```

This:
1. Removes the completion intent
2. Creates a feedback fact
3. Creates an external_feedback intent
4. Sets project status back to "active"

## Troubleshooting

### Database Not Created

Check if the database file exists:
```bash
ls -la ~/.flocks/cairn.db
```

If missing, restart the server. The database is created on first API call.

### API Returns 404

Verify the server is running and Cairn routes are registered:
```bash
curl http://localhost:8000/docs
```

Look for "Cairn" tag in the OpenAPI documentation.

### Permission Denied

Ensure you're authenticated. Most endpoints require a valid user session. Check authentication headers if using custom clients.

### Intent Claim Conflicts

If you get a 409 Conflict, the intent is claimed by another worker. Wait for timeout or contact the current worker.

## Next Steps

Now that you've mastered the basics:

1. **Explore the API**: Visit `http://localhost:8000/docs` for interactive API documentation
2. **Build Automation**: Write scripts to automate common workflows
3. **Integrate Agents**: Connect Flocks agents to execute intents automatically
4. **Contribute**: Help implement Phase 3 (Dispatcher) and Phase 4 (DAG Visualization)

## Resources

- [Cairn Module README](flocks/cairn/README.md)
- [Implementation Summary](CAIRN_IMPLEMENTATION_SUMMARY.md)
- [Original Cairn Design](workspace/outputs/2026-05-30/Cairn-main/docs/specs/dispatcher-design.md)
- [Server Protocol Spec](workspace/outputs/2026-05-30/Cairn-main/docs/specs/server-protocol.md)

## Support

For issues or questions:
1. Check existing tests: `tests/cairn/test_storage.py`
2. Review API documentation: `http://localhost:8000/docs`
3. Examine source code: `flocks/cairn/`

Happy exploring! 🚀
