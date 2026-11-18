"""The AI trainer: OpenAI chooses the exercises for each workout of a weekly plan (ADR-014).

The rule-based generator (generator.py) still decides everything that has to stay predictable: the split, which
days are training days, the macro targets, and which kinds of movement each workout covers. The AI only picks
exercises from our own library for those days. Whatever it returns is checked against the library and the user's
equipment; if anything is wrong, or the call fails, the rule-based plan is used unchanged (improve_plan never raises).

The API key (settings.OPENAI_API_KEY) is read in call_openai() and goes only into the Authorization header. Nothing
here logs the key, a prompt, or a response body (OpenAI's error bodies can echo part of a key), and no name, email,
weight, or height is ever sent: only the goal, experience level, split, and exercise names.
"""

import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

from accounts import throttle

from .generator import EXERCISES, SPLIT_LABELS

logger = logging.getLogger(__name__)

OPENAI_URL = 'https://api.openai.com/v1/chat/completions'
TIMEOUT_SECONDS = 15  # plan pages wait for this call, so it stays well under Gunicorn's 30 second worker timeout
MAX_RESPONSE_BYTES = 200_000
MAX_OUTPUT_TOKENS = 4000  # reasoning models count their thinking against this limit too, so leave room for it
MAX_EXERCISES_PER_DAY = 8
MAX_RECENT_NAMES = 60
MIN_SETS, MAX_SETS = 1, 5
MAX_REP_NUMBER = 60  # reps, seconds, or minutes
REPS_PATTERN = re.compile(r'\d{1,2}(-\d{1,2})?( sec| min)?( each side)?')  # "10", "8-12", "30-45 sec", "8-12 each side"

# Which movement every exercise in the library trains (names are unique across the library).
MOVEMENT_OF = {name: movement for movement, options in EXERCISES.items() for _, name in options}

SYSTEM_PROMPT = (
    'You are a certified strength and conditioning coach for a beginner-friendly fitness app. '
    'You choose the exercises for one week of workouts. '
    'Reply only with JSON that matches the schema, with one entry in "days" for each item of the request\'s "days", '
    'in the same order. '
    'Use only exercise names from "allowed_exercises", and use each name at most once per day. '
    'Every movement listed in a day\'s "must_cover" must be trained at least once that day. '
    'Give 1 to 5 sets per exercise. '
    'Write reps as a number or a range such as "10" or "8-12", or a time such as "30-45 sec" or "20 min". '
    'For one-sided exercises such as lunges, add " each side", for example "8-12 each side". '
    'Where an equally suitable alternative exists, prefer exercises that are not in "recently_used" '
    'so the week feels fresh. '
    'Match the volume to the goal and experience level. Do not add notes or any other text.'
)


class AiTrainerError(Exception):
    """The AI trainer couldn't give us a usable answer."""


def enabled():
    """The AI trainer is on only when a key is configured."""
    return bool(settings.OPENAI_API_KEY)


def exercise_catalog(equipment):
    """{exercise name: movement} for every exercise someone with this equipment can do."""
    have = set(equipment or [])
    return {
        name: movement
        for movement, options in EXERCISES.items()
        for required, name in options
        if required == 'none' or required in have
    }


def _training_days(plan):
    return [day for day in plan['days'] if day['exercises']]


def _response_schema(names):
    """The JSON Schema OpenAI must follow. Only keywords OpenAI's strict mode supports; ranges are checked later."""
    return {
        'name': 'weekly_workouts',
        'strict': True,
        'schema': {
            'type': 'object',
            'additionalProperties': False,
            'required': ['days'],
            'properties': {
                'days': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'additionalProperties': False,
                        'required': ['exercises'],
                        'properties': {
                            'exercises': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'additionalProperties': False,
                                    'required': ['name', 'sets', 'reps'],
                                    'properties': {
                                        'name': {'type': 'string', 'enum': names},
                                        'sets': {'type': 'integer'},
                                        'reps': {'type': 'string'},
                                    },
                                },
                            }
                        },
                    },
                }
            },
        },
    }


def build_request(goal, level, plan, catalog, recent=()):
    """The body for OpenAI. Holds no personal details, and no free text except our own exercise names."""
    days = [
        {
            'weekday': day['day'],
            'workout': day['name'],
            'must_cover': sorted({MOVEMENT_OF[exercise['name']] for exercise in day['exercises']}),
        }
        for day in _training_days(plan)
    ]
    known_recent = [name for name in dict.fromkeys(recent) if name in MOVEMENT_OF][:MAX_RECENT_NAMES]
    names = sorted(catalog)
    details = {
        'goal': goal,
        'experience_level': level,
        'split': SPLIT_LABELS[plan['split']],
        'days': days,
        'allowed_exercises': [{'name': name, 'movement': catalog[name]} for name in names],
        'recently_used': known_recent,
    }
    body = {
        'model': settings.OPENAI_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps(details, separators=(',', ':'))},
        ],
        'response_format': {'type': 'json_schema', 'json_schema': _response_schema(names)},
        'max_completion_tokens': MAX_OUTPUT_TOKENS,
    }
    if settings.OPENAI_REASONING_EFFORT:  # only reasoning models accept this; leave it empty for the others
        body['reasoning_effort'] = settings.OPENAI_REASONING_EFFORT
    return body


def call_openai(body):
    """Send the request and return the JSON the model produced (still unchecked). Raises AiTrainerError."""
    request = Request(  # noqa: S310 (fixed https URL)
        OPENAI_URL,
        data=json.dumps(body).encode(),
        headers={'Authorization': f'Bearer {settings.OPENAI_API_KEY}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        # Only ever the constant https:// URL above, so no file:// or other scheme can reach it.
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # nosec B310  # noqa: S310
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        # Log the status only: OpenAI's error bodies can echo part of the key.
        logger.warning('OpenAI request failed with HTTP %s', exc.code)
        raise AiTrainerError(f'OpenAI answered HTTP {exc.code}.') from None
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning('OpenAI request failed: %s', type(exc).__name__)
        raise AiTrainerError('OpenAI could not be reached.') from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise AiTrainerError('OpenAI sent a response that is too large.')
    try:
        data = json.loads(raw)
    except ValueError:
        raise AiTrainerError('OpenAI returned a response that is not JSON.') from None

    choices = data.get('choices') if isinstance(data, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get('message') if isinstance(choice, dict) else None
    if not isinstance(choice, dict) or not isinstance(message, dict):
        raise AiTrainerError('OpenAI returned no answer.')
    if message.get('refusal'):
        raise AiTrainerError('OpenAI declined the request.')
    if choice.get('finish_reason') != 'stop':
        raise AiTrainerError('OpenAI did not finish its answer.')
    content = message.get('content')
    if not isinstance(content, str):
        raise AiTrainerError('OpenAI returned an empty answer.')
    try:
        return json.loads(content)
    except ValueError:
        raise AiTrainerError('The answer is not valid JSON.') from None


def _valid_reps(reps):
    if not isinstance(reps, str) or not REPS_PATTERN.fullmatch(reps):
        return False
    numbers = [int(number) for number in re.findall(r'\d+', reps)]
    return all(1 <= number <= MAX_REP_NUMBER for number in numbers) and numbers == sorted(numbers)


def _validate_day(given, base_day, catalog, number):
    """Check one day's exercises and return them in the plan's shape."""
    if not isinstance(given, dict) or set(given) != {'exercises'} or not isinstance(given['exercises'], list):
        raise AiTrainerError(f'Day {number} is not in the expected shape.')
    required = {MOVEMENT_OF[exercise['name']] for exercise in base_day['exercises']}
    items = given['exercises']
    if not len(required) <= len(items) <= MAX_EXERCISES_PER_DAY:
        raise AiTrainerError(f'Day {number} has the wrong number of exercises.')

    clean, seen, covered = [], set(), set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'name', 'sets', 'reps'}:
            raise AiTrainerError(f'Day {number} has an exercise in the wrong shape.')
        name, sets, reps = item['name'], item['sets'], item['reps']
        if not isinstance(name, str) or name not in catalog:
            raise AiTrainerError(f'Day {number} has an exercise that is not allowed.')
        if name in seen:
            raise AiTrainerError(f'Day {number} repeats an exercise.')
        if isinstance(sets, bool) or not isinstance(sets, int) or not MIN_SETS <= sets <= MAX_SETS:
            raise AiTrainerError(f'Day {number} has an invalid number of sets.')
        if not _valid_reps(reps):
            raise AiTrainerError(f'Day {number} has invalid reps.')
        seen.add(name)
        covered.add(catalog[name])
        clean.append({'name': name, 'sets': sets, 'reps': reps})
    if not required <= covered:
        raise AiTrainerError(f'Day {number} leaves out a required movement.')
    return clean


def validate_days(answer, plan, catalog):
    """Check the whole answer against the rule-based plan and return each training day's exercises, in order."""
    if not isinstance(answer, dict) or set(answer) != {'days'} or not isinstance(answer['days'], list):
        raise AiTrainerError('The answer is not in the expected shape.')
    trained = _training_days(plan)
    if len(answer['days']) != len(trained):
        raise AiTrainerError('The answer has the wrong number of days.')
    return [
        _validate_day(given, base_day, catalog, number)
        for number, (given, base_day) in enumerate(zip(answer['days'], trained, strict=True), start=1)
    ]


def improve_plan(profile, plan, recent=()):
    """Return `plan` with AI-chosen exercises, or `plan` itself if the AI is off, limited, or gives anything unusable.

    `recent` lists the exercise names of the user's previous plan, so the AI can vary the week.
    """
    if not enabled():
        return plan
    # Each call costs money, so a user only gets so many an hour (accounts/throttle.py).
    if throttle.acquire_ai_trainer(profile.user_id):
        return plan
    try:
        catalog = exercise_catalog(getattr(profile, 'equipment', None))
        body = build_request(profile.goal, profile.experience_level, plan, catalog, recent)
        chosen = validate_days(call_openai(body), plan, catalog)
        exercises = iter(chosen)
        days = [{**day, 'exercises': next(exercises)} if day['exercises'] else day for day in plan['days']]
    except Exception as exc:  # whatever goes wrong, the user still gets the rule-based plan
        reason = str(exc) if isinstance(exc, AiTrainerError) else type(exc).__name__
        logger.warning('AI trainer not used for user %s (%s); using the rule-based plan', profile.user_id, reason)
        return plan
    return {**plan, 'days': days, 'source': 'ai'}
