from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()
PASSWORD = 'correct-horse-battery-42'


class RegisterTests(TestCase):
    def test_register_page_renders(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create your account')

    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'ana',
            'email': 'Ana@Example.com',
            'password1': PASSWORD,
            'password2': PASSWORD,
        })
        self.assertRedirects(response, reverse('home'))
        user = User.objects.get(username='ana')
        self.assertEqual(user.email, 'ana@example.com')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_duplicate_email_rejected_case_insensitively(self):
        User.objects.create_user('bob', 'bob@example.com', PASSWORD)
        response = self.client.post(reverse('register'), {
            'username': 'bob2',
            'email': 'BOB@example.com',
            'password1': PASSWORD,
            'password2': PASSWORD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertFalse(User.objects.filter(username='bob2').exists())

    def test_password_mismatch_rejected(self):
        response = self.client.post(reverse('register'), {
            'username': 'cy',
            'email': 'cy@example.com',
            'password1': PASSWORD,
            'password2': 'something-else-entirely-1',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='cy').exists())

    def test_weak_password_rejected(self):
        response = self.client.post(reverse('register'), {
            'username': 'di',
            'email': 'di@example.com',
            'password1': '12345678',
            'password2': '12345678',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='di').exists())

    def test_logged_in_user_is_redirected_away(self):
        self.client.force_login(User.objects.create_user('ed', 'ed@example.com', PASSWORD))
        self.assertRedirects(self.client.get(reverse('register')), reverse('home'))


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('fay', 'fay@example.com', PASSWORD)

    def test_login_page_renders(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Log in')

    def test_login_success(self):
        response = self.client.post(reverse('login'), {'username': 'fay', 'password': PASSWORD})
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_login_wrong_password(self):
        response = self.client.post(reverse('login'), {'username': 'fay', 'password': 'nope'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_honours_safe_next(self):
        response = self.client.post(
            reverse('login'), {'username': 'fay', 'password': PASSWORD, 'next': '/admin/'},
        )
        self.assertRedirects(response, '/admin/', fetch_redirect_response=False)

    def test_login_ignores_external_next(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'fay', 'password': PASSWORD, 'next': 'https://evil.example.com/'},
        )
        self.assertRedirects(response, reverse('home'))

    def test_logout_requires_post_and_clears_session(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)