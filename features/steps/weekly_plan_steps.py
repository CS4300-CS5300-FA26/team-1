"""Step definitions for features/weekly_plan.feature

Step wording is unique to this feature (behave shares step text across all step files).
"""
from decimal import Decimal
from unittest import mock

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import UserProfile

User = get_user_model()

VALID_PASSWORD = '<M42HVb-;p(!2cve9!'
USERNAME = 'planner'


@given('I am logged in with a completed profile')
def step_logged_in_completed_profile(context):
    user = User.objects.create_user(USERNAME, 'planner@example.com', VALID_PASSWORD)
    UserProfile.objects.create(
        user=user, onboarding_completed=True, goal='build_muscle', height_inches=70,
        weight=Decimal('180.50'), experience_level='intermediate',
        weekly_food_budget=Decimal('85.50'), equipment=['dumbbells'],
    )
    context.test.assertTrue(context.test.client.login(username=USERNAME, password=VALID_PASSWORD))


@given('the plan generator is unavailable')
def step_generator_unavailable(context):
    patcher = mock.patch('plans.services.generate_plan', side_effect=RuntimeError('generator down'))
    patcher.start()
    context.add_cleanup(patcher.stop)


def open_from_dashboard(context, url_name):
    """Go to the dashboard, check it links to the page, then follow the link."""
    dashboard = context.test.client.get(reverse('dashboard'))
    context.test.assertContains(dashboard, reverse(url_name))
    # The generator-down scenario logs the failure; keep it out of the test output.
    with mock.patch('plans.services.logger'):
        context.response = context.test.client.get(reverse(url_name))
    context.test.assertEqual(context.response.status_code, 200)


@when('I open This Week from the dashboard')
def step_open_this_week(context):
    open_from_dashboard(context, 'this_week')


@when('I open Nutrition from the dashboard')
def step_open_nutrition(context):
    open_from_dashboard(context, 'nutrition')


def assert_full_week(context):
    days = context.response.context['days']
    context.test.assertEqual(len(days), 7)
    training = [day for day in days if day['exercises']]
    context.test.assertGreaterEqual(len(training), 3)
    for day in training:
        for exercise in day['exercises']:
            context.test.assertTrue(exercise['name'])
            context.test.assertTrue(exercise['sets'])
            context.test.assertTrue(exercise['reps'])
    context.test.assertContains(context.response, 'Sets')
    context.test.assertContains(context.response, 'Reps')


@then('I see a full week of workouts with exercises, sets, and reps')
def step_see_full_week(context):
    assert_full_week(context)
    context.test.assertNotContains(context.response, 'starter plan')


@then('I see a starter plan with a full week of workouts')
def step_see_starter_plan(context):
    assert_full_week(context)
    context.test.assertContains(context.response, 'starter plan')


@then("I see today's macro targets")
def step_see_todays_macros(context):
    context.test.assertContains(context.response, "Today's macro targets")
    for label in ('calories', 'protein', 'carbs', 'fat'):
        context.test.assertContains(context.response, label)


@then('I see my daily macro targets')
def step_see_daily_macros(context):
    step_see_todays_macros(context)
