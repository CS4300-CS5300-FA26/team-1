from django.urls import path

from . import views

urlpatterns = [
    path('this-week/', views.this_week, name='this_week'),
    path('this-week/split/', views.change_split, name='change_split'),
    path('workout/start/', views.start_workout, name='start_workout'),
    path('workout/', views.workout, name='workout'),
    path('nutrition/', views.nutrition, name='nutrition'),
]
