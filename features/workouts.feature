Feature: D-3 Workout split and exercise tracking
  As a gym beginner, I want a weekly workout split built from the equipment I have,
  so that I know what to do each day and can log how it went.

  Scenario: A split that fits my equipment
    Given I have finished onboarding with only dumbbells
    When I open This Week
    Then I see a workout for each of my training days and rest days between them
    And every exercise uses dumbbells or my body weight

  Scenario: No equipment at all
    Given I have finished onboarding with no equipment
    When I open This Week
    Then I see a workout for each of my training days and rest days between them
    And every exercise uses my body weight

  Scenario: Choosing how many days I train
    Given I have finished onboarding with only dumbbells
    When I choose to train 5 days a week
    Then my week has 5 workouts

  Scenario: Logging a workout
    Given I have finished onboarding with only dumbbells
    And I have started the first workout of the week
    When I log reps and weight for the first set of each exercise and finish
    Then the workout is marked done
    And it appears in my progress history

  Scenario: Finishing with nothing logged
    Given I have finished onboarding with only dumbbells
    And I have started the first workout of the week
    When I finish without logging anything
    Then I am asked to log at least one set

  Scenario: My workouts are private
    Given I have finished onboarding with only dumbbells
    And another member has started a workout
    When I try to open their workout
    Then I get a not found response
