"""Steps for features/workout_variety_ai.feature (the AI trainer, ADR-014).

Nothing here reaches OpenAI: the app is given a fake key and the call to OpenAI is replaced.
Step wording is unique to this feature (behave shares step text across all step files).
"""

import json
from unittest import mock

from behave import given, then
from django.test import override_settings

from plans.ai_trainer import AiTrainerError
from plans.models import WeeklyPlan

USERNAME = 'planner'  # the user created by "I am logged in with a completed profile"
FAKE_KEY = 'sk-test-not-a-real-key'
AI_SETS = 4  # the fake AI trainer's signature: the rule-based plan gives an intermediate user 3 sets


def fake_trainer(body):
    """Answer like a well-behaved AI trainer, using only what the request says: one allowed exercise per movement."""
    details = json.loads(body['messages'][1]['content'])
    first = {}
    for item in details['allowed_exercises']:
        first.setdefault(item['movement'], item['name'])
    return {
        'days': [
            {'exercises': [{'name': first[movement], 'sets': AI_SETS, 'reps': '10'} for movement in day['must_cover']]}
            for day in details['days']
        ]
    }


def invented_exercise(body):
    answer = fake_trainer(body)
    answer['days'][0]['exercises'][0]['name'] = 'Invented Exercise'
    return answer


def switch_on_ai_trainer(context, side_effect):
    """Give the app a fake key and replace the call to OpenAI with `side_effect`."""
    overrides = override_settings(OPENAI_API_KEY=FAKE_KEY)
    overrides.enable()
    context.add_cleanup(overrides.disable)
    call = mock.patch('plans.ai_trainer.call_openai', side_effect=side_effect)
    context.openai_call = call.start()
    context.add_cleanup(call.stop)
    # A failing AI trainer logs a warning by design; keep it out of the test output.
    quiet = mock.patch('plans.ai_trainer.logger')
    quiet.start()
    context.add_cleanup(quiet.stop)


@given('the AI trainer is available and suggests a valid plan')
def step_ai_valid(context):
    switch_on_ai_trainer(context, fake_trainer)


@given('the AI trainer suggests a plan that fails validation')
def step_ai_invalid(context):
    switch_on_ai_trainer(context, invented_exercise)


@given('the AI trainer is unavailable')
def step_ai_unavailable(context):
    switch_on_ai_trainer(context, AiTrainerError('The AI trainer is down.'))


@then('I see the plan the AI trainer suggested')
def step_see_ai_plan(context):
    response = context.response
    context.test.assertTrue(response.context['ai_built'])
    context.test.assertContains(response, 'Our AI trainer chose the exercises')
    exercises = [exercise for day in response.context['days'] for exercise in day['exercises']]
    context.test.assertTrue(exercises)
    context.test.assertTrue(all(exercise['sets'] == AI_SETS for exercise in exercises))
    context.openai_call.assert_called_once()


@then('the invalid AI plan was not saved')
def step_invalid_plan_not_saved(context):
    context.openai_call.assert_called_once()  # the AI trainer was asked, and its answer was thrown away
    saved = json.dumps(WeeklyPlan.objects.get(user__username=USERNAME).data)
    context.test.assertNotIn('Invented Exercise', saved)
    context.test.assertNotIn('"source"', saved)


@then('the request to the AI trainer holds no name, email, weight, or height')
def step_request_holds_nothing_personal(context):
    context.openai_call.assert_called_once()
    sent = json.dumps(context.openai_call.call_args.args[0])
    for private in (USERNAME, 'planner@example.com', '"weight"', '"height"', '"email"', FAKE_KEY):
        context.test.assertNotIn(private, sent)
