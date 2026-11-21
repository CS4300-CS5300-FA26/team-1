"""Step definitions for features/user_auth.feature.

behave-django gives every scenario a fresh database and exposes `context.test`, a Django
TestCase instance. We use its test client (`context.test.client`) and its assertions.
"""

from unittest import mock

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

from accounts.emails import ACCOUNT_EXISTS_SUBJECT
from accounts.testing import link_in

User = get_user_model()

# Meets AUTH_PASSWORD_VALIDATORS (10+ characters, not common, not numeric, not like the email).
VALID_PASSWORD = 'Tr4ining-Plan-2026!'
WRONG_PASSWORD = 'definitely-the-wrong-one'
EXISTING_EMAIL = 'member@example.com'
NEW_EMAIL = 'newuser@example.com'
NEW_PASSWORD = 'Squat-Bench-Dead-2027?'


def create_account(email, username):
    return User.objects.create_user(username=username, email=email, password=VALID_PASSWORD)


def post_registration(context, email, username):
    context.response = context.test.client.post(
        reverse('register'),
        {
            'username': username,
            'email': email,
            'password1': VALID_PASSWORD,
            'password2': VALID_PASSWORD,
        },
    )


# --- Scenario: Successful registration -------------------------------------------------


@given('I am on the sign-up page')
def step_on_signup_page(context):
    context.response = context.test.client.get(reverse('register'))
    context.test.assertEqual(context.response.status_code, 200)
    context.test.assertTemplateUsed(context.response, 'accounts/register.html')


@when('I submit a valid email and a password that meets the requirements')
def step_submit_valid_registration(context):
    post_registration(context, NEW_EMAIL, 'newuser')


@then('I am asked to confirm my email')
def step_asked_to_confirm(context):
    # The same page whether or not the address already had an account (ADR-018).
    context.test.assertRedirects(context.response, reverse('verify_email_sent'))


@when('I open the confirmation link from the email and confirm')
def step_open_confirmation_link(context):
    link = link_in(mail.outbox[-1])
    context.test.assertContains(context.test.client.get(link), 'Confirm my email')
    context.response = context.test.client.post(link)


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


@then('the owner of "{email}" is emailed that they already have an account')
def step_owner_emailed(context, email):
    context.test.assertEqual([(m.to, m.subject) for m in mail.outbox], [([email], ACCOUNT_EXISTS_SUBJECT)])


@then('no second account is created')
def step_no_second_account(context):
    context.test.assertEqual(User.objects.count(), 1)


# --- Scenario: Wrong password ----------------------------------------------------------


@given('I have an account')
def step_have_an_account(context):
    create_account(EXISTING_EMAIL, username='member')


@when('I log in with an incorrect password')
def step_login_wrong_password(context):
    context.response = context.test.client.post(
        reverse('login'),
        {
            'username': EXISTING_EMAIL,
            'password': WRONG_PASSWORD,
        },
    )


@then('I see "{message}"')
def step_see_message(context, message):
    context.test.assertContains(context.response, message)


@then('I remain logged out')
def step_remain_logged_out(context):
    context.test.assertNotIn('_auth_user_id', context.test.client.session)


# --- Scenario: An unconfirmed account can't log in -------------------------------------


@given("I signed up but haven't confirmed my email")
def step_signed_up_unconfirmed(context):
    post_registration(context, NEW_EMAIL, 'newuser')
    context.test.assertFalse(User.objects.get(username='newuser').is_active)


@when('I log in with my email and password')
def step_login_with_email(context):
    context.response = context.test.client.post(reverse('login'), {'username': NEW_EMAIL, 'password': VALID_PASSWORD})


# --- Scenario: Reset a forgotten password ----------------------------------------------


@when('I ask to reset my password')
def step_ask_reset(context):
    response = context.test.client.post(reverse('password_reset'), {'email': EXISTING_EMAIL})
    context.test.assertRedirects(response, reverse('password_reset_done'))


@when('I open the reset link from the email and choose a new password')
def step_open_reset_link(context):
    form_url = context.test.client.get(link_in(mail.outbox[-1]))['Location']
    response = context.test.client.post(form_url, {'new_password1': NEW_PASSWORD, 'new_password2': NEW_PASSWORD})
    context.test.assertRedirects(response, reverse('password_reset_complete'))


@then('I can log in with the new password')
def step_login_new_password(context):
    context.test.client.post(reverse('login'), {'username': EXISTING_EMAIL, 'password': NEW_PASSWORD})
    context.test.assertIn('_auth_user_id', context.test.client.session)


# --- Scenario: The email can't be sent -------------------------------------------------


@given('the email service is unavailable')
def step_email_unavailable(context):
    context.email_outage = mock.patch('accounts.emails.send_account_email', return_value=False)
    context.email_outage.start()
    context.add_cleanup(lambda: context.email_outage.stop() if context.email_outage else None)


@when('the email service is back and I ask for the link again')
def step_email_back_and_resend(context):
    # The page looked the same as a sent email (ADR-018), so the person asks for the link again.
    context.email_outage.stop()
    context.email_outage = None
    context.test.assertEqual(mail.outbox, [])
    response = context.test.client.post(reverse('resend_verification'), {'email': NEW_EMAIL})
    context.test.assertRedirects(response, reverse('verify_email_sent'))
