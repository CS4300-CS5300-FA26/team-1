from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    # Logout only accepts POST (a link would 405), so templates use a small form.
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
