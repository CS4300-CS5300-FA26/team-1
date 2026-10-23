"""Tests for user story D-2: the onboarding questionnaire, the dashboard, and the login redirect.

The Gherkin scenarios for this story are in features/onboarding.feature.
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import UserProfile

PASSWORD = 'Correct-Horse-9'

# What a user types into the questionnaire (form POST data).
VALID_ANSWERS = {
    'goal': 'build_muscle',
    'height_inches': '70',
    'weight': '180.5',
    'experience_level': 'intermediate',
    'weekly_food_budget': '85.50',
    'equipment': ['dumbbells', 'bands'],
}

# The message each required field shows when left blank.
REQUIRED_MESSAGES = {
    'goal': 'Your goal is required.',
    'height_inches': 'Your height is required.',
    'weight': 'Your weight is required.',
    'experience_level': 'Your experience level is required.',
    'weekly_food_budget': 'Weekly food budget is required.',
    'equipment': 'Select at least one option for available equipment.',
}

# Model values for a user who has already finished onboarding.
COMPLETED_ANSWERS = {
    'goal': 'build_muscle',
    'height_inches': 70,
    'weight': Decimal('180.50'),
    'experience_level': 'intermediate',
    'weekly_food_budget': Decimal('85.50'),
    'equipment': ['dumbbells'],
}


class OnboardingTestBase(TestCase):
    def make_user(self, username='alice', completed=False, with_profile=True, **profile_fields):
        user = User.objects.create_user(
            username=username, email=f'{username}@example.com', password=PASSWORD,
        )
        if with_profile:
            UserProfile.objects.create(user=user, onboarding_completed=completed, **profile_fields)
        return user

    def make_completed_user(self, username='alice', **overrides):
        return self.make_user(username, completed=True, **{**COMPLETED_ANSWERS, **overrides})

    def log_in_as(self, user):
        self.client.force_login(user)

    def log_in_through_form(self, username, next_url=None):
        data = {'username': username, 'password': PASSWORD}
        if next_url:
            data['next'] = next_url
        return self.client.post(reverse('login'), data)


class CompleteOnboardingTests(OnboardingTestBase):
    """Scenario: Complete onboarding."""

    def test_valid_answers_are_saved_and_onboarding_marked_complete(self):
        user = self.make_user()
        self.log_in_as(user)

        response = self.client.post(reverse('onboarding'), VALID_ANSWERS)

        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        profile = UserProfile.objects.get(user=user)
        self.assertTrue(profile.onboarding_completed)
        self.assertEqual(profile.goal, 'build_muscle')
        self.assertEqual(profile.height_inches, 70)
        self.assertEqual(profile.weight, Decimal('180.50'))
        self.assertEqual(profile.experience_level, 'intermediate')
        self.assertEqual(profile.weekly_food_budget, Decimal('85.50'))
        self.assertCountEqual(profile.equipment, ['dumbbells', 'bands'])

    def test_user_ends_up_on_dashboard_showing_their_values(self):
        self.log_in_as(self.make_user())

        response = self.client.post(reverse('onboarding'), VALID_ANSWERS, follow=True)

        self.assertRedirects(response, reverse('dashboard'))
        self.assertContains(response, 'Your profile summary')
        self.assertContains(response, 'Build muscle')
        self.assertContains(response, '70 in')
        self.assertContains(response, '180.5')
        self.assertContains(response, 'Intermediate')
        self.assertContains(response, '$85.50')
        self.assertContains(response, 'Dumbbells')
        self.assertContains(response, 'Resistance bands')

    def test_zero_budget_is_accepted(self):
        user = self.make_user()
        self.log_in_as(user)

        response = self.client.post(
            reverse('onboarding'), {**VALID_ANSWERS, 'weekly_food_budget': '0'},
        )

        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(UserProfile.objects.get(user=user).weekly_food_budget, Decimal('0'))

    def test_height_and_weight_limits_are_inclusive(self):
        user = self.make_user()
        self.log_in_as(user)

        response = self.client.post(
            reverse('onboarding'), {**VALID_ANSWERS, 'height_inches': '96', 'weight': '50'},
        )

        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.height_inches, 96)
        self.assertEqual(profile.weight, Decimal('50'))

    def test_questionnaire_page_loads_for_incomplete_user(self):
        self.log_in_as(self.make_user())

        response = self.client.get(reverse('onboarding'))

        self.assertEqual(response.status_code, 200)
        for field in VALID_ANSWERS:
            self.assertIn(field, response.context['form'].fields)


class MissingAnswerTests(OnboardingTestBase):
    """Scenario: Missing required answer."""

    def test_missing_budget_shows_message_and_keeps_other_answers(self):
        user = self.make_user()
        self.log_in_as(user)

        response = self.client.post(
            reverse('onboarding'), {**VALID_ANSWERS, 'weekly_food_budget': ''},
        )

        self.assertEqual(response.status_code, 200)  # re-rendered, not redirected
        self.assertContains(response, 'Weekly food budget is required.')
        # The other answers are still filled in.
        form = response.context['form']
        self.assertEqual(form['goal'].value(), 'build_muscle')
        self.assertEqual(form['experience_level'].value(), 'intermediate')
        self.assertEqual(form['height_inches'].value(), '70')
        self.assertEqual(form['weight'].value(), '180.5')
        self.assertCountEqual(form['equipment'].value(), ['dumbbells', 'bands'])
        self.assertContains(response, 'value="70"')
        self.assertContains(response, 'value="180.5"')
        # Nothing was saved.
        profile = UserProfile.objects.get(user=user)
        self.assertFalse(profile.onboarding_completed)
        self.assertIsNone(profile.weekly_food_budget)

    def test_each_required_field_is_enforced_with_its_own_message(self):
        user = self.make_user()
        self.log_in_as(user)

        for field, message in REQUIRED_MESSAGES.items():
            with self.subTest(field=field):
                blank = [] if field == 'equipment' else ''
                response = self.client.post(reverse('onboarding'), {**VALID_ANSWERS, field: blank})

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.assertContains(response, message)
                self.assertFalse(UserProfile.objects.get(user=user).onboarding_completed)

    def test_invalid_values_are_rejected(self):
        user = self.make_user()
        self.log_in_as(user)
        invalid_values = [
            ('goal', 'fly'),
            ('experience_level', 'wizard'),
            ('height_inches', 'tall'),
            ('height_inches', '-5'),
            ('height_inches', '0'),
            ('height_inches', '35'),
            ('height_inches', '97'),
            ('weight', 'heavy'),
            ('weight', '-5'),
            ('weight', '0'),
            ('weight', '49.99'),
            ('weight', '700.01'),
            ('weekly_food_budget', 'lots'),
            ('weekly_food_budget', '-1'),
            ('equipment', ['jetpack']),
            ('equipment', ['none', 'dumbbells']),
        ]

        for field, value in invalid_values:
            with self.subTest(field=field, value=value):
                response = self.client.post(reverse('onboarding'), {**VALID_ANSWERS, field: value})

                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.assertFalse(UserProfile.objects.get(user=user).onboarding_completed)


class AccessGuardTests(OnboardingTestBase):
    def test_anonymous_users_are_sent_to_login(self):
        for name in ('onboarding', 'dashboard'):
            with self.subTest(page=name):
                url = reverse(name)
                response = self.client.get(url)
                self.assertRedirects(
                    response, f"{reverse('login')}?next={url}", fetch_redirect_response=False,
                )

    def test_anonymous_post_to_onboarding_is_rejected_and_saves_nothing(self):
        self.make_user()

        response = self.client.post(reverse('onboarding'), VALID_ANSWERS)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserProfile.objects.get(user__username='alice').onboarding_completed)

    def test_incomplete_user_is_sent_from_dashboard_to_onboarding(self):
        self.log_in_as(self.make_user())

        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_completed_user_is_sent_from_onboarding_to_dashboard(self):
        self.log_in_as(self.make_completed_user())

        response = self.client.get(reverse('onboarding'))

        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

    def test_completed_user_cannot_overwrite_answers_by_posting(self):
        user = self.make_completed_user()
        self.log_in_as(user)

        self.client.post(reverse('onboarding'), {**VALID_ANSWERS, 'goal': 'endurance'})

        self.assertEqual(UserProfile.objects.get(user=user).goal, 'build_muscle')

    def test_user_without_a_profile_row_gets_one_and_is_sent_to_onboarding(self):
        user = self.make_user(with_profile=False)
        self.log_in_as(user)

        response = self.client.get(reverse('dashboard'))

        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)
        self.assertFalse(UserProfile.objects.get(user=user).onboarding_completed)

    def test_dashboard_only_shows_the_signed_in_users_data(self):
        self.make_completed_user('alice', goal='lose_weight')
        self.make_completed_user('bob', goal='endurance')
        self.log_in_as(User.objects.get(username='alice'))

        response = self.client.get(reverse('dashboard'))

        self.assertContains(response, 'alice')
        self.assertContains(response, 'Lose weight')
        self.assertNotContains(response, 'Improve endurance')
        self.assertNotContains(response, 'bob')

    def test_dashboard_has_a_post_logout_form_and_logout_ends_the_session(self):
        self.log_in_as(self.make_completed_user())

        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, f'action="{reverse("logout")}"')

        self.client.post(reverse('logout'))
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(
            response, f"{reverse('login')}?next={reverse('dashboard')}", fetch_redirect_response=False,
        )


class LoginRedirectTests(OnboardingTestBase):
    """Scenario: Returning user skips onboarding, plus the redirect for everyone else."""

    def test_returning_user_logs_in_straight_to_dashboard(self):
        self.make_completed_user()

        response = self.log_in_through_form('alice')

        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)

    def test_user_with_incomplete_onboarding_logs_in_to_onboarding(self):
        self.make_user()

        response = self.log_in_through_form('alice')

        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_logging_in_with_email_follows_the_same_redirect(self):
        self.make_user()

        response = self.log_in_through_form('alice@example.com')

        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_login_without_a_profile_row_does_not_crash_and_creates_one(self):
        user = self.make_user(with_profile=False)

        response = self.log_in_through_form('alice')

        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_next_parameter_is_respected_for_a_completed_user(self):
        self.make_completed_user()

        response = self.log_in_through_form('alice', next_url=reverse('user_profile'))

        self.assertRedirects(response, reverse('user_profile'), fetch_redirect_response=False)

    def test_incomplete_onboarding_takes_priority_over_next(self):
        self.make_user()

        response = self.log_in_through_form('alice', next_url=reverse('user_profile'))

        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)

    def test_logged_in_users_visiting_login_are_redirected_by_onboarding_status(self):
        cases = [
            (self.make_user('incomplete'), 'onboarding'),
            (self.make_completed_user('complete'), 'dashboard'),
        ]
        for user, destination in cases:
            with self.subTest(user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse('login'))
                self.assertRedirects(
                    response, reverse(destination), fetch_redirect_response=False,
                )


class RegistrationTests(OnboardingTestBase):
    def test_new_user_gets_a_profile_and_lands_on_onboarding(self):
        response = self.client.post(reverse('register'), {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': PASSWORD,
            'password2': PASSWORD,
        })

        self.assertRedirects(response, reverse('onboarding'), fetch_redirect_response=False)
        profile = UserProfile.objects.get(user__username='newuser')
        self.assertFalse(profile.onboarding_completed)


class UserProfileModelTests(TestCase):
    def test_equipment_labels_are_human_readable(self):
        user = User.objects.create_user('alice', password=PASSWORD)
        profile = UserProfile.objects.create(user=user, equipment=['dumbbells', 'none'])

        self.assertEqual(
            profile.equipment_labels(),
            ['Dumbbells', 'No equipment (bodyweight only)'],
        )

    def test_unknown_equipment_key_falls_back_to_the_key(self):
        user = User.objects.create_user('alice', password=PASSWORD)
        profile = UserProfile.objects.create(user=user, equipment=['mystery'])

        self.assertEqual(profile.equipment_labels(), ['mystery'])

    def test_new_profiles_start_with_onboarding_incomplete(self):
        user = User.objects.create_user('alice', password=PASSWORD)

        self.assertFalse(UserProfile.objects.create(user=user).onboarding_completed)


class MigrationTests(TestCase):
    def test_no_model_changes_are_missing_a_migration(self):
        out = StringIO()
        try:
            call_command('makemigrations', '--check', '--dry-run', stdout=out)
        except SystemExit:
            self.fail(f'Model changes are missing a migration:\n{out.getvalue()}')
