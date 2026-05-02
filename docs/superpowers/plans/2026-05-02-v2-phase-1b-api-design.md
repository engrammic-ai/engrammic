# Phase 1b-B: REST API Design Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create OpenAPI 3.0 specification and REST contract documentation for partner review before implementation.

**Architecture:** Contract-first design. Produce machine-readable OpenAPI spec and human-readable contract doc. Get Silt feedback before Phase 2.

**Tech Stack:** OpenAPI 3.0 YAML, Markdown

**Parallel with:** Phase 1b-A (Protocol Adoption)

---

## File Structure

**Deliverables:**
- Create: `docs/api/openapi.yaml` - Full OpenAPI 3.0 specification
- Create: `docs/api/REST-CONTRACT.md` - Design rationale, auth flow, webhook contract

---

## Task 1: Create OpenAPI Skeleton

**Files:**
- Create: `docs/api/openapi.yaml`

- [ ] **Step 1: Create docs/api directory**

```bash
mkdir -p docs/api
```

- [ ] **Step 2: Create OpenAPI skeleton with info and servers**

Create `docs/api/openapi.yaml`:

```yaml
openapi: 3.0.3
info:
  title: Delta Prime Context Service API
  description: |
    REST API for the Delta Prime Context Service.
    Provides context storage, retrieval, and management for AI applications.
  version: 1.0.0
  contact:
    name: Delta Prime
    email: api@deltaprime.dev

servers:
  - url: https://api.deltaprime.dev/v1
    description: Production
  - url: https://staging-api.deltaprime.dev/v1
    description: Staging
  - url: http://localhost:8000/v1
    description: Local development

tags:
  - name: context
    description: Context read and write operations
  - name: silos
    description: Silo management
  - name: webhooks
    description: Webhook registration and management
  - name: org
    description: Organization and user management
  - name: bulk
    description: Bulk operations
  - name: health
    description: Health and readiness checks

security:
  - bearerAuth: []

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
      description: WorkOS session token

paths: {}
```

- [ ] **Step 3: Commit skeleton**

```bash
git add docs/api/openapi.yaml
git commit -m "docs: add OpenAPI skeleton"
```

---

## Task 2: Add Common Components

**Files:**
- Modify: `docs/api/openapi.yaml`

- [ ] **Step 1: Add error response schema**

Add to `components`:

```yaml
components:
  schemas:
    Error:
      type: object
      required:
        - error
      properties:
        error:
          type: object
          required:
            - code
            - message
          properties:
            code:
              type: string
              enum:
                - VALIDATION_ERROR
                - UNAUTHORIZED
                - FORBIDDEN
                - NOT_FOUND
                - CONFLICT
                - PAYLOAD_TOO_LARGE
                - RATE_LIMITED
                - INTERNAL_ERROR
                - SERVICE_UNAVAILABLE
            message:
              type: string
              description: Human-readable error description
            details:
              type: object
              additionalProperties: true
              description: Additional error context

    PaginatedResponse:
      type: object
      properties:
        next_cursor:
          type: string
          nullable: true
          description: Cursor for next page, null if no more pages

    Node:
      type: object
      required:
        - id
        - silo_id
        - type
        - content
        - created_at
      properties:
        id:
          type: string
          format: uuid
        silo_id:
          type: string
          format: uuid
        type:
          type: string
          enum: [memory, knowledge, wisdom, intelligence]
        content:
          type: string
        metadata:
          type: object
          additionalProperties: true
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time
          nullable: true

  parameters:
    cursor:
      name: cursor
      in: query
      schema:
        type: string
      description: Pagination cursor from previous response
    limit:
      name: limit
      in: query
      schema:
        type: integer
        minimum: 1
        maximum: 100
        default: 50
      description: Maximum items per page
    silo_id:
      name: silo_id
      in: path
      required: true
      schema:
        type: string
        format: uuid
      description: Silo identifier

  responses:
    BadRequest:
      description: Invalid request
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    Unauthorized:
      description: Missing or invalid authentication
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    Forbidden:
      description: Insufficient permissions
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    NotFound:
      description: Resource not found
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
    RateLimited:
      description: Rate limit exceeded
      headers:
        Retry-After:
          schema:
            type: integer
          description: Seconds until rate limit resets
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
```

- [ ] **Step 2: Commit**

```bash
git add docs/api/openapi.yaml
git commit -m "docs: add OpenAPI common components"
```

---

## Task 3: Add Core Context Endpoints

**Files:**
- Modify: `docs/api/openapi.yaml`

- [ ] **Step 1: Add context_get endpoint**

Add to `paths`:

```yaml
paths:
  /context/{id}:
    get:
      operationId: context_get
      summary: Get context node by ID
      tags: [context]
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Context node
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Node'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '404':
          $ref: '#/components/responses/NotFound'
```

- [ ] **Step 2: Add context_query endpoint**

```yaml
  /context/query:
    post:
      operationId: context_query
      summary: Semantic search for context
      tags: [context]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - query
              properties:
                query:
                  type: string
                  minLength: 1
                  maxLength: 10000
                silo_id:
                  type: string
                  format: uuid
                limit:
                  type: integer
                  minimum: 1
                  maximum: 100
                  default: 10
                filters:
                  type: object
                  properties:
                    types:
                      type: array
                      items:
                        type: string
                        enum: [memory, knowledge, wisdom, intelligence]
                    as_of:
                      type: string
                      format: date-time
                      description: Time-travel query point
      responses:
        '200':
          description: Search results
          content:
            application/json:
              schema:
                type: object
                properties:
                  results:
                    type: array
                    items:
                      type: object
                      properties:
                        node:
                          $ref: '#/components/schemas/Node'
                        score:
                          type: number
                          format: float
        '400':
          $ref: '#/components/responses/BadRequest'
        '401':
          $ref: '#/components/responses/Unauthorized'
```

- [ ] **Step 3: Add write endpoints (remember, assert, commit, reflect)**

```yaml
  /context/remember:
    post:
      operationId: context_remember
      summary: Store a memory
      tags: [context]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - content
                - silo_id
              properties:
                content:
                  type: string
                  maxLength: 100000
                silo_id:
                  type: string
                  format: uuid
                metadata:
                  type: object
                  additionalProperties: true
      responses:
        '201':
          description: Memory created
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid
        '400':
          $ref: '#/components/responses/BadRequest'
        '401':
          $ref: '#/components/responses/Unauthorized'

  /context/assert:
    post:
      operationId: context_assert
      summary: Assert a knowledge claim with evidence
      tags: [context]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - content
                - silo_id
                - evidence
              properties:
                content:
                  type: string
                silo_id:
                  type: string
                  format: uuid
                evidence:
                  type: array
                  minItems: 1
                  items:
                    type: string
                    format: uuid
                  description: Node IDs that support this assertion
      responses:
        '201':
          description: Claim created
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid
        '400':
          $ref: '#/components/responses/BadRequest'
        '401':
          $ref: '#/components/responses/Unauthorized'

  /context/commit:
    post:
      operationId: context_commit
      summary: Commit a wisdom-level belief
      tags: [context]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - content
                - silo_id
              properties:
                content:
                  type: string
                silo_id:
                  type: string
                  format: uuid
                confidence:
                  type: number
                  format: float
                  minimum: 0
                  maximum: 1
      responses:
        '201':
          description: Belief committed
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid

  /context/reflect:
    post:
      operationId: context_reflect
      summary: Create a meta-observation
      tags: [context]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - content
                - silo_id
                - about
              properties:
                content:
                  type: string
                silo_id:
                  type: string
                  format: uuid
                about:
                  type: array
                  items:
                    type: string
                    format: uuid
                  description: Node IDs this reflection is about
      responses:
        '201':
          description: Reflection created
          content:
            application/json:
              schema:
                type: object
                properties:
                  id:
                    type: string
                    format: uuid
```

- [ ] **Step 4: Commit**

```bash
git add docs/api/openapi.yaml
git commit -m "docs: add core context endpoints to OpenAPI"
```

---

## Task 4: Add Silo Management Endpoints

**Files:**
- Modify: `docs/api/openapi.yaml`

- [ ] **Step 1: Add silo CRUD endpoints**

```yaml
  /silos:
    get:
      operationId: list_silos
      summary: List silos for current org
      tags: [silos]
      parameters:
        - $ref: '#/components/parameters/cursor'
        - $ref: '#/components/parameters/limit'
        - name: include_archived
          in: query
          schema:
            type: boolean
            default: false
      responses:
        '200':
          description: List of silos
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/PaginatedResponse'
                  - type: object
                    properties:
                      silos:
                        type: array
                        items:
                          $ref: '#/components/schemas/Silo'
    post:
      operationId: create_silo
      summary: Create a new silo
      tags: [silos]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - name
              properties:
                name:
                  type: string
                  maxLength: 255
                description:
                  type: string
                  maxLength: 1000
      responses:
        '201':
          description: Silo created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Silo'

  /silos/{silo_id}:
    get:
      operationId: get_silo
      summary: Get silo details
      tags: [silos]
      parameters:
        - $ref: '#/components/parameters/silo_id'
      responses:
        '200':
          description: Silo details
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Silo'
    delete:
      operationId: delete_silo
      summary: Delete silo (soft delete by default)
      tags: [silos]
      parameters:
        - $ref: '#/components/parameters/silo_id'
        - name: hard
          in: query
          schema:
            type: boolean
            default: false
          description: If true, permanently delete (requires admin)
      responses:
        '204':
          description: Silo deleted

  /silos/{silo_id}/restore:
    post:
      operationId: restore_silo
      summary: Restore archived silo
      tags: [silos]
      parameters:
        - $ref: '#/components/parameters/silo_id'
      responses:
        '200':
          description: Silo restored
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Silo'
```

- [ ] **Step 2: Add Silo schema**

Add to components/schemas:

```yaml
    Silo:
      type: object
      required:
        - id
        - name
        - org_id
        - created_at
      properties:
        id:
          type: string
          format: uuid
        name:
          type: string
        description:
          type: string
          nullable: true
        org_id:
          type: string
        created_at:
          type: string
          format: date-time
        archived_at:
          type: string
          format: date-time
          nullable: true
        stats:
          type: object
          properties:
            node_count:
              type: integer
            edge_count:
              type: integer
            storage_bytes:
              type: integer
```

- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi.yaml
git commit -m "docs: add silo management endpoints to OpenAPI"
```

---

## Task 5: Add Webhook Endpoints

**Files:**
- Modify: `docs/api/openapi.yaml`

- [ ] **Step 1: Add webhook schemas**

```yaml
    Webhook:
      type: object
      required:
        - id
        - url
        - created_at
      properties:
        id:
          type: string
          format: uuid
        url:
          type: string
          format: uri
        filters:
          $ref: '#/components/schemas/WebhookFilters'
        created_at:
          type: string
          format: date-time

    WebhookFilters:
      type: object
      properties:
        event_types:
          type: array
          items:
            type: string
            enum: [context.created, context.updated, claim.promoted, cluster.updated]
        silo_ids:
          type: array
          items:
            type: string
            format: uuid
        layers:
          type: array
          items:
            type: string
            enum: [memory, knowledge, wisdom, intelligence]

    WebhookEvent:
      type: object
      required:
        - event_type
        - event_id
        - timestamp
        - silo_id
        - data
      properties:
        event_type:
          type: string
        event_id:
          type: string
          format: uuid
        timestamp:
          type: string
          format: date-time
        silo_id:
          type: string
          format: uuid
        data:
          type: object
          properties:
            node_id:
              type: string
              format: uuid
            layer:
              type: string
            content_preview:
              type: string
              maxLength: 200
```

- [ ] **Step 2: Add webhook endpoints**

```yaml
  /webhooks:
    get:
      operationId: list_webhooks
      summary: List registered webhooks
      tags: [webhooks]
      parameters:
        - $ref: '#/components/parameters/cursor'
        - $ref: '#/components/parameters/limit'
      responses:
        '200':
          description: List of webhooks
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/PaginatedResponse'
                  - type: object
                    properties:
                      webhooks:
                        type: array
                        items:
                          $ref: '#/components/schemas/Webhook'
    post:
      operationId: create_webhook
      summary: Register a webhook
      tags: [webhooks]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - url
              properties:
                url:
                  type: string
                  format: uri
                secret:
                  type: string
                  description: HMAC secret (auto-generated if omitted)
                filters:
                  $ref: '#/components/schemas/WebhookFilters'
      responses:
        '201':
          description: Webhook created
          content:
            application/json:
              schema:
                allOf:
                  - $ref: '#/components/schemas/Webhook'
                  - type: object
                    properties:
                      secret:
                        type: string
                        description: Only returned on creation

  /webhooks/{id}:
    delete:
      operationId: delete_webhook
      summary: Unregister a webhook
      tags: [webhooks]
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '204':
          description: Webhook deleted

  /webhooks/{id}/rotate-secret:
    post:
      operationId: rotate_webhook_secret
      summary: Rotate webhook secret
      tags: [webhooks]
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: New secret (old valid for 24h)
          content:
            application/json:
              schema:
                type: object
                properties:
                  secret:
                    type: string
                  old_secret_valid_until:
                    type: string
                    format: date-time
```

- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi.yaml
git commit -m "docs: add webhook endpoints to OpenAPI"
```

---

## Task 6: Add Bulk and Health Endpoints

**Files:**
- Modify: `docs/api/openapi.yaml`

- [ ] **Step 1: Add bulk ingest endpoints**

```yaml
  /ingest:
    post:
      operationId: bulk_ingest
      summary: Batch ingest documents/memories
      tags: [bulk]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - items
                - silo_id
              properties:
                silo_id:
                  type: string
                  format: uuid
                items:
                  type: array
                  maxItems: 10000
                  items:
                    type: object
                    required:
                      - content
                    properties:
                      content:
                        type: string
                        maxLength: 1048576
                      type:
                        type: string
                        default: memory
                      metadata:
                        type: object
      responses:
        '202':
          description: Job accepted
          content:
            application/json:
              schema:
                type: object
                properties:
                  job_id:
                    type: string
                    format: uuid
        '413':
          description: Payload too large
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'

  /ingest/{job_id}:
    get:
      operationId: get_ingest_status
      summary: Get bulk ingest job status
      tags: [bulk]
      parameters:
        - name: job_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Job status
          content:
            application/json:
              schema:
                type: object
                properties:
                  job_id:
                    type: string
                    format: uuid
                  status:
                    type: string
                    enum: [pending, processing, completed, failed]
                  progress:
                    type: object
                    properties:
                      total:
                        type: integer
                      processed:
                        type: integer
                      succeeded:
                        type: integer
                      failed:
                        type: integer
                  errors:
                    type: array
                    items:
                      type: object
                      properties:
                        index:
                          type: integer
                        error:
                          type: string
```

- [ ] **Step 2: Add health endpoints**

```yaml
  /health:
    get:
      operationId: health_check
      summary: Basic liveness check
      tags: [health]
      security: []
      responses:
        '200':
          description: Service is alive
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    enum: [ok]

  /ready:
    get:
      operationId: readiness_check
      summary: Readiness check (checks dependencies)
      tags: [health]
      security: []
      responses:
        '200':
          description: Service is ready
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    enum: [ok]
                  checks:
                    type: object
                    properties:
                      memgraph:
                        type: boolean
                      qdrant:
                        type: boolean
                      redis:
                        type: boolean
        '503':
          description: Service not ready
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    enum: [degraded]
                  checks:
                    type: object
```

- [ ] **Step 3: Commit**

```bash
git add docs/api/openapi.yaml
git commit -m "docs: add bulk and health endpoints to OpenAPI"
```

---

## Task 7: Create REST Contract Document

**Files:**
- Create: `docs/api/REST-CONTRACT.md`

- [ ] **Step 1: Write contract document**

Create `docs/api/REST-CONTRACT.md`:

```markdown
# Delta Prime REST API Contract

This document describes the design rationale and contracts for the Delta Prime Context Service REST API.

## Overview

The REST API provides HTTP access to the same capabilities as the MCP tools, enabling non-agent consumers to integrate with the Context Service.

**OpenAPI Spec:** `openapi.yaml` (machine-readable)

## Authentication

All endpoints (except `/health` and `/ready`) require authentication.

### Bearer Token Flow

1. Client authenticates via WorkOS
2. WorkOS returns a session token
3. Client sends token in `Authorization: Bearer <token>` header
4. Server validates token via `workos.verify_session()` (cached 60s)

### Org Binding

The token contains `org_id`. All operations are automatically scoped to this org.

### Role Enforcement

| Role | Permissions |
|------|-------------|
| `viewer` | GET endpoints only |
| `member` | GET + POST (context ops, ingest, webhooks) |
| `admin` | All endpoints including DELETE, org management |

## Silo Ownership

Every silo belongs to an org. Before any silo operation:

```
assert_silo_belongs_to_org(silo_id, auth_ctx.org_id)
```

Returns 403 FORBIDDEN if the silo doesn't belong to the caller's org.

## Pagination

All list endpoints use cursor-based pagination:

```
GET /v1/silos?cursor=<opaque>&limit=50
```

Response:
```json
{
  "silos": [...],
  "next_cursor": "eyJvZmZzZXQiOjUwfQ=="
}
```

- `next_cursor` is null when no more pages
- Cursors are HMAC-signed to prevent tampering
- Invalid cursors return 400 VALIDATION_ERROR

## Rate Limiting

| Scope | Limit | Burst |
|-------|-------|-------|
| Global | 1000 req/min per org | 100 concurrent |
| Bulk endpoints | 10 req/min per org | 3 |
| Webhook registration | 100/hour per org | - |

Response headers:
- `X-RateLimit-Limit`: requests allowed per window
- `X-RateLimit-Remaining`: requests remaining
- `X-RateLimit-Reset`: Unix timestamp when limit resets

Exceeded: 429 with `Retry-After` header.

## Error Responses

All errors follow this format:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Silo not found",
    "details": {"silo_id": "abc-123"}
  }
}
```

### Error Codes

| Code | HTTP | Description |
|------|------|-------------|
| VALIDATION_ERROR | 400 | Invalid request |
| UNAUTHORIZED | 401 | Missing/invalid auth |
| FORBIDDEN | 403 | Insufficient permissions |
| NOT_FOUND | 404 | Resource not found |
| CONFLICT | 409 | Concurrent write conflict |
| PAYLOAD_TOO_LARGE | 413 | Bulk request too large |
| RATE_LIMITED | 429 | Rate limit exceeded |
| INTERNAL_ERROR | 500 | Server error |
| SERVICE_UNAVAILABLE | 503 | Dependency down |

## Request Tracing

All requests include `X-Request-ID`:
- Use client-provided value if present
- Otherwise generate UUID

Request ID appears in:
- All log entries
- Error responses
- Webhook payloads

## Webhooks

### Registration

```
POST /v1/webhooks
{
  "url": "https://example.com/webhook",
  "filters": {
    "event_types": ["context.created"],
    "silo_ids": ["uuid"],
    "layers": ["memory", "knowledge"]
  }
}
```

Filters are AND-ed. Omit for wildcard.

### Delivery Contract

**Signature:**
```
X-Delta-Signature: t=1234567890,v1=<hmac-sha256>
```

Signature covers: `timestamp.payload`

**Replay Protection:** Reject if timestamp > 5 minutes old.

**Retry Policy:** 1s, 5s, 30s, 5m, 30m (max 5 attempts)

**Idempotency:** `event_id` is unique. Receivers should dedupe.

### Event Payload

```json
{
  "event_type": "context.created",
  "event_id": "uuid",
  "timestamp": "2026-05-02T12:00:00Z",
  "silo_id": "uuid",
  "data": {
    "node_id": "uuid",
    "layer": "memory",
    "content_preview": "First 200 chars..."
  }
}
```

## Bulk Operations

### Ingest

```
POST /v1/ingest
{
  "silo_id": "uuid",
  "items": [
    {"content": "...", "type": "memory"},
    ...
  ]
}
```

**Limits:**
- Max 10,000 items
- Max 50MB payload
- Max 1MB per item

**Semantics:** Partial success. Response includes succeeded/failed arrays.

```json
{
  "job_id": "uuid",
  "status": "completed",
  "progress": {
    "total": 100,
    "succeeded": 98,
    "failed": 2
  },
  "errors": [
    {"index": 42, "error": "Content too large"},
    {"index": 87, "error": "Invalid metadata"}
  ]
}
```

## Audit Logging

All write/delete operations are logged:

| Field | Description |
|-------|-------------|
| timestamp | ISO8601 |
| org_id | Caller's org |
| user_id | Caller's user |
| action | Operation name |
| resource_type | silo, node, webhook, etc. |
| resource_id | UUID |
| request_id | X-Request-ID |
| details | Operation-specific data |

Hard delete blocked until audit entry written.

Retention: 7 years (configurable).

Query: `GET /v1/org/audit` (admin only)
```

- [ ] **Step 2: Commit**

```bash
git add docs/api/REST-CONTRACT.md
git commit -m "docs: add REST API contract document"
```

---

## Task 8: Validate and Finalize

- [ ] **Step 1: Validate OpenAPI spec**

```bash
# Install spectral if needed
npm install -g @stoplight/spectral-cli

# Validate
spectral lint docs/api/openapi.yaml
```

- [ ] **Step 2: Generate preview (optional)**

```bash
# Preview with Redoc
npx @redocly/cli preview-docs docs/api/openapi.yaml
```

- [ ] **Step 3: Create PR for Silt review**

```bash
git push -u origin phase-v2-1b-api-design
gh pr create --title "Phase 1b-B: REST API design (OpenAPI + contract)" --body "$(cat <<'EOF'
## Summary
- OpenAPI 3.0 specification covering all REST endpoints
- REST contract document with auth, pagination, webhooks, bulk ops
- Ready for Silt review before Phase 2 implementation

## Endpoints covered
- Core context: get, query, remember, assert, commit, reflect
- Silos: CRUD, export/import, restore
- Webhooks: register, list, delete, rotate-secret
- Bulk: ingest, status
- Health: liveness, readiness

## Review requested
@silt-team - please review the API contract and flag any blockers

Spec: docs/superpowers/specs/2026-05-02-arch-cleanup-perf-rest-api.md
EOF
)"
```
