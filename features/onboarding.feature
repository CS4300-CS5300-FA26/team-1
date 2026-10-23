Feature: D-2 Onboarding questionnaire
  As a fitness beginner, I want to enter my goals, baseline metrics, weekly food budget,
  and available equipment during onboarding, so that my plan fits my body, budget, and gear.

  Scenario: Complete onboarding
    Given I am logged in and have not completed onboarding
    When I submit my goal, height, weight, experience level, weekly food budget, and available equipment
    Then I see a profile summary showing those values
    And I am taken to my dashboard

  Scenario: Missing required answer
    Given I am on the onboarding questionnaire
    When I submit without a weekly food budget
    Then I see a message that the budget is required
    And my other answers are still filled in

  Scenario: Returning user skips onboarding
    Given I have already completed onboarding
    When I log in
    Then I am taken straight to my dashboard