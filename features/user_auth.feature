Feature: D-1 User authentication
  As a new user, I want to create an account and log in,
  so that my plan and history are private to me.

  Scenario: Successful registration
    Given I am on the sign-up page
    When I submit a valid email and a password that meets the requirements
    Then I am asked to confirm my email
    And I remain logged out
    When I open the confirmation link from the email and confirm
    Then I am logged in and taken to the onboarding questionnaire

  Scenario: Email already registered
    Given an account exists for "sam@example.com"
    When I try to register with "sam@example.com"
    Then I am asked to confirm my email
    And the owner of "sam@example.com" is emailed that they already have an account
    And no second account is created

  Scenario: Wrong password
    Given I have an account
    When I log in with an incorrect password
    Then I see "Invalid email or password"
    And I remain logged out

  Scenario: An unconfirmed account can't log in
    Given I signed up but haven't confirmed my email
    When I log in with my email and password
    Then I see "Invalid email or password"
    And I remain logged out

  Scenario: Reset a forgotten password
    Given I have an account
    When I ask to reset my password
    And I open the reset link from the email and choose a new password
    Then I can log in with the new password

  Scenario: The email can't be sent
    Given the email service is unavailable
    When I submit a valid email and a password that meets the requirements
    Then I am asked to confirm my email
    When the email service is back and I ask for the link again
    And I open the confirmation link from the email and confirm
    Then I am logged in and taken to the onboarding questionnaire
