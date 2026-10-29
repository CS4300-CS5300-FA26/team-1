"""Step definitions for features/onboarding.feature

behave-django gives every scenario a fresh database and exposes `context.test`, a Django
TestCase instance. We use its test client (`context.test.client`) and its assertions.
"""

from decimal import Decimal

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import UserProfile

User = get_user_model()

# Meets AUTH_PASSWORD_VALIDATORS (10+ characters, not common, not numeric, not like the email).
VALID_PASSWORD = '<M42HVb-;p(!2cve9!'
USERNAME = 'onboarder'

# What the user types into the questionnaire.
ANSWERS = {
    'goal': 'build_muscle',
    'height_inches': '70',
    'weight': '180.5',
    'experience_level': 'intermediate',
    'weekly_food_budget': '85.50',
    'equipment': ['dumbbells', 'bands'],
}

# What a user who finished onboarding earlier has saved.
SAVED_ANSWERS = {
    'goal': 'build_muscle',
    'height_inches': 70,
    'weight': Decimal('180.50'),
    'experience_level': 'intermediate',
    'weekly_food_budget': Decimal('85.50'),
    'equipment': ['dumbbells'],
}


def create_user(context, completed):
    context.user = User.objects.create_user(USERNAME, 'onboarder@example.com', VALID_PASSWORD)
    answers = SAVED_ANSWERS if completed else {}
    UserProfile.objects.create(user=context.user, onboarding_completed=completed, **answers)


def log_in_directly(context):
    logged_in = context.test.client.login(username=USERNAME, password=VALID_PASSWORD)
    context.test.assertTrue(logged_in)


@given('I am logged in and have not completed onboarding')
def step_logged_in_not_onboarded(context):
    create_user(context, completed=False)
    log_in_directly(context)


@when('I submit my goal, height, weight, experience level, weekly food budget, and available equipment')
def step_submit_all_answers(context):
    # follow=True so the next steps see the page the user ends up on.
    context.response = context.test.client.post(reverse('onboarding'), ANSWERS, follow=True)


@then('I see a profile summary showing those values')
def step_see_profile_summary(context):
    context.test.assertContains(context.response, 'Your profile summary')
    for text in ('Build muscle', '70 in', '180.5', 'Intermediate', '$85.50', 'Dumbbells', 'Resistance bands'):
        context.test.assertContains(context.response, text)


# "And I am taken to my dashboard" / "Then I am taken straight to my dashboard"
@then('I am taken to my dashboard')
@then('I am taken straight to my dashboard')
def step_taken_to_dashboard(context):
    context.test.assertRedirects(context.response, reverse('dashboard'))


# Scenario: Missing required answer ------------------------------------


@given('I am on the onboarding questionnaire')
def step_on_questionnaire(context):
    create_user(context, completed=False)
    log_in_directly(context)
    context.response = context.test.client.get(reverse('onboarding'))
    context.test.assertEqual(context.response.status_code, 200)


@when('I submit without a weekly food budget')
def step_submit_without_budget(context):
    answers = {**ANSWERS, 'weekly_food_budget': ''}
    context.response = context.test.client.post(reverse('onboarding'), answers)


@then('I see a message that the budget is required')
def step_budget_required_message(context):
    context.test.assertEqual(context.response.status_code, 200)  # re-shown, not redirected
    context.test.assertContains(context.response, 'Weekly food budget is required.')


@then('my other answers are still filled in')
def step_other_answers_kept(context):
    form = context.response.context['form']
    context.test.assertEqual(form['goal'].value(), 'build_muscle')
    context.test.assertEqual(form['experience_level'].value(), 'intermediate')
    context.test.assertEqual(form['height_inches'].value(), '70')
    context.test.assertEqual(form['weight'].value(), '180.5')
    context.test.assertCountEqual(form['equipment'].value(), ['dumbbells', 'bands'])


# Scenario: Returning user skips onboarding ----------------------------


@given('I have already completed onboarding')
def step_already_onboarded(context):
    create_user(context, completed=True)


@when('I log in')
def step_log_in(context):
    context.response = context.test.client.post(
        reverse('login'),
        {'username': USERNAME, 'password': VALID_PASSWORD},
        follow=True,
    )
