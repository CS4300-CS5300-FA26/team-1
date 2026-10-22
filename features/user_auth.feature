Feature: D-1 User authentication
  As a new user, I want to create an account and log in,
  so that my plan and history are private to me.

  Scenario: Successful registration
    Given I am on the sign-up page
    When I submit a valid email and a password that meets the requirements
    Then I am logged in and taken to the onboarding questionnaire

  Scenario: Email already registered
    Given an account exists for "sam@example.com"
    When I try to register with "sam@example.com"
    Then I see a message that the email is already registered
    And I remain on the sign-up page

  Scenario: Wrong password
    Given I have an account
    When I log in with an incorrect password
    Then I see "Invalid email or password"
    And I remain logged out