# Cairn Module - Blackboard-Based Multi-Agent Collaboration

## Overview

Cairn implements a **blackboard architecture** for multi-agent collaboration in Flocks, inspired by the original Cairn project. It enables agents to coordinate indirectly through a shared knowledge graph without direct communication.

## Core Concepts

### 1. Fact (事实)
- Immutable, objective facts about the problem domain
- Only appendable, never modifiable
- Special facts: `origin` (starting point) and `goal` (target)

### 2. Intent (意图)
- Exploration direction from certain Facts toward new conclusions
- Can be claimed by workers for execution
- Supports hyperedges (multiple source Facts → one target)

### 3. Hint (提示)
- External strategic suggestions from users or systems
- Not part of the fact graph, but influences exploration

### 4. Project (项目)
- Container for a complete exploration session
- Tracks status: `active`, `stopped`, `completed`
- Manages reason lease for coordination

## Architecture

```
┌─────────────────────────────────────┐
│         WebUI (React)               │
│  - Project List                     │
│  - DAG Visualization                │
│  - Fact/Intent/Hint Manager         │
└──────────────┬──────────────────────┘
               │ HTTP API
┌──────────────▼──────────────────────┐
│     FastAPI Routes (/api/cairn)     │
│  - Projects CRUD                    │
│  - Intent lifecycle                 │
│  - Reason lease management          │
│  - Export (YAML/Timeline)           │
└──────────────┬──────────────────────┘
               │
┌──────────────▼──────────────────────┐
│      CairnStorage (SQLite)          │
│  - cairn_projects                   │
│  - cairn_facts                      │
│  - cairn_intents                    │
│  - cairn_hints                      │
└─────────────────────────────────────┘
```

## API Endpoints

### Projects
- `POST /api/cairn/projects` - Create new project
- `GET /api/cairn/projects` - List all projects
- `GET /api/cairn/projects/{id}` - Get project details
- `DELETE /api/cairn/projects/{id}` - Delete project
- `PUT /api/cairn/projects/{id}/title` - Update title
- `PUT /api/cairn/projects/{id}/status` - Update status (active/stopped)

### Intents
- `POST /api/cairn/projects/{id}/intents` - Create intent
- `POST /api/cairn/projects/{id}/intents/{intent_id}/heartbeat` - Claim/renew intent
- `POST /api/cairn/projects/{id}/intents/{intent_id}/release` - Release intent
- `POST /api/cairn/projects/{id}/intents/{intent_id}/conclude` - Conclude with new fact

### Hints
- `POST /api/cairn/projects/{id}/hints` - Add hint

### Reason Lease
- `POST /api/cairn/projects/{id}/reason/claim` - Claim project-level reason lock
- `POST /api/cairn/projects/{id}/reason/heartbeat` - Heartbeat reason lease
- `POST /api/cairn/projects/{id}/reason/release` - Release reason lease

### Completion
- `POST /api/cairn/projects/{id}/complete` - Mark project as completed
- `POST /api/cairn/projects/{id}/reopen` - Reopen completed project with feedback

### Export
- `GET /api/cairn/projects/{id}/export?format=yaml` - Export as YAML

## Usage Example

### Create a Project

```bash
curl -X POST http://localhost:8000/api/cairn/projects \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Security Analysis",
    "origin": "Detected suspicious network activity on port 443",
    "goal": "Identify root cause and recommend mitigation",
    "hints": [
      {"content": "Check recent firewall rule changes", "creator": "admin"}
    ]
  }'
```

### Create an Intent

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_xxx/intents \
  -H "Content-Type: application/json" \
  -d '{
    "from": ["origin"],
    "description": "Analyze network traffic patterns",
    "creator": "analyst-1",
    "worker": "agent-security"
  }'
```

### Heartbeat (Claim/Renew)

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_xxx/intents/i_yyy/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"worker": "agent-security"}'
```

### Conclude Intent

```bash
curl -X POST http://localhost:8000/api/cairn/projects/proj_xxx/intents/i_yyy/conclude \
  -H "Content-Type: application/json" \
  -d '{
    "worker": "agent-security",
    "description": "Found anomalous outbound connections to known C2 server"
  }'
```

## Implementation Status

### Phase 1: ✅ Complete (Core Models & Storage)
- [x] Data models (`Fact`, `Intent`, `Hint`, `Project`)
- [x] SQLite storage layer with full CRUD operations
- [x] Timeout handling for stale claims
- [x] Unit tests for storage layer

### Phase 2: 🚧 In Progress (API Protocol)
- [x] FastAPI routes for all protocol endpoints
- [x] Request validation with Pydantic
- [x] Error handling and logging
- [ ] Integration tests
- [ ] WebSocket support for real-time updates

### Phase 3: ⏳ Planned (Dispatcher & Tasks)
- [ ] Simplified dispatcher (single instance)
- [ ] Task executors (bootstrap/reason/explore)
- [ ] Worker selection algorithm
- [ ] Integration with Flocks Session system

### Phase 4: ⏳ Planned (WebUI)
- [ ] Project list page
- [ ] Project detail page with table view
- [ ] DAG visualization (react-flow)
- [ ] Manual intent/hint creation UI
- [ ] Real-time status updates

## Design Principles

1. **Minimal Impact**: Reuses Flocks' existing infrastructure (Session, Agent, Tool systems)
2. **Compatibility**: Follows Cairn's collaboration protocol exactly
3. **First Principles**: Focuses on blackboard architecture core concepts
4. **Progressive Enhancement**: Starts simple, adds complexity incrementally

## Future Enhancements

- Multi-instance dispatcher with distributed locks
- Docker container isolation for workers
- Advanced DAG visualization with interactive features
- Timeline export for audit trails
- Integration with Flocks workflow engine for automated exploration

## References

- Original Cairn design: `workspace/outputs/2026-05-30/Cairn-main/docs/specs/dispatcher-design.md`
- Server protocol: `workspace/outputs/2026-05-30/Cairn-main/docs/specs/server-protocol.md`
