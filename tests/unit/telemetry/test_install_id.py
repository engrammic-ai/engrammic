import tempfile
from pathlib import Path

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
