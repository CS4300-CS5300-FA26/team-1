from django.urls import path

from . import views

urlpatterns = [
    path('workouts/', views.this_week, name='workouts_this_week'),
    path('workouts/new/', views.plan_new, name='workouts_new'),
    path('workouts/preferences/', views.preferences, name='workouts_preferences'),
    path('workouts/start/<int:workout_id>/', views.start, name='workouts_start'),
    path('workouts/session/<int:session_id>/', views.session, name='workouts_session'),
    path('workouts/history/', views.history, name='workouts_history'),
]
