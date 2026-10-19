from .models import UserProfile
from django.contrib.auth.models import User
from unittest import mock
from django.db import OperationalError, connections
from django.test import TestCase, override_settings
from django.urls import reverse

# Unit test to show that the model is storing the data it should
class UserProfileModelTest(TestCase):
    def test_create_user_profile(self):
        user = User.objects.create_user(username="testuser", password="password123")
        profile = UserProfile.objects.create(user =user, age = 22, weight = 222.22)
        self.assertEqual(profile.user.username , "testuser")
        self.assertEqual(profile.age , 22)
        self.assertEqual(profile.weight , 222.22)


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


# User story D-1: pages that need a login (plans and history are private to each user)
class OnboardingAndProfileAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ownerbob', 'bob@example.com', 'Tr4ining-Plan-2026!')
        self.other = User.objects.create_user('strangeralice', 'alice@example.com', 'Tr4ining-Plan-2026!')
        UserProfile.objects.create(user=self.user, age=30, weight='180.50')
        UserProfile.objects.create(user=self.other, age=41, weight='222.22')

    def test_onboarding_requires_login(self):
        response = self.client.get(reverse('onboarding'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('onboarding')}")

    def test_onboarding_available_when_logged_in(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('onboarding')).status_code, 200)

    def test_profile_page_requires_login(self):
        response = self.client.get(reverse('user_profile'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('user_profile')}")

    def test_profile_page_only_shows_own_profile(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('user_profile'))
        self.assertContains(response, 'ownerbob')
        self.assertNotContains(response, 'strangeralice')