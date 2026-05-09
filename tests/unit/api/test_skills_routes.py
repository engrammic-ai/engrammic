"""Tests for skills REST routes."""

import pytest


def test_router_has_correct_prefix():
    """Router should have /api/skills prefix."""
    from context_service.api.routes.skills import router

    assert router.prefix == "/api/skills"


def test_routes_exist():
    """All expected routes should be registered."""
    from context_service.api.routes.skills import router

    paths = {route.path for route in router.routes}
    prefix = router.prefix
    assert prefix in paths or f"{prefix}/" in paths  # list/create
    assert f"{prefix}/search" in paths
    assert f"{prefix}/import" in paths
    assert f"{prefix}/{{name:path}}" in paths or f"{prefix}/{{name}}" in paths


def test_search_before_name_param():
    """Static routes /search and /import must appear before /{name:path}."""
    from context_service.api.routes.skills import router

    prefix = router.prefix
    route_paths = [route.path for route in router.routes]
    search_idx = next(i for i, p in enumerate(route_paths) if p == f"{prefix}/search")
    import_idx = next(i for i, p in enumerate(route_paths) if p == f"{prefix}/import")
    name_idx = next(i for i, p in enumerate(route_paths) if "name" in p)
    assert search_idx < name_idx
    assert import_idx < name_idx


def test_set_skill_service():
    """set_skill_service should update the module-level service."""
    from context_service.api.routes import skills

    dummy = object()
    skills.set_skill_service(dummy)
    assert skills._skill_service is dummy
    # Reset
    skills.set_skill_service(None)


def test_get_skill_service_raises_when_none():
    """_get_skill_service should raise RuntimeError when not configured."""
    from context_service.api.routes import skills

    skills._skill_service = None
    with pytest.raises(RuntimeError, match="SkillService not configured"):
        skills._get_skill_service()
