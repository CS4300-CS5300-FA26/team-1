from django.urls import path

from . import views

urlpatterns = [
    path('workouts/start/<int:day>/', views.start, name='workouts_start'),
    path('workouts/session/<int:session_id>/', views.session, name='workouts_session'),
    path('workouts/history/', views.history, name='workouts_history'),
]
