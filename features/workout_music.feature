Feature: A workout playlist starts with my workout
  As a passive exerciser, I want a workout playlist to start when I begin a session,
  so that I stay motivated without picking music.

  Scenario: Playlist starts
    Given Spotify is linked and a Spotify device is active
    When I start today's workout
    Then a playlist starts playing
    And its name appears on the workout screen

  Scenario: Spotify not linked
    Given Spotify is not linked
    When I start today's workout
    Then the workout starts normally
    And I see a "Link Spotify for music" option

  Scenario: Playback not possible
    Given Spotify is linked but no device is active or my account cannot be controlled
    When I start today's workout
    Then the workout starts normally
    And I see an "Open in Spotify" link for the playlist
