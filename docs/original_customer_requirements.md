# FitPro Ecosystem: Design Specification

## 1. Project Overview

### 1.1 Overview
Fitness beginners and budget-conscious students often struggle to find accessible, structured training and nutritional guidance without paying for expensive personal trainers or premium apps. FitPro solves this by providing a unified, intelligent ecosystem that generates personalized workout splits, provides budget-friendly meal prep guidance, and curates dynamic playlists. This holistic approach ensures users who want a passive, guided experience can focus on execution, while the automated backend handles the complexity of their fitness journey.

### 1.2 Target Audience
The primary users are individuals who want an accessible, low-friction entry into fitness. Specifically, the system targets:
1. **Fitness Beginners** looking for structured, easy-to-follow guidance.
2. **Budget-conscious gym-goers** avoiding the cost of premium trainers.
3. **Gym-avoidant people** who need simple, adaptable home or low-equipment routines.
4. **Cash-strapped students** balancing tight schedules and tighter budgets.
5. **Passive exercisers** who prefer a "don't make me think" approach to their daily routines.

### 1.3 Goals
1. Provide personalized, AI-generated workout splits that adapt to user progress with a focus on simplicity.
2. Synchronize training regimens with dietary tracking to maximize macro-nutrient utilization on a budget.
3. Automate budget-friendly meal planning and grocery list generation using third-party recipe APIs.
4. Enhance workout motivation through dynamic music playlist recommendations (via Spotify/Apple Music) to keep passive exercisers engaged.
5. Maintain a frictionless user experience by abstracting the AI personal trainer into a background compilation agent, ensuring users are guided without overthinking.

## 2. Core User Flow
1. User signs into the application and completes a rapid onboarding questionnaire defining baseline metrics, budget limits, and available equipment.
2. The AI background agent compiles the input data and generates a customized weekly workout split and a budget-conscious macro target list.
3. User selects a daily workout; the application connects to a music API to generate a context-aware playlist.
4. The system queries a recipe/food API to generate a cheap, macro-friendly meal prep idea for post-workout recovery.
5. User completes the workout, logs simple completion metrics, and the AI agent automatically refines future splits.

## 3. Features

### Training & PT Intelligence
1. **Automated AI PT Agent**: Compiles user input data into structured, easy-to-follow workout plans.
2. **Dynamic Workout Splits**: Generates rotating schedules utilizing available (or zero) equipment.
3. **Frictionless Workout Interface**: Tracks sets, reps, and rest timers with minimal manual input required.
4. **Simple Progress Dashboard**: Visualizes consistency and basic volume trends without overwhelming the user.

### Nutrition & Diet
5. **Macro Optimization Engine**: Calculates required macronutrients based on current training splits.
6. **Budget Recipe Integration**: Interfaces with recipe APIs (e.g., Spoonacular) to suggest cheap, macro-friendly meals instead of expensive delivery.
7. **Automated Grocery Lists**: Compiles required ingredients for the week's suggested meals to keep users on budget.

### Media & Third-Party Integration
8. **Smart Music Recommendations**: Connects to Spotify to curate playlists that drive momentum for unmotivated users.
9. **Automated Playlist Syncing**: Automatically queues the AI-recommended playlist upon starting a workout.
10. **Secure Authentication Gateway**: Manages user accounts and securely handles OAuth tokens for linked third-party services.

## 4. Required APIs
To satisfy the system constraints, the application will integrate the following free-to-use APIs:
* **OpenAI API (or compatible schema models)** [AI API]: Serves as the core logic for the lightweight PT agent. It will ingest user metrics and output structured JSON workout splits.
* **Spoonacular API** [Third-Party API]: Replaces food delivery integrations to provide budget-conscious recipe recommendations, meal planning, and grocery list generation.
* **Spotify Web API** [Third-Party API]: Interacts with the user's Spotify account to retrieve and build smart playlist recommendations.

## 5. Architecture Context
While the development team has full flexibility in implementing the UI, the following architecture constraints act as the system baseline.

### 5.1 Stack Requirements
* **Backend Core**: Django (Python) is strictly required for handling the core business logic, AI compilation pipelines, and API integrations.
* **Frontend UI**: Open choice (e.g., React, Vue, HTMX, or standard Django templates). Must provide a responsive, accessible interface.
* **Database**: PostgreSQL (Required to meet the database backend constraint).

### 5.2 Storage Model
* **PostgreSQL (Relational DB)**: Stores user metadata, securely hashed authentication data, historical workout logs, generated splits, and cached exercise mappings.
* **Blob Storage (S3-compatible)**: Stores static assets, exercise demonstration images/videos, and user profile media.

### 5.3 System Boundaries
* `backend/` (Django Project) — Owns the core configuration, external routing, and overarching security/auth settings.
* `apps/` (Django Apps) — Isolated domain modules (e.g., `workouts`, `nutrition`, `users`) responsible strictly for model definitions, API integration logic, and JSON response sanitization.
* `frontend/` — Owns the client-facing UI components, active workout state management, and user interaction layers.

### 5.4 Auth and Access Model
* Every user signs in via a secure authentication system (e.g., Django's built-in Auth, JWT, or a third-party OAuth provider).
* Users maintain strict ownership of their physical data; cross-user data access is strictly forbidden at the database row level.
* Access tokens for third-party integrations (e.g., Spotify OAuth) are encrypted at rest and tied exclusively to the individual user session.

### 5.5 Invariants
1. **No Direct User-to-AI Chat**: To limit scope and expense, all AI interactions must be abstracted through structured backend data compilation.
2. **Database Requirement**: The system must persistently store user profiles and workout histories in the relational database backend.
3. **Graceful Degradation**: If external third-party APIs fail, the core workout tracking features must continue to function uninterrupted.
4. **Secure Data Parsing**: All outputs from the AI API must pass through a strict schema validation layer before being inserted into the database or presented to the user.
