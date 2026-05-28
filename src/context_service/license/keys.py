"""Embedded public key for license validation."""

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAhBOyf9EQFrXkTJh+YuLFZKcp4Bd9HPNXRfe9BBunhwM=
-----END PUBLIC KEY-----
"""


def get_public_key_pem() -> str:
    """Return the embedded public key PEM."""
    return PUBLIC_KEY_PEM.strip()
