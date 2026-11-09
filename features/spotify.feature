Feature: D-7 Spotify integration
  As a FitPro user, I want to link my Spotify account and use it to log in or sign up,
  so that FitPro can later build playlists and control playback for my workouts.

  Scenario: Link succeeds
    Given Spotify is not linked
    When I approve access on Spotify's authorization page
    Then I return to settings and see "Spotify connected" with my Spotify name

  Scenario: User declines
    Given I am on Spotify's authorization page
    When I decline access
    Then I return to settings and see "Spotify not connected"

  Scenario: Unlink
    Given Spotify is linked
    When I click "Disconnect Spotify"
    Then I see "Spotify not connected"

  Scenario: Log in with a linked Spotify account
    Given I have a FitPro account linked to Spotify
    When I log in with Spotify and approve access
    Then I am logged in and taken to my dashboard

  Scenario: Log in with Spotify never matches on email
    Given I have a FitPro account with the same email as my Spotify account, but Spotify is not linked
    When I log in with Spotify and approve access
    Then I am told to log in with my password and link Spotify from my profile
    And I remain logged out
