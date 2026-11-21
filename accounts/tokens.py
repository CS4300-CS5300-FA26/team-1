"""Signed, expiring tokens for email confirmation links (ADR-018).

Built on Django's PasswordResetTokenGenerator, with its own salt so a confirmation token can never be used as a
password reset token, or the other way round. Tokens expire after settings.PASSWORD_RESET_TIMEOUT.
"""

from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = 'fitpro.accounts.tokens.EmailVerificationTokenGenerator'

    def _make_hash_value(self, user, timestamp):
        # is_active turns True when the email is confirmed, so a used link stops working; a changed email does too.
        return f'{user.pk}{user.is_active}{user.email}{timestamp}'


email_verification_token = EmailVerificationTokenGenerator()
