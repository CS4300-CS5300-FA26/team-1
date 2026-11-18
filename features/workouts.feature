Feature: Exercise tracking for the weekly plan
  As a gym beginner, I want to log each workout of my weekly plan as I do it,
  so that I can see how consistent I am and what I lifted last time.

  Background:
    Given I have finished onboarding with only dumbbells
    And I have opened This Week

  Scenario: Every training day can be started from This Week
    Then each training day has a Start workout button
    And rest days do not

  Scenario: Logging a workout
    Given I have started the first workout of the week
    When I log reps and weight for the first set of each exercise and finish
    Then the workout is marked done
    And it appears in my progress history
    And This Week shows it as done

  Scenario: Finishing with nothing logged
    Given I have started the first workout of the week
    When I finish without logging anything
    Then I am asked to log at least one set

  Scenario: My workouts are private
    Given another member has started a workout
    When I try to open their workout
    Then I get a not found response
