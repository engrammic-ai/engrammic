"""Embedded public key for license validation."""

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAP6oGZYYU9c8ZmbH5npbIPMpQ041S/AnGBBwFc+xX9m0=
-----END PUBLIC KEY-----
"""


def get_public_key_pem() -> str:
    """Return the embedded public key PEM."""
    return PUBLIC_KEY_PEM.strip()
