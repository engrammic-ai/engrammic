import tempfile
from pathlib import Path
from unittest.mock import patch

import context_service.telemetry.install_id as install_id_module
from context_service.telemetry.install_id import get_or_create_install_id


def test_creates_new_id_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "install_id"
        id1 = get_or_create_install_id(path)
        assert len(id1) == 36  # UUID format


def test_returns_existing_id():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "install_id"
        id1 = get_or_create_install_id(path)
        id2 = get_or_create_install_id(path)
        assert id1 == id2


def test_regenerates_if_deleted():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "install_id"
        id1 = get_or_create_install_id(path)
        path.unlink()
        id2 = get_or_create_install_id(path)
        assert id1 != id2


def test_fallback_to_ephemeral_on_permission_error():
    # Reset the global ephemeral ID
    install_id_module._EPHEMERAL_ID = None

    with (
        patch.object(Path, "exists", return_value=False),
        patch.object(Path, "parent", property(lambda self: self)),
        patch.object(Path, "mkdir", side_effect=OSError("Permission denied")),
    ):
        id1 = get_or_create_install_id(Path("/nonexistent/path"))
        assert len(id1) == 36  # UUID format

        # Should return same ephemeral ID on subsequent calls
        id2 = get_or_create_install_id(Path("/another/path"))
        assert id1 == id2
