# W1: Engine Repo

Parent: [oss-master.md](./oss-master.md)

Goal: Build `delta-prime/engine/` — single-tenant SQLite-backed engine with basic MCP server.

License: Apache 2.0

## Structure

```
engine/
├── pyproject.toml
├── LICENSE                 # Apache 2.0
├── README.md
├── src/
│   └── engine/
│       ├── __init__.py
│       ├── __main__.py     # CLI entry: python -m engine
│       ├── store/
│       │   ├── __init__.py
│       │   ├── sqlite.py   # SQLite implementation of primitives protocols
│       │   └── models.py   # Pydantic models for persistence
│       └── mcp/
│           ├── __init__.py
│           ├── server.py   # FastMCP server
│           └── tools.py    # MCP tool implementations
├── tests/
│   ├── conftest.py
│   ├── test_store.py
│   └── test_mcp.py
└── examples/
    └── quickstart.py
```

## Tasks

### Task 1: Repo scaffold

- [ ] Create engine/ directory in delta-prime/
- [ ] Add pyproject.toml with dependencies (primitives, fastmcp, sqlite3)
- [ ] Add Apache 2.0 LICENSE file
- [ ] Add minimal README.md
- [ ] Initialize git, first commit

### Task 2: SQLite store — schema

- [ ] Create src/engine/store/models.py with Pydantic models
  - Node (id, silo_id, layer, content, metadata, created_at, updated_at)
  - Edge (source_id, target_id, edge_type, metadata)
- [ ] Create src/engine/store/sqlite.py with schema init
  - nodes table
  - edges table
  - indexes on silo_id, layer
- [ ] Write test: schema creates tables correctly
- [ ] Commit

### Task 3: SQLite store — write operations

- [ ] Implement create_node() — insert node, return id
- [ ] Implement create_edge() — insert edge between nodes
- [ ] Implement update_node() — update content/metadata
- [ ] Write tests for each operation
- [ ] Commit

### Task 4: SQLite store — read operations

- [ ] Implement get_node(id) — fetch single node
- [ ] Implement query_nodes(silo_id, layer, filters) — filtered fetch
- [ ] Implement get_edges(node_id, direction) — incoming/outgoing edges
- [ ] Write tests for each operation
- [ ] Commit

### Task 5: SQLite store — layer operations

- [ ] Implement promote_node(id, from_layer, to_layer) — manual promotion
- [ ] Implement delete_node(id) — soft delete with superseded_at
- [ ] Write tests
- [ ] Commit

### Task 6: MCP server — scaffold

- [ ] Create src/engine/mcp/server.py with FastMCP app
- [ ] Create src/engine/mcp/tools.py with tool stubs
- [ ] Wire store as dependency
- [ ] Write test: server starts without error
- [ ] Commit

### Task 7: MCP tools — reads

- [ ] Implement context_get tool — fetch node by id
- [ ] Implement context_query tool — query nodes with filters
- [ ] Write tests using MCP test client
- [ ] Commit

### Task 8: MCP tools — writes

- [ ] Implement context_remember tool — create Memory node
- [ ] Implement context_assert tool — create Knowledge claim
- [ ] Implement context_commit tool — create Wisdom node
- [ ] Write tests
- [ ] Commit

### Task 9: MCP tools — promotion

- [ ] Implement context_promote tool — manual layer promotion
- [ ] Write test: claim promoted to fact
- [ ] Commit

### Task 10: CLI entry point

- [ ] Create src/engine/__main__.py
- [ ] Parse args: --host, --port, --db-path
- [ ] Start MCP server
- [ ] Test: `python -m engine` runs server
- [ ] Commit

### Task 11: Examples

- [ ] Create examples/quickstart.py
  - Connect to engine
  - Write a claim
  - Promote to fact
  - Query it back
- [ ] Test example runs end-to-end
- [ ] Commit

### Task 12: README + docs

- [ ] Update README.md with:
  - What this is
  - Installation
  - Quickstart
  - Link to manifesto
  - "Why Apache 2.0" section
- [ ] Commit

## Done Criteria

- [ ] `pip install -e .` works
- [ ] `python -m engine` starts MCP server
- [ ] All MCP tools functional (remember, assert, commit, get, query, promote)
- [ ] examples/quickstart.py runs successfully
- [ ] All tests pass
