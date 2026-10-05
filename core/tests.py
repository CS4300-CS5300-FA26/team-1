from django.test import TestCase
from .models import UserProfile
from django.contrib.auth.models import User

# TODO: Make an actual test - the spec says we need to actually test something, but this was nice to see the passing pipeline for now
class BasicTests(TestCase):
    def test_example(self):
        self.assertTrue(True)

# Unit test to show that the model is storing the data it should
class UserProfileModelTest(TestCase):
    def test_create_user_profile(self):
        user = User.objects.create_user(username="testuser", password="password123")
        profile = UserProfile.objects.create(user =user, age = 22, weight = 222.22)
        self.assertEqual(profile.user.username , "testuser")
        self.assertEqual(profile.age , 22)
        self.assertEqual(profile.weight , 222.22)
from unittest import mock

from django.db import OperationalError, connections
from django.test import TestCase, override_settings

# Probes from kubelet and the load balancer use the pod IP as the Host header.
POD_IP_HOST = '10.20.0.7:8000'


@override_settings(ALLOWED_HOSTS=['testserver'])
class HealthCheckTests(TestCase):
    def test_livez_ok_with_unknown_host(self):
        response = self.client.get('/livez/', HTTP_HOST=POD_IP_HOST)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok')

    def test_livez_does_not_touch_database(self):
        with mock.patch.object(connections['default'], 'cursor') as cursor:
            response = self.client.get('/livez/', HTTP_HOST=POD_IP_HOST)
        self.assertEqual(response.status_code, 200)
        cursor.assert_not_called()

    def test_healthz_ok_with_unknown_host(self):
        response = self.client.get('/healthz/', HTTP_HOST=POD_IP_HOST)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok')

    def test_healthz_503_when_database_fails(self):
        with mock.patch.object(connections['default'], 'cursor', side_effect=OperationalError('down')):
            with self.assertLogs('core.middleware', level='WARNING'):
                response = self.client.get('/healthz/', HTTP_HOST=POD_IP_HOST)
        self.assertEqual(response.status_code, 503)

    def test_other_paths_still_validate_host(self):
        with self.assertLogs('django.security.DisallowedHost', level='ERROR'):
            response = self.client.get('/admin/', HTTP_HOST=POD_IP_HOST)
        self.assertEqual(response.status_code, 400)


class HomePageTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<h1>FitPro</h1>')
