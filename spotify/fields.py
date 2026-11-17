"""A text field that is encrypted at rest with Fernet (AES-128-CBC plus HMAC-SHA256)."""

import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from .config import encryption_keys

logger = logging.getLogger('spotify')


def _fernet() -> MultiFernet:
    keys = encryption_keys()
    if not keys:
        raise ImproperlyConfigured('SPOTIFY_TOKEN_ENCRYPTION_KEY is not set, so Spotify tokens cannot be stored.')
    return MultiFernet([Fernet(key) for key in keys])


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored value. A value no configured key can read comes back empty, so the caller asks to relink."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.warning('A stored Spotify token could not be decrypted; was SPOTIFY_TOKEN_ENCRYPTION_KEY changed?')
        return ''


class EncryptedTextField(models.TextField):
    """Stores ciphertext in the database and gives Python code the plaintext.

    Encryption is randomized, so the column can't be filtered on; it only ever holds secrets read by primary key.
    An empty string is stored as-is, meaning "no token".
    """

    def from_db_value(self, value, expression, connection):
        if value in (None, ''):
            return value
        return decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ''):
            return value
        return encrypt(value)
