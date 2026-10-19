"""Step definitions for features/user_auth.feature.

behave-django gives every scenario a fresh database and exposes `context.test`, a Django
TestCase instance. We use its test client (`context.test.client`) and its assertions.
"""
from behave import given, then, when
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

# Meets AUTH_PASSWORD_VALIDATORS (10+ characters, not common, not numeric, not like the email).
VALID_PASSWORD = 'Tr4ining-Plan-2026!'
WRONG_PASSWORD = 'definitely-the-wrong-one'
EXISTING_EMAIL = 'member@example.com'


def create_account(email, username):
    return User.objects.create_user(username=username, email=email, password=VALID_PASSWORD)


def post_registration(context, email, username):
    context.response = context.test.client.post(reverse('register'), {
        'username': username,
        'email': email,
        'password1': VALID_PASSWORD,
        'password2': VALID_PASSWORD,
    })


# --- Scenario: Successful registration -------------------------------------------------

@given('I am on the sign-up page')
def step_on_signup_page(context):
    context.response = context.test.client.get(reverse('register'))
    context.test.assertEqual(context.response.status_code, 200)
    context.test.assertTemplateUsed(context.response, 'accounts/register.html')


@when('I submit a valid email and a password that meets the requirements')
def step_submit_valid_registration(context):
    post_registration(context, 'newuser@example.com', 'newuser')


@then('I am logged in and taken to the onboarding questionnaire')
def step_logged_in_and_onboarding(context):
    context.test.assertRedirects(context.response, reverse('onboarding'))
    context.test.assertIn('_auth_user_id', context.test.client.session)


# --- Scenario: Email already registered ------------------------------------------------

@given('an account exists for "{email}"')
def step_account_exists_for(context, email):
    create_account(email, username='existing')


@when('I try to register with "{email}"')
def step_try_to_register(context, email):
    post_registration(context, email, username='someone-new')


@then('I see a message that the email is already registered')
def step_already_registered_message(context):
    # The accounts app words this "An account with this email already exists."
    context.test.assertContains(context.response, 'already exists')


@then('I remain on the sign-up page')
def step_remain_on_signup(context):
    context.test.assertEqual(context.response.status_code, 200)
    context.test.assertTemplateUsed(context.response, 'accounts/register.html')


# --- Scenario: Wrong password ----------------------------------------------------------

@given('I have an account')
def step_have_an_account(context):
    create_account(EXISTING_EMAIL, username='member')


@when('I log in with an incorrect password')
def step_login_wrong_password(context):
    context.response = context.test.client.post(reverse('login'), {
        'username': EXISTING_EMAIL,
        'password': WRONG_PASSWORD,
    })


@then('I see "{message}"')
def step_see_message(context, message):
    context.test.assertContains(context.response, message)


@then('I remain logged out')
def step_remain_logged_out(context):
    context.test.assertNotIn('_auth_user_id', context.test.client.session)