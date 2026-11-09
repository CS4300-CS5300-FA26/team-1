from django.urls import path

from . import views

urlpatterns = [
    path('link/', views.start, {'mode': 'link'}, name='spotify_link'),
    path('login/', views.start, {'mode': 'login'}, name='spotify_login'),
    path('signup/', views.start, {'mode': 'signup'}, name='spotify_signup'),
    path('disconnect/', views.unlink, name='spotify_unlink'),
    path('status/', views.status, name='spotify_status'),
]
