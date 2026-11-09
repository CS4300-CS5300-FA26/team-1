"""Token helper, encryption at rest, configuration, and the Spotify HTTP client (story D-7, ADR-010)."""

from datetime import timedelta
from unittest import mock

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, connection, transaction
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings
from django.utils import timezone

from . import client, config, services
from .fields import encrypt
from .models import SpotifyAccount
from .testing import TEST_SETTINGS, UNCONFIGURED_SETTINGS, FakeSpotify

User = get_user_model()


def raw_column(account: SpotifyAccount, column: str) -> str:
    """What is actually stored in the database, bypassing the field's decryption."""
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT {column} FROM spotify_spotifyaccount WHERE id = %s', [account.pk])  # noqa: S608
        return cursor.fetchone()[0]


@override_settings(**TEST_SETTINGS)
class SpotifyTestCase(TestCase):
    def setUp(self):
        self.spotify = self.enterContext(FakeSpotify().installed())
        self.user = User.objects.create_user('lifter', 'lifter@example.com', 'Tr4ining-Plan-2026!')

    def linked(self, expires_in_seconds=3600, **fields) -> SpotifyAccount:
        values = {
            'spotify_id': 'spotify-user-1',
            'display_name': 'DJ Lifts',
            'access_token': 'stored-access',
            'refresh_token': 'stored-refresh',
            'expires_at': timezone.now() + timedelta(seconds=expires_in_seconds),
            'scopes': 'user-read-private user-read-email',
        }
        values.update(fields)
        return SpotifyAccount.objects.create(user=self.user, **values)


class AccessTokenTests(SpotifyTestCase):
    def test_a_fresh_token_is_returned_without_calling_spotify(self):
        self.linked(expires_in_seconds=3600)
        self.assertEqual(services.get_access_token(self.user), 'stored-access')
        self.assertEqual(self.spotify.requests, [])

    def test_a_token_expiring_within_60_seconds_is_refreshed(self):
        self.linked(expires_in_seconds=59)
        token = services.get_access_token(self.user)

        self.assertEqual(token, 'access-1')
        [form] = self.spotify.grants('refresh_token')
        self.assertEqual(form['refresh_token'], ['stored-refresh'])
        account = SpotifyAccount.objects.get(user=self.user)
        self.assertEqual(account.access_token, 'access-1')
        assert account.expires_at is not None
        self.assertGreater(account.expires_at, timezone.now() + timedelta(minutes=59))

    def test_a_token_with_more_than_60_seconds_left_is_kept(self):
        self.linked(expires_in_seconds=90)
        self.assertEqual(services.get_access_token(self.user), 'stored-access')

    def test_the_refresh_token_is_kept_when_spotify_does_not_send_a_new_one(self):
        self.linked(expires_in_seconds=0)
        services.get_access_token(self.user)
        self.assertEqual(SpotifyAccount.objects.get(user=self.user).refresh_token, 'stored-refresh')

    def test_the_refresh_token_is_replaced_when_spotify_rotates_it(self):
        self.spotify.rotate_refresh_token = True
        self.linked(expires_in_seconds=0)
        services.get_access_token(self.user)
        self.assertEqual(SpotifyAccount.objects.get(user=self.user).refresh_token, 'refresh-1')

    def test_a_rejected_refresh_token_clears_tokens_and_sets_needs_relink(self):
        self.spotify.refresh_error = 'invalid_grant'
        self.linked(expires_in_seconds=0)

        with self.assertRaises(services.NeedsRelink):
            services.get_access_token(self.user)

        account = SpotifyAccount.objects.get(user=self.user)
        self.assertTrue(account.needs_relink)
        self.assertEqual((account.access_token, account.refresh_token, account.expires_at), ('', '', None))
        # The link itself stays, so the profile can offer "Reconnect Spotify".
        self.assertEqual(account.spotify_id, 'spotify-user-1')

    def test_needs_relink_stops_further_refresh_attempts(self):
        self.linked(expires_in_seconds=0, needs_relink=True)
        with self.assertRaises(services.NeedsRelink):
            services.get_access_token(self.user)
        self.assertEqual(self.spotify.requests, [])

    def test_spotify_being_down_is_not_mistaken_for_revoked_access(self):
        self.spotify.refresh_error = 'down'
        self.linked(expires_in_seconds=0)
        with self.assertRaises(client.SpotifyUnavailable):
            services.get_access_token(self.user)
        account = SpotifyAccount.objects.get(user=self.user)
        self.assertFalse(account.needs_relink)
        self.assertEqual(account.refresh_token, 'stored-refresh')

    def test_a_token_that_can_no_longer_be_decrypted_needs_relink(self):
        account = self.linked(expires_in_seconds=0)
        with (
            override_settings(SPOTIFY_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode()),
            self.assertLogs('spotify', 'WARNING'),
            self.assertRaises(services.NeedsRelink),
        ):
            services.get_access_token(self.user)
        account.refresh_from_db()
        self.assertTrue(account.needs_relink)
        self.assertEqual(self.spotify.requests, [])

    def test_no_linked_account(self):
        with self.assertRaises(services.NotLinked):
            services.get_access_token(self.user)

    def test_tokens_never_appear_in_logs(self):
        self.spotify.refresh_error = 'invalid_grant'
        self.linked(expires_in_seconds=0)
        with self.assertLogs('spotify', 'INFO') as logs, self.assertRaises(services.NeedsRelink):
            services.get_access_token(self.user)
        self.assertNotIn('stored-refresh', '\n'.join(logs.output))
        self.assertNotIn('stored-access', '\n'.join(logs.output))


class EncryptionAtRestTests(SpotifyTestCase):
    def test_tokens_are_encrypted_in_the_database(self):
        account = self.linked()
        for column, plaintext in (('refresh_token', 'stored-refresh'), ('access_token', 'stored-access')):
            stored = raw_column(account, column)
            self.assertNotIn(plaintext, stored)
            self.assertEqual(Fernet(TEST_SETTINGS['SPOTIFY_TOKEN_ENCRYPTION_KEY']).decrypt(stored).decode(), plaintext)

    def test_an_old_key_still_decrypts_during_a_rotation(self):
        old_key, new_key = TEST_SETTINGS['SPOTIFY_TOKEN_ENCRYPTION_KEY'], Fernet.generate_key().decode()
        account = self.linked()
        with override_settings(SPOTIFY_TOKEN_ENCRYPTION_KEY=f'{new_key},{old_key}'):
            account = SpotifyAccount.objects.get(pk=account.pk)
            self.assertEqual(account.refresh_token, 'stored-refresh')
            account.save()  # re-encrypted with the newest key
            Fernet(new_key).decrypt(raw_column(account, 'refresh_token'))

    def test_empty_tokens_are_stored_as_empty(self):
        account = self.linked(access_token='', refresh_token='')
        self.assertEqual(raw_column(account, 'refresh_token'), '')

    @override_settings(SPOTIFY_TOKEN_ENCRYPTION_KEY='')
    def test_storing_a_token_without_a_key_fails_loudly(self):
        with self.assertRaises(ImproperlyConfigured):
            encrypt('token')


class ConnectionStatusTests(SpotifyTestCase):
    def test_ok_calls_get_me_with_the_stored_token(self):
        self.linked()
        status = services.connection_status(self.user)
        self.assertEqual(status.state, 'ok')
        self.assertEqual(status.display_name, 'DJ Lifts')
        self.assertEqual(self.spotify.requests[0].get_header('Authorization'), 'Bearer stored-access')

    def test_a_new_display_name_is_saved(self):
        self.spotify.display_name = 'DJ Squats'
        self.linked()
        self.assertEqual(services.connection_status(self.user).display_name, 'DJ Squats')
        self.assertEqual(SpotifyAccount.objects.get(user=self.user).display_name, 'DJ Squats')

    def test_states_for_each_failure(self):
        self.assertEqual(services.connection_status(self.user).state, 'not_linked')
        account = self.linked(needs_relink=True)
        self.assertEqual(services.connection_status(self.user).state, 'needs_relink')
        account.needs_relink = False
        account.save()
        for error in ('down', 'offline', 'unauthorized'):
            self.spotify.me_error = error
            with self.subTest(error=error), self.assertLogs('spotify', 'WARNING'):
                self.assertEqual(services.connection_status(self.user).state, 'error')

    def test_a_token_for_another_spotify_user_is_an_error(self):
        self.spotify.user_id = 'someone-else'
        self.linked()
        with self.assertLogs('spotify', 'WARNING'):
            self.assertEqual(services.connection_status(self.user).state, 'error')


class ConfigTests(TestCase):
    @override_settings(**UNCONFIGURED_SETTINGS)
    def test_missing_settings_are_named(self):
        self.assertFalse(config.is_configured())
        with self.assertRaisesMessage(ImproperlyConfigured, 'SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET'):
            config.credentials()
        config.check_startup_config()  # nothing set: Spotify is simply off

    @override_settings(**{**TEST_SETTINGS, 'SPOTIFY_REDIRECT_URI': ''})
    def test_a_partial_configuration_stops_startup(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'SPOTIFY_REDIRECT_URI missing'):
            config.check_startup_config()

    @override_settings(**{**TEST_SETTINGS, 'SPOTIFY_TOKEN_ENCRYPTION_KEY': 'not-a-fernet-key'})
    def test_a_malformed_key_stops_startup(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'must be a Fernet key'):
            config.check_startup_config()

    def test_a_copy_of_env_example_starts_with_spotify_off(self):
        # The README says `cp .env.example .env`; that must give a working app, not a partial Spotify configuration.
        from django.conf import settings

        values = {}
        for line in (settings.BASE_DIR / '.env.example').read_text().splitlines():
            name, sep, value = line.partition('=')
            if sep and name in config.REQUIRED_SETTINGS:
                values[name] = value
        self.assertEqual(set(values), set(config.REQUIRED_SETTINGS))
        self.assertEqual(set(values.values()), {''})
        with override_settings(**values):
            config.check_startup_config()
            self.assertFalse(config.is_configured())

    @override_settings(**TEST_SETTINGS)
    def test_complete_configuration(self):
        config.check_startup_config()
        self.assertEqual(config.credentials().redirect_uri, 'http://testserver/auth-callback/spotify')


@override_settings(**TEST_SETTINGS)
class ClientTests(TestCase):
    def setUp(self):
        self.spotify = self.enterContext(FakeSpotify().installed())

    def test_exchange_sends_the_code_redirect_uri_and_client_credentials(self):
        tokens = client.exchange_code('the-code')
        request = self.spotify.requests[0]
        [form] = self.spotify.grants('authorization_code')
        self.assertEqual(form['code'], ['the-code'])
        self.assertEqual(form['redirect_uri'], ['http://testserver/auth-callback/spotify'])
        self.assertTrue(request.get_header('Authorization').startswith('Basic '))
        self.assertEqual(tokens.refresh_token, 'refresh-1')

    def test_tokens_are_hidden_from_repr(self):
        tokens = client.exchange_code('the-code')
        self.assertNotIn('access-1', repr(tokens))
        self.assertNotIn('refresh-1', repr(tokens))

    def test_errors_map_to_exceptions(self):
        cases = {
            'invalid_grant': client.InvalidGrant,
            'down': client.SpotifyUnavailable,
            'offline': client.SpotifyUnavailable,
        }
        for error, exception in cases.items():
            self.spotify.exchange_error = error
            with self.subTest(error=error), self.assertLogs('spotify', 'WARNING'), self.assertRaises(exception):
                client.exchange_code('the-code')

    def test_unexpected_bodies_are_errors(self):
        from unittest import mock

        from .testing import _Response

        for body in (b'not json', b'[]', b'{}'):
            with (
                self.subTest(body=body),
                mock.patch('spotify.client.urlopen', return_value=_Response(body)),
                self.assertRaises(client.SpotifyError),
            ):
                client.current_user('token')

    def test_an_exchange_without_a_refresh_token_is_an_error(self):
        from unittest import mock

        from .testing import _Response

        body = b'{"access_token": "a", "expires_in": 3600, "scope": ""}'
        with mock.patch('spotify.client.urlopen', return_value=_Response(body)), self.assertRaises(client.SpotifyError):
            client.exchange_code('the-code')

    def test_the_authorize_url_asks_for_every_scope(self):
        from urllib.parse import parse_qs, urlsplit

        from django.conf import settings

        query = parse_qs(urlsplit(client.authorize_url('the-state', settings.SPOTIFY_SCOPES)).query)
        self.assertEqual(query['response_type'], ['code'])
        self.assertEqual(query['state'], ['the-state'])
        self.assertEqual(query['client_id'], ['test-client-id'])
        self.assertEqual(query['scope'][0].split(), settings.SPOTIFY_SCOPES)
        self.assertNotIn('client_secret', query)


class OneAccountPerSpotifyIdTests(SpotifyTestCase):
    """A Spotify account can be linked to only one FitPro user, and a user to only one Spotify account.

    The rules are checked in spotify.services, but the database enforces them (unique indexes on spotify_id and
    user_id), so two requests racing past the checks still can't both win.
    """

    def setUp(self):
        super().setUp()
        self.other = User.objects.create_user('other', 'other@example.com', 'Tr4ining-Plan-2026!')
        self.profile = client.Profile(id='spotify-user-1', display_name='DJ Lifts', email='dj@example.com')
        self.tokens = client.Tokens(access_token='a', expires_in=3600, scope='', refresh_token='r')

    def test_the_database_rejects_a_spotify_id_linked_twice(self):
        self.linked()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SpotifyAccount.objects.create(user=self.other, spotify_id='spotify-user-1')

    def test_the_database_rejects_a_second_spotify_account_for_one_user(self):
        self.linked()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SpotifyAccount.objects.create(user=self.user, spotify_id='another-spotify-user')

    def test_linking_a_different_spotify_account_replaces_the_old_link(self):
        self.linked(spotify_id='old-spotify-user')
        services.link(self.user, self.profile, self.tokens)
        self.assertEqual(list(SpotifyAccount.objects.values_list('spotify_id', flat=True)), ['spotify-user-1'])

    def test_a_link_that_loses_a_race_is_refused_by_the_database(self):
        SpotifyAccount.objects.create(user=self.other, spotify_id='spotify-user-1')
        # Pretend both lookups ran before the other user's link was committed.
        with (
            mock.patch.object(QuerySet, 'first', return_value=None),
            self.assertRaises(services.SpotifyAccountError) as err,
        ):
            services.link(self.user, self.profile, self.tokens)
        self.assertEqual(str(err.exception), services.ALREADY_LINKED_ELSEWHERE)
        self.assertEqual(SpotifyAccount.objects.get(spotify_id='spotify-user-1').user, self.other)
        self.assertFalse(SpotifyAccount.objects.filter(user=self.user).exists())

    def assert_sign_up_race(self, expected_message, stale_checks=2):
        """Sign up as if the duplicate checks ran before another request committed; nothing may be left behind."""
        real_exists = QuerySet.exists
        calls = {'n': 0}

        def stale_then_real(qs):
            calls['n'] += 1
            return False if calls['n'] <= stale_checks else real_exists(qs)  # the pre-checks miss the other row

        users_before = User.objects.count()
        with (
            mock.patch.object(QuerySet, 'exists', stale_then_real),
            self.assertRaises(services.SpotifyAccountError) as err,
        ):
            services.sign_up(self.profile, self.tokens)
        self.assertEqual(str(err.exception), expected_message)
        self.assertEqual(User.objects.count(), users_before)  # rolled back, no half-made account

    def test_a_sign_up_that_loses_the_spotify_id_race_says_so(self):
        SpotifyAccount.objects.create(user=self.other, spotify_id='spotify-user-1')
        self.assert_sign_up_race(services.ALREADY_LINKED_FOR_SIGNUP)

    def test_a_sign_up_that_loses_the_email_race_says_so(self):
        User.objects.create_user('taken', 'dj@example.com')
        self.assert_sign_up_race(services.SIGNUP_REFUSED)

    def test_a_sign_up_that_loses_the_username_race_gets_the_same_generic_refusal(self):
        User.objects.create_user('dj-lifts', 'someone@example.com')
        # Spotify id, email, and username checks all ran before the other user was committed.
        self.assert_sign_up_race(services.SIGNUP_REFUSED, stale_checks=3)
