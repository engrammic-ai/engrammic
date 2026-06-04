# Self-Serve Org Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user signs up self-serve (e.g. via the event QR -> hosted AuthKit) with no organization, silently provision a personal `"{name}'s workspace"` org so every authenticated identity resolves to a real `silo_id`, with no signup-time friction.

**Architecture:** Add one shared provisioning helper that resolves an effective org id with the precedence **session `org_id` -> stored user `org_id` -> create new WorkOS org (idempotent)**. Call it from both auth entry points: the `/oauth/callback` route (signup) and `verify_session` (per-request MCP auth, hot path). Only the genuinely-new branch makes a WorkOS round-trip, so the per-request path stays fast and the existing Postgres fail-open contract is preserved for users who already have an org.

**Tech Stack:** Python 3.12 / FastAPI / `workos==6.0.8` SDK / SQLAlchemy async / structlog / pytest. WorkOS calls run via the `auth` dependency-group (`uv run --group auth ...`).

---

## Background & Verified Facts

Established during research (do not re-litigate, but verify against the live SDK if anything fails):

1. **The bug being fixed.** Three code paths disagree on the no-org case:
   - `verify_session` (`auth/workos_client.py:61-63`) **rejects** no-org users: `raise ValueError("WorkOS session response missing organization_id")`.
   - Both `/oauth/callback` branches (`api/routes/oauth.py:301, 342`) **accept** with `effective_org_id = org_id or workos_user_id` — a silo keyed to the *user id*, not a real org.
   This plan makes all three consistent: auto-create a real org.

2. **`silo_id` is derived purely from `org_id`** via `derive_silo_id(org_id)` (`services/models.py:94-96`), `uuid5(NAMESPACE_DNS, f"silo:{org_id}")`. A real org id means a real, shareable silo.

3. **AuthKit auto-scopes single-org users.** WorkOS docs: "If a user only has a single Organization membership, that Organization will be automatically selected ... made available as the `org_id` claim." So once we create the membership, the user's *next* login (sealed session OR OAuth) carries `org_id` automatically. The current-session gap is cosmetic and self-heals. Source: https://workos.com/docs/authkit/users-organizations

4. **SDK surface (`workos==6.0.8`), verified by inspection:**
   - `client.organizations.create_organization(*, name: str, external_id: str | None = None, metadata: dict[str,str] | None = None, ...) -> Organization` (has `.id`).
   - `client.user_management.create_organization_membership(*, user_id: str, organization_id: str, role: ... | None = None, ...) -> OrganizationMembership`.
   - `client.organizations.get_organization_by_external_id(external_id: str) -> Organization`; raises `workos.NotFoundError` when absent (`from workos import NotFoundError` works).

5. **Existing contracts to preserve:**
   - `verify_session` **fails open on Postgres errors** — returns `AuthContext` with `db_user_id=None` for an already-org'd user when the DB is down (`tests/integration/test_auth_user_sync.py:171`). Keep this. Fail *closed* only when we cannot provision an org for a genuinely-new no-org user.
   - `exchange_code_for_user` (`auth/workos_authkit.py:53-95`) currently returns only `{id, email, organization_id}`. It must additionally return `name` so the callback can name the workspace.
   - `UserService.upsert_user(workos_user_id, org_id, silo_id, email, name=None)` and `UserService.get_user_by_workos_id(workos_user_id) -> User | None` already exist (`services/user.py:26, 76`).

6. **Scope boundary (confirmed with product owner):** The QR is a lightweight quick-signup; conversion to actual agent usage happens later via the onboarding flow. The success page CTA (`oauth.py:119`) now targets `join.engrammic.ai` per the join onboarding plan (`2026-05-30-join-engrammic-onboarding-plan.md`).

---

## File Structure

- **Create:** `src/context_service/auth/org_provisioning.py` — all org-provisioning logic: workspace-name derivation, idempotent WorkOS org+membership creation, and the precedence resolver. One responsibility: "given an identity, return its effective org id, creating a personal org if needed." Both callers depend on this; the logic lives in exactly one place.
- **Modify:** `src/context_service/auth/workos_authkit.py` — extend `exchange_code_for_user` to also surface `name`.
- **Modify:** `src/context_service/api/routes/oauth.py` — replace the `org_id or workos_user_id` fallback in both callback branches with a call to the resolver.
- **Modify:** `src/context_service/auth/workos_client.py` — replace the no-org `raise` in `verify_session` with the resolver; preserve Postgres fail-open for org'd users.
- **Modify:** `src/context_service/services/user.py` — persist `org_id`/`silo_id` on the `upsert_user` conflict path so a resolved/upgraded org sticks across requests (fixes B1).
- **Create tests:**
  - `tests/auth/test_org_provisioning.py` — unit tests for the new helper (name derivation, idempotency, precedence).
  - `tests/integration/test_oauth_org_creation.py` — callback creates an org for no-org signup.
  - Extend `tests/integration/test_auth_user_sync.py` — `verify_session` provisions instead of raising, and still fails open for org'd users.

---

## Task 1: Workspace-name derivation

**Files:**
- Create: `src/context_service/auth/org_provisioning.py`
- Test: `tests/auth/test_org_provisioning.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_org_provisioning.py
"""Unit tests for self-serve org provisioning helpers."""

from __future__ import annotations

from context_service.auth.org_provisioning import resolve_workspace_name


class TestResolveWorkspaceName:
    def test_uses_full_name_when_present(self) -> None:
        assert resolve_workspace_name("Alice Example", "alice@x.com") == "Alice Example's workspace"

    def test_falls_back_to_email_local_part_when_name_missing(self) -> None:
        assert resolve_workspace_name(None, "alice@example.com") == "alice's workspace"

    def test_falls_back_when_name_is_blank(self) -> None:
        assert resolve_workspace_name("   ", "bob@example.com") == "bob's workspace"

    def test_strips_surrounding_whitespace_in_name(self) -> None:
        assert resolve_workspace_name("  Carol  ", "c@x.com") == "Carol's workspace"

    def test_neutral_default_when_no_name_and_no_local_part(self) -> None:
        assert resolve_workspace_name(None, "@example.com") == "New workspace"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group auth pytest tests/auth/test_org_provisioning.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'resolve_workspace_name'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/context_service/auth/org_provisioning.py
"""Self-serve organization provisioning.

When a user authenticates with no organization (typical of self-serve
signup via the hosted AuthKit UI), provision a personal
``"{name}'s workspace"`` org so every identity resolves to a real silo.

WorkOS calls use the lazily-imported ``workos`` SDK (the ``auth`` group), so
this module imports cleanly when that group is not installed.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


def resolve_workspace_name(name: str | None, email: str) -> str:
    """Derive a workspace name from the user's display name or email.

    Prefers the full name; falls back to the local-part of the email when no
    name is available (common for magic-link signups).
    """
    base = (name or "").strip() or email.split("@", 1)[0].strip()
    if not base:
        # No usable name and no email local-part (e.g. "@x.com"); neutral default.
        return "New workspace"
    return f"{base}'s workspace"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group auth pytest tests/auth/test_org_provisioning.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/auth/org_provisioning.py tests/auth/test_org_provisioning.py
git commit -m "feat(auth): add workspace-name derivation for org provisioning"
```

---

## Task 2: Idempotent WorkOS org + membership creation

**Files:**
- Modify: `src/context_service/auth/org_provisioning.py`
- Test: `tests/auth/test_org_provisioning.py`

Idempotency and concurrency, keyed on `external_id = workos_user_id`:
- If `get_organization_by_external_id` finds an org, reuse it **and re-ensure the membership exists** (repairs a prior partial failure where the org was created but the membership call failed). Do not assume membership is present.
- On `NotFoundError`, create the org. If a racing first-time login created it first, WorkOS rejects the duplicate `external_id` with `ConflictError` (HTTP 409, not `NotFoundError`) — catch it and re-fetch by external id to return the winner's org.
- Always (re)ensure the membership, tolerating an already-a-member conflict (`ConflictError`/`UnprocessableEntityError`).

This makes both a double-fired callback and two concurrent first-time logins safe, and guarantees the membership exists so AuthKit's single-org auto-scope (Fact #3) actually fires on the next login.

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_org_provisioning.py  (add imports + class)
import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from context_service.auth.org_provisioning import ensure_personal_org
from context_service.config.settings import Settings

_SETTINGS = Settings(
    _env_file=None,
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)


def _not_found() -> Exception:
    """Construct a real WorkOS NotFoundError (6.0.8 ctor treats a non-str first
    arg as the response object)."""
    from workos import NotFoundError

    return NotFoundError(MagicMock(headers={}, status_code=404, response_dict={"code": "not_found"}))


def _conflict() -> Exception:
    """Construct a real WorkOS ConflictError (HTTP 409 duplicate external_id)."""
    from workos import ConflictError

    return ConflictError(MagicMock(headers={}, status_code=409, response_dict={"code": "conflict"}))


def _make_client() -> MagicMock:
    """A bare WorkOS client mock; tests wire specific side effects."""
    client = MagicMock()
    return client


def _wrap(client: MagicMock) -> MagicMock:
    from workos import ConflictError, NotFoundError, UnprocessableEntityError

    mod = MagicMock()
    mod.WorkOSClient.return_value = client
    mod.NotFoundError = NotFoundError
    mod.ConflictError = ConflictError
    mod.UnprocessableEntityError = UnprocessableEntityError
    return mod


class TestEnsurePersonalOrg:
    def test_creates_org_and_membership_when_none_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
        client = _make_client()
        client.organizations.get_organization_by_external_id.side_effect = _not_found()
        created = MagicMock()
        created.id = "org-new"
        client.organizations.create_organization.return_value = created

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")

        assert org_id == "org-new"
        _, kwargs = client.organizations.create_organization.call_args
        assert kwargs["name"] == "Alice's workspace"
        assert kwargs["external_id"] == "wos-user-1"
        assert kwargs["metadata"] == {"source": "self-serve-signup"}
        client.user_management.create_organization_membership.assert_called_once_with(
            user_id="wos-user-1", organization_id="org-new"
        )

    def test_reuses_existing_org_and_repairs_membership(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B2: reuse path must (re)ensure membership, not assume it exists."""
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
        client = _make_client()
        found = MagicMock()
        found.id = "org-existing"
        client.organizations.get_organization_by_external_id.return_value = found

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")

        assert org_id == "org-existing"
        client.organizations.create_organization.assert_not_called()
        # membership is (re)ensured on the reuse path
        client.user_management.create_organization_membership.assert_called_once_with(
            user_id="wos-user-1", organization_id="org-existing"
        )

    def test_tolerates_already_a_member_conflict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B2: an already-a-member ConflictError on the membership call is swallowed."""
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
        client = _make_client()
        found = MagicMock()
        found.id = "org-existing"
        client.organizations.get_organization_by_external_id.return_value = found
        client.user_management.create_organization_membership.side_effect = _conflict()

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")  # must not raise

        assert org_id == "org-existing"

    def test_create_conflict_refetches_race_winner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B3: a duplicate-external_id ConflictError on create -> re-fetch and reuse."""
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
        client = _make_client()
        winner = MagicMock()
        winner.id = "org-winner"
        # First lookup: not found (we proceed to create). Second lookup (after the
        # create conflict): the racing winner's org.
        client.organizations.get_organization_by_external_id.side_effect = [
            _not_found(),
            winner,
        ]
        client.organizations.create_organization.side_effect = _conflict()

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")

        assert org_id == "org-winner"
        client.user_management.create_organization_membership.assert_called_once_with(
            user_id="wos-user-1", organization_id="org-winner"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group auth pytest tests/auth/test_org_provisioning.py::TestEnsurePersonalOrg -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_personal_org'`. (If a WorkOS error constructor signature differs in 6.0.8, adjust `_not_found`/`_conflict`; production code depends only on the class identities.)

- [ ] **Step 3: Write minimal implementation**

Add to `src/context_service/auth/org_provisioning.py`:

```python
from typing import Any

from context_service.config.settings import get_settings

_ORG_METADATA = {"source": "self-serve-signup"}


def _build_workos_client() -> Any:
    """Construct a WorkOS client from settings (matches existing auth helpers)."""
    import workos  # lazy: optional `auth` group

    settings = get_settings()
    api_key = settings.workos_api_key.get_secret_value() if settings.workos_api_key else None
    if api_key is None:
        raise ValueError("WORKOS_API_KEY must be configured for org provisioning")
    if not settings.workos_client_id:
        raise ValueError("WORKOS_CLIENT_ID must be configured for org provisioning")
    return workos.WorkOSClient(api_key=api_key, client_id=settings.workos_client_id)


def _ensure_membership(client: Any, *, workos_user_id: str, organization_id: str) -> None:
    """Create the user's membership, tolerating an already-a-member conflict.

    Idempotent: a duplicate membership returns ConflictError (or
    UnprocessableEntityError on some WorkOS versions); both are treated as a
    no-op so re-running provisioning is safe and partial failures self-repair.
    """
    import workos

    try:
        client.user_management.create_organization_membership(
            user_id=workos_user_id,
            organization_id=organization_id,
        )
    except (workos.ConflictError, workos.UnprocessableEntityError):
        logger.info(
            "org_provisioning.membership_exists",
            org_id=organization_id,
            workos_user_id=workos_user_id,
        )


def ensure_personal_org(workos_user_id: str, workspace_name: str) -> str:
    """Return the id of the user's personal org, creating it if absent.

    Idempotent and concurrency-safe, keyed on ``external_id == workos_user_id``:
      - If an org with that external id already exists, reuse it and re-ensure
        the membership (repairs a prior org-created-but-membership-failed state).
      - Otherwise create the org. If a racing request created it first, WorkOS
        rejects the duplicate external id with ConflictError; re-fetch and reuse.
      - Always (re)ensure the membership.
    """
    import workos

    client = _build_workos_client()

    try:
        existing = client.organizations.get_organization_by_external_id(workos_user_id)
        org_id = str(existing.id)
        _ensure_membership(client, workos_user_id=workos_user_id, organization_id=org_id)
        logger.info("org_provisioning.reuse_existing", org_id=org_id, workos_user_id=workos_user_id)
        return org_id
    except workos.NotFoundError:
        pass

    try:
        org = client.organizations.create_organization(
            name=workspace_name,
            external_id=workos_user_id,
            metadata=_ORG_METADATA,
        )
        org_id = str(org.id)
        logger.info("org_provisioning.created", org_id=org_id, workos_user_id=workos_user_id)
    except workos.ConflictError:
        # Lost a race: another request already created the org for this external id.
        existing = client.organizations.get_organization_by_external_id(workos_user_id)
        org_id = str(existing.id)
        logger.info("org_provisioning.create_race_resolved", org_id=org_id, workos_user_id=workos_user_id)

    _ensure_membership(client, workos_user_id=workos_user_id, organization_id=org_id)
    return org_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group auth pytest tests/auth/test_org_provisioning.py::TestEnsurePersonalOrg -v`
Expected: PASS (4 passed) — create, reuse-repairs-membership, tolerate-already-member, and create-conflict-refetch.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/auth/org_provisioning.py tests/auth/test_org_provisioning.py
git commit -m "feat(auth): idempotent personal-org creation via WorkOS external_id"
```

---

## Task 3: Precedence resolver `resolve_or_create_org`

**Files:**
- Modify: `src/context_service/auth/org_provisioning.py`
- Test: `tests/auth/test_org_provisioning.py`

Precedence: **session `org_id` -> stored user `org_id` (real, not the legacy user-id fallback) -> create**. Only the last branch hits WorkOS. The legacy-fallback guard (`stored.org_id != workos_user_id`) ensures any user written by the old code gets a real org on next auth.

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_org_provisioning.py  (add)
from unittest.mock import AsyncMock

from context_service.auth.org_provisioning import resolve_or_create_org


class TestResolveOrCreateOrg:
    async def test_returns_session_org_id_without_db_or_workos(self) -> None:
        session = AsyncMock()
        with patch("context_service.auth.org_provisioning.ensure_personal_org") as ensure:
            result = await resolve_or_create_org(
                session,
                workos_user_id="wos-1",
                session_org_id="org-from-session",
                name="Alice",
                email="alice@x.com",
            )
        assert result == "org-from-session"
        ensure.assert_not_called()

    async def test_returns_stored_org_id_when_session_has_none(self) -> None:
        stored = MagicMock()
        stored.org_id = "org-stored"
        session = AsyncMock()
        with (
            patch("context_service.auth.org_provisioning.UserService") as MockSvc,
            patch("context_service.auth.org_provisioning.ensure_personal_org") as ensure,
        ):
            MockSvc.return_value.get_user_by_workos_id = AsyncMock(return_value=stored)
            result = await resolve_or_create_org(
                session, workos_user_id="wos-1", session_org_id=None, name="Alice", email="a@x.com"
            )
        assert result == "org-stored"
        ensure.assert_not_called()

    async def test_creates_when_no_session_and_no_stored_org(self) -> None:
        session = AsyncMock()
        with (
            patch("context_service.auth.org_provisioning.UserService") as MockSvc,
            patch(
                "context_service.auth.org_provisioning.ensure_personal_org",
                return_value="org-new",
            ) as ensure,
        ):
            MockSvc.return_value.get_user_by_workos_id = AsyncMock(return_value=None)
            result = await resolve_or_create_org(
                session, workos_user_id="wos-1", session_org_id=None, name=None, email="bob@x.com"
            )
        assert result == "org-new"
        ensure.assert_called_once_with("wos-1", "bob's workspace")

    async def test_creates_when_stored_org_is_legacy_userid_fallback(self) -> None:
        stored = MagicMock()
        stored.org_id = "wos-1"  # legacy fallback wrote org_id == workos_user_id
        session = AsyncMock()
        with (
            patch("context_service.auth.org_provisioning.UserService") as MockSvc,
            patch(
                "context_service.auth.org_provisioning.ensure_personal_org",
                return_value="org-new",
            ) as ensure,
        ):
            MockSvc.return_value.get_user_by_workos_id = AsyncMock(return_value=stored)
            result = await resolve_or_create_org(
                session, workos_user_id="wos-1", session_org_id=None, name="Al", email="al@x.com"
            )
        assert result == "org-new"
        ensure.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group auth pytest tests/auth/test_org_provisioning.py::TestResolveOrCreateOrg -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_or_create_org'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/context_service/auth/org_provisioning.py`:

```python
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.services.user import UserService


async def resolve_or_create_org(
    session: AsyncSession,
    *,
    workos_user_id: str,
    session_org_id: str | None,
    name: str | None,
    email: str,
) -> str:
    """Resolve the effective org id for an identity, provisioning if needed.

    Precedence:
      1. The org id carried by the current session/token, if any.
      2. The org id already stored on the user record (fast indexed read) -
         unless it equals the workos_user_id, which marks a legacy user-id
         fallback that should be upgraded to a real org.
      3. A newly-created personal org (the only branch that calls WorkOS).
    """
    if session_org_id:
        return session_org_id

    user = await UserService(session).get_user_by_workos_id(workos_user_id)
    if user is not None and user.org_id and user.org_id != workos_user_id:
        return str(user.org_id)

    return ensure_personal_org(workos_user_id, resolve_workspace_name(name, email))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group auth pytest tests/auth/test_org_provisioning.py::TestResolveOrCreateOrg -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/auth/org_provisioning.py tests/auth/test_org_provisioning.py
git commit -m "feat(auth): precedence resolver for effective org id"
```

---

## Task 4: Surface `name` from `exchange_code_for_user`

**Files:**
- Modify: `src/context_service/auth/workos_authkit.py:53-95`
- Test: `tests/integration/test_auth_workos.py` (add a focused test) or a new `tests/auth/test_exchange_code_name.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/auth/test_exchange_code_name.py
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from context_service.auth.workos_authkit import exchange_code_for_user
from context_service.config.settings import Settings

_SETTINGS = Settings(
    _env_file=None,
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)


def _fake_workos(first: str | None, last: str | None) -> MagicMock:
    user = MagicMock()
    user.id = "wos-user-1"
    user.email = "alice@example.com"
    user.first_name = first
    user.last_name = last
    resp = MagicMock()
    resp.user = user
    resp.organization_id = None
    client = MagicMock()
    client.user_management.authenticate_with_code.return_value = resp
    mod = MagicMock()
    mod.WorkOSClient.return_value = client
    return mod


@pytest.mark.asyncio
async def test_exchange_returns_joined_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("context_service.auth.workos_authkit.get_settings", lambda: _SETTINGS)
    with patch.dict(sys.modules, {"workos": _fake_workos("Alice", "Example")}):
        info = await exchange_code_for_user("code-123")
    assert info["name"] == "Alice Example"
    assert info["organization_id"] is None


@pytest.mark.asyncio
async def test_exchange_name_is_none_when_no_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("context_service.auth.workos_authkit.get_settings", lambda: _SETTINGS)
    with patch.dict(sys.modules, {"workos": _fake_workos(None, None)}):
        info = await exchange_code_for_user("code-123")
    assert info["name"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group auth pytest tests/auth/test_exchange_code_name.py -v`
Expected: FAIL — `KeyError: 'name'`.

- [ ] **Step 3: Write minimal implementation**

In `src/context_service/auth/workos_authkit.py`, replace the return block (currently lines 79-95) with:

```python
    user: Any = response.user
    if user is None:
        raise ValueError("WorkOS code exchange response missing user")

    org_id: str | None = response.organization_id
    full_name: str | None = (
        " ".join(filter(None, [user.first_name, user.last_name])) or None
    )

    logger.info(
        "workos_authkit_exchange_success",
        user_id=user.id,
        organization_id=org_id,
    )

    return {
        "id": user.id,
        "email": user.email,
        "organization_id": org_id,
        "name": full_name,
    }
```

Also update the docstring line "Returns a dict with keys: id, email, organization_id." to "Returns a dict with keys: id, email, organization_id, name."

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group auth pytest tests/auth/test_exchange_code_name.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/auth/workos_authkit.py tests/auth/test_exchange_code_name.py
git commit -m "feat(auth): surface user name from WorkOS code exchange"
```

---

## Task 5: Persist `org_id`/`silo_id` on user upsert conflict

**Files:**
- Modify: `src/context_service/services/user.py:54-61`
- Test: `tests/services/test_user.py`

**Why (fixes B1):** `upsert_user`'s `on_conflict_do_update` currently sets only `{last_active_at, email, name}`. For a returning user it never rewrites `org_id`/`silo_id`. That breaks the legacy-fallback upgrade: the resolver (Task 3) computes the real org, but the DB row keeps `org_id == workos_user_id`, so every subsequent request re-triggers the legacy guard and pays another WorkOS round-trip, and the row carries a wrong user-keyed silo. Persisting these on conflict makes the upgrade stick after one auth.

Multi-org note: a user legitimately in multiple orgs would have their row's `org_id` reflect their most recent session's org. That matches how `silo_id` is already derived per-session today and is within the existing flat-silo scope; not a regression.

- [ ] **Step 1: Write the failing test**

```python
# tests/services/test_user.py  (add)
from sqlalchemy.dialects import postgresql


@pytest.mark.asyncio
async def test_upsert_persists_org_and_silo_on_conflict(
    service: UserService, session: AsyncMock
) -> None:
    """The ON CONFLICT DO UPDATE clause must rewrite org_id and silo_id."""
    user = _make_user()
    mock_result = MagicMock()
    mock_result.scalars.return_value.one.return_value = user
    session.execute.return_value = mock_result

    await service.upsert_user(
        workos_user_id=WORKOS_ID,
        org_id="org_new",
        silo_id="silo_new",
        email=EMAIL,
        name=NAME,
    )

    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    on_conflict = sql.split("ON CONFLICT", 1)[1]
    assert "org_id" in on_conflict
    assert "silo_id" in on_conflict
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group auth pytest tests/services/test_user.py::test_upsert_persists_org_and_silo_on_conflict -v`
Expected: FAIL — `org_id`/`silo_id` are not in the `ON CONFLICT DO UPDATE SET` clause.

- [ ] **Step 3: Write minimal implementation**

In `src/context_service/services/user.py`, update the `on_conflict_do_update` `set_` (currently lines 54-61) to include `org_id` and `silo_id`:

```python
            .on_conflict_do_update(
                index_elements=["workos_user_id"],
                set_={
                    "last_active_at": now,
                    "email": email,
                    "name": name,
                    "org_id": org_id,
                    "silo_id": silo_id,
                },
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group auth pytest tests/services/test_user.py -v`
Expected: PASS — new test passes; existing `upsert_user` tests unaffected (they assert on the returned user / that execute was awaited, not on the SET clause).

- [ ] **Step 5: Commit**

```bash
git add src/context_service/services/user.py tests/services/test_user.py
git commit -m "fix(user): persist org_id/silo_id on upsert conflict so org upgrades stick"
```

---

## Task 6: Wire resolver into `/oauth/callback` (both branches)

**Files:**
- Modify: `src/context_service/api/routes/oauth.py:287-313` (direct signup, `state is None`) and `:315-351` (MCP OAuth, `state` set)
- Test: `tests/integration/test_oauth_org_creation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_oauth_org_creation.py
"""Callback provisions a real org for no-org self-serve signup."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.api.routes.oauth import callback


@asynccontextmanager
async def _fake_session():  # type: ignore[return]
    yield AsyncMock()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_direct_signup_creates_org_when_user_has_none() -> None:
    user_info = {
        "id": "wos-user-1",
        "email": "alice@example.com",
        "organization_id": None,
        "name": "Alice Example",
    }
    with (
        patch(
            "context_service.api.routes.oauth.exchange_code_for_user",
            AsyncMock(return_value=user_info),
        ),
        patch("context_service.api.routes.oauth.get_session", _fake_session),
        patch(
            "context_service.api.routes.oauth.resolve_or_create_org",
            AsyncMock(return_value="org-new"),
        ) as resolve_mock,
        patch("context_service.api.routes.oauth.UserService") as MockSvc,
    ):
        MockSvc.return_value.upsert_user = AsyncMock(return_value=MagicMock())
        resp = await callback(code="code-1", state=None, error=None, error_description=None)

    resolve_mock.assert_awaited_once()
    kwargs = resolve_mock.await_args.kwargs
    assert kwargs["workos_user_id"] == "wos-user-1"
    assert kwargs["session_org_id"] is None
    assert kwargs["name"] == "Alice Example"
    # upsert receives the real org id and a silo derived from it (not the user id)
    upsert_kwargs = MockSvc.return_value.upsert_user.await_args.kwargs
    assert upsert_kwargs["org_id"] == "org-new"
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group auth pytest tests/integration/test_oauth_org_creation.py -v`
Expected: FAIL — `AttributeError`/`ImportError`: `resolve_or_create_org` is not imported in `oauth.py` yet.

- [ ] **Step 3: Write minimal implementation**

In `src/context_service/api/routes/oauth.py`, add the import near the other auth imports at the top of the file:

```python
from context_service.auth.org_provisioning import resolve_or_create_org
```

Replace the direct-signup body (currently `oauth.py:295-310`) with:

```python
        async with get_session() as session:
            from context_service.services.models import derive_silo_id

            workos_user_id: str = user_info["id"]
            email: str = user_info.get("email", "")
            name: str | None = user_info.get("name")
            session_org_id: str | None = user_info.get("organization_id")

            effective_org_id = await resolve_or_create_org(
                session,
                workos_user_id=workos_user_id,
                session_org_id=session_org_id,
                name=name,
                email=email,
            )
            silo_id = str(derive_silo_id(effective_org_id))

            user_svc = UserService(session)
            await user_svc.upsert_user(
                workos_user_id=workos_user_id,
                org_id=effective_org_id,
                silo_id=silo_id,
                email=email,
                name=name,
            )
```

Replace the MCP-OAuth branch body (currently `oauth.py:336-351`) with:

```python
        workos_user_id = user_info["id"]
        email = user_info.get("email", "")
        name = user_info.get("name")
        session_org_id = user_info.get("organization_id")

        from context_service.services.models import derive_silo_id

        effective_org_id = await resolve_or_create_org(
            session,
            workos_user_id=workos_user_id,
            session_org_id=session_org_id,
            name=name,
            email=email,
        )
        silo_id = str(derive_silo_id(effective_org_id))

        user_svc = UserService(session)
        db_user = await user_svc.upsert_user(
            workos_user_id=workos_user_id,
            org_id=effective_org_id,
            silo_id=silo_id,
            email=email,
            name=name,
        )
```

Note: both branches now pass `name=` to `upsert_user` (previously omitted). This is consistent with `verify_session`, which already passes the joined name.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --group auth pytest tests/integration/test_oauth_org_creation.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the existing oauth tests to check for regressions**

Run: `uv run --group auth pytest tests/integration/test_oauth.py -v`
Expected: PASS (existing behavior with a real `organization_id` still routes through the `session_org_id` short-circuit unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/context_service/api/routes/oauth.py tests/integration/test_oauth_org_creation.py
git commit -m "feat(auth): provision personal org in oauth callback for no-org signup"
```

---

## Task 7: Wire resolver into `verify_session` (preserve fail-open)

**Files:**
- Modify: `src/context_service/auth/workos_client.py:61-99`
- Test: extend `tests/integration/test_auth_user_sync.py`

Behavior change: when `response.organization_id` is `None`, resolve/create instead of raising. The `AuthContext.org_id` must be the **effective** org id. Preserve the Postgres fail-open path for users who already have an org; fail *closed* only when a genuinely-new no-org user cannot be provisioned (no DB session / WorkOS create failed), since `derive_silo_id(None)` is invalid.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_auth_user_sync.py  (add to TestAuthUserSync)

    async def test_verify_session_provisions_org_when_session_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No-org sealed session should provision an org, not raise."""
        monkeypatch.setattr(
            "context_service.auth.workos_client.get_settings", lambda: _WORKOS_SETTINGS
        )

        fake_db_user = _make_fake_db_user()
        session_mock = AsyncMock()
        upsert_mock = AsyncMock(return_value=fake_db_user)

        # session response WITHOUT an organization_id
        no_org_response = _make_workos_response()
        no_org_response.organization_id = None
        fake_workos = _make_workos_module(no_org_response)

        with (
            patch.dict(sys.modules, {"workos": fake_workos}),
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_get_session(session_mock),
            ),
            patch(
                "context_service.services.user.UserService",
            ) as MockUserService,
            patch(
                "context_service.auth.workos_client.resolve_or_create_org",
                AsyncMock(return_value="org-provisioned"),
            ) as resolve_mock,
        ):
            MockUserService.return_value.upsert_user = upsert_mock
            ctx = await verify_session("sealed-token-no-org")

        resolve_mock.assert_awaited_once()
        assert ctx.org_id == "org-provisioned"
        assert upsert_mock.await_args.kwargs["org_id"] == "org-provisioned"
```

Confirm the existing `test_verify_session_fail_open_on_postgres_error` (org_id present) is unchanged and still expected to pass.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --group auth pytest tests/integration/test_auth_user_sync.py::TestAuthUserSync::test_verify_session_provisions_org_when_session_has_none -v`
Expected: FAIL — currently `verify_session` raises `ValueError("WorkOS session response missing organization_id")`.

- [ ] **Step 3: Write minimal implementation**

In `src/context_service/auth/workos_client.py`, add the import at the top with the other auth imports:

```python
from context_service.auth.org_provisioning import resolve_or_create_org
```

Replace the block from the `org_id` read through the `return AuthContext(...)` (currently lines 61-99) with:

```python
    session_org_id = response.organization_id

    first_name: str | None = user.get("first_name")
    last_name: str | None = user.get("last_name")
    full_name: str | None = " ".join(filter(None, [first_name, last_name])) or None
    email = user.get("email", "")

    db_user_id: UUID | None = None
    effective_org_id: str | None = session_org_id
    try:
        from context_service.db.postgres import get_session
        from context_service.services.models import derive_silo_id
        from context_service.services.user import UserService

        async with get_session() as session:
            effective_org_id = await resolve_or_create_org(
                session,
                workos_user_id=user["id"],
                session_org_id=session_org_id,
                name=full_name,
                email=email,
            )
            user_service = UserService(session)
            db_user = await user_service.upsert_user(
                workos_user_id=user["id"],
                org_id=effective_org_id,
                silo_id=str(derive_silo_id(effective_org_id)),
                email=email,
                name=full_name,
            )
            db_user_id = db_user.id
            await session.commit()
    except Exception as exc:
        logger.warning(
            "user_upsert_failed",
            error=str(exc),
            workos_user_id=user["id"],
        )

    # Fail open only when the user already had an org (existing contract).
    # A genuinely-new no-org user that could not be provisioned cannot get a
    # valid silo, so fail closed rather than emit a None org id.
    if effective_org_id is None:
        raise ValueError("Could not resolve or provision an organization for the user")

    return AuthContext(
        org_id=effective_org_id,
        user_id=user["id"],
        email=email,
        is_dev=False,
        db_user_id=db_user_id,
    )
```

- [ ] **Step 4: Run the new and existing verify_session tests**

Run: `uv run --group auth pytest tests/integration/test_auth_user_sync.py -v`
Expected: PASS — new provisioning test passes; the four existing tests (including `test_verify_session_fail_open_on_postgres_error`, which has `organization_id` set so `effective_org_id` stays non-None through the fail-open path) still pass.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/auth/workos_client.py tests/integration/test_auth_user_sync.py
git commit -m "feat(auth): provision org in verify_session instead of rejecting no-org users"
```

---

## Task 8: Full check + staging cleanup (manual/ops)

**Files:** none (verification + ops). No code changes.

- [ ] **Step 1: Run lint + typecheck + full test suite**

Run: `uv run --group auth just check && uv run --group auth just test -k "org_provisioning or oauth or auth_user_sync or exchange_code"`
Expected: ruff + mypy strict clean; targeted tests green. Then run the full `just ci` before opening the PR.

- [ ] **Step 2: Staging data cleanup (one-time, manual)**

Any user created under the old code has `org_id == workos_user_id` and a silo keyed to the user id. The legacy-fallback guard in Task 3 upgrades them to a real org on next auth, but their pre-existing nodes stay in the old user-keyed silo (orphaned). For the staging event, the simplest correct action is to **wipe staging user/silo data before the event** so everyone starts clean. Coordinate with the owner; do not run destructive operations without confirmation. Record the decision in the PR description.

- [ ] **Step 3: WorkOS staging dashboard (manual, owner)**

Reduce signup friction independent of this code:
- Enable **magic link** and/or **Google** under staging Authentication (avoid forcing passwords on phones at the event).
- Confirm public sign-ups are allowed.
- Confirm the staging **Redirects** list contains the `/oauth/callback` issuer URL (and a tunnel URL if testing phone scanning against a local instance).

- [ ] **Step 4: Open PR (never commit to main)**

```bash
git switch -c feat/self-serve-org-provisioning
git push -u origin feat/self-serve-org-provisioning
gh pr create --fill
```

---

## Open Decisions / Notes

- **Membership role:** the plan omits `role` on `create_organization_membership`, so the user gets the org's default role. If your authz ever checks for an `admin`/owner role on the workspace creator, pass `role={"slug": "admin"}` (confirm the exact `RoleSingle` shape against `workos==6.0.8`) in `ensure_personal_org`. Out of scope until authz needs it.
- **Sync WorkOS calls in async context:** `ensure_personal_org` makes blocking SDK calls inside async functions, matching the existing pattern in `workos_authkit.py`/`workos_client.py`. Acceptable here because provisioning runs once per new user, not on the hot path. If it ever moves onto a hot path, wrap in `anyio.to_thread.run_sync`.
- **Event-signup metric:** every provisioned org carries `metadata={"source": "self-serve-signup"}`. This lets you count event signups via the WorkOS organizations list, which ties to the Antler closed-beta / waitlist KPIs.
- **No success-page change:** confirmed out of scope; the existing CTA to `docs.engrammic.ai/quickstart` is the intended conversion handoff.
- **Other auth paths carry the same fallback (N1/N2, out of scope).** `mcp/server.py` has the identical "no real org" pattern in two spots: the API-key path (`org_id = getattr(owner, "organization_id", None) or owner.id`) and `_resolve_oauth_token` (reads `user.org_id` straight from the row with no legacy guard). The QR/event flow is sealed-session/OAuth-callback, so these are not on the event path. Task 5 transitively fixes the OAuth-token row read (the row now holds a real org after one auth). Call both out in the PR description as known remaining inconsistencies to clean up post-event; do not expand scope here.

---

## Self-Review

- **Spec coverage:** no-org rejection bug (Tasks 3, 7), inconsistent callback fallback (Task 6), hot-path latency (Task 3 precedence + Task 5 persistence + Task 7 DB-first), name derivation incl. magic-link + empty-local-part fallback (Tasks 1, 4), idempotency + concurrency/partial-failure safety (Task 2: membership repair, ConflictError refetch), legacy-upgrade persistence (Task 5, fixes B1), fail-open preservation (Task 7), legacy-fallback data orphaning (Task 8 cleanup), friction reduction (Task 8 dashboard), KPI metric (Task 2 metadata). All mapped.
- **Review fixes folded in:** B1 (Task 5), B2 membership repair + already-member tolerance (Task 2), B3 ConflictError race refetch (Task 2), N4 empty-local-part name (Task 1). N1/N2 (API-key and OAuth-token paths in `mcp/server.py` have the same fallback) are noted in Open Decisions as known out-of-scope inconsistencies, transitively improved by Task 5.
- **Type consistency:** `resolve_or_create_org(session, *, workos_user_id, session_org_id, name, email) -> str`, `ensure_personal_org(workos_user_id, workspace_name) -> str`, `_ensure_membership(client, *, workos_user_id, organization_id) -> None`, `resolve_workspace_name(name, email) -> str`, and `exchange_code_for_user(...) -> {id,email,organization_id,name}` are used identically across Tasks 1-7.
- **Placeholders:** none — every code step shows full content; the one tunable (membership role) is explicitly deferred in Open Decisions.
