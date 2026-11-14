"""Steps for features/workout_variety.feature (week-to-week workout variety, ADR-013)."""

from datetime import timedelta

from behave import given, then, when
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from core.models import UserProfile
from plans.generator import EXERCISES, SPLIT_LABELS, generate_plan
from plans.models import WeeklyPlan
from plans.services import MAX_SPLIT_SWITCHES, week_start_for

USERNAME = 'planner'  # the user created by "I am logged in with a completed profile"
PASSWORD = 'Correct-Horse-9'
SPLIT_KEYS = {label: key for key, label in SPLIT_LABELS.items()}
BODYWEIGHT_NAMES = {name for options in EXERCISES.values() for required, name in options if required == 'none'}


def _this_week_plan(context):
    return WeeklyPlan.objects.get(user__username=USERNAME, week_start=week_start_for(timezone.localdate()))


def _open_this_week(context):
    context.response = context.test.client.get(reverse('this_week'))
    assert context.response.status_code == 200, context.response.status_code
    return context.response


def _choose_split(context, choice):
    context.response = context.test.client.post(reverse('change_split'), {'split': choice}, follow=True)


def _signature(response):
    """What a user sees of the week: each day's name and exercises (not the 'today' marker)."""
    return [(day['day'], day['name'], day['exercises']) for day in response.context['days']]


@given('last week\'s saved plan used the "{label}" split')
def step_last_weeks_plan(context, label):
    profile = UserProfile.objects.get(user__username=USERNAME)
    last_week = week_start_for(timezone.localdate()) - timedelta(days=7)
    plan = generate_plan(profile, split=SPLIT_KEYS[label])
    WeeklyPlan.objects.create(user=profile.user, week_start=last_week, data=plan)


@given('I am logged in with a completed profile that has no equipment')
def step_logged_in_without_equipment(context):
    user = User.objects.create_user(USERNAME, f'{USERNAME}@example.com', PASSWORD)
    UserProfile.objects.create(
        user=user,
        onboarding_completed=True,
        goal='build_muscle',
        height_inches=70,
        weight=180,
        experience_level='beginner',  # 3 training days, so every split style is offered
        weekly_food_budget=85,
        equipment=['none'],
    )
    assert context.test.client.login(username=USERNAME, password=PASSWORD)


@given('I have opened This Week once this week')
def step_opened_this_week_once(context):
    response = _open_this_week(context)
    context.week_before = _signature(response)
    context.split_before = response.context['split_key']
    context.macros_before = response.context['macros']


@given('I have already switched my split {count:d} times this week')
def step_already_switched(context, count):
    _open_this_week(context)
    saved = _this_week_plan(context)
    saved.data['switches'] = count
    saved.save(update_fields=['data'])
    context.saved_before = saved.data


@when('I open This Week again later in the week')
def step_open_again(context):
    _open_this_week(context)


@when('I choose the "{label}" split for this week')
def step_choose_split(context, label):
    _choose_split(context, SPLIT_KEYS[label])


@when('I ask for a different workout split this week')
def step_ask_for_different_split(context):
    _choose_split(context, 'next')


@then('I see a plan that does not use the "{label}" split')
def step_plan_not_using_split(context, label):
    assert context.response.context['split_key'] not in (None, SPLIT_KEYS[label]), context.response.context['split_key']


@then('I see the same split and exercises as before')
def step_same_as_before(context):
    assert _signature(context.response) == context.week_before
    assert context.response.context['split_key'] == context.split_before


@then('my plan includes push, pull, and legs workouts')
def step_plan_includes_ppl(context):
    names = {day['name'] for day in context.response.context['days']}
    assert {'Push', 'Pull', 'Legs'} <= names, names


@then('I see a split that is different from the one I had')
def step_split_differs(context):
    assert context.response.context['split_key'] not in (None, context.split_before)
    assert _signature(context.response) != context.week_before


@then('my daily macro targets are unchanged')
def step_macros_unchanged(context):
    assert context.response.context['macros'] == context.macros_before


@then("I am told I have reached this week's switch limit")
def step_told_limit_reached(context):
    expected = f'reached the limit of {MAX_SPLIT_SWITCHES} split switches'
    assert expected in context.response.content.decode(), 'limit message not shown'


@then('my plan is unchanged')
def step_plan_unchanged(context):
    assert _this_week_plan(context).data == context.saved_before


@then('every exercise in my plan can be done without equipment')
def step_every_exercise_bodyweight(context):
    exercises = {e['name'] for day in context.response.context['days'] for e in day['exercises']}
    assert exercises, 'the plan has no exercises'
    assert exercises <= BODYWEIGHT_NAMES, exercises - BODYWEIGHT_NAMES
