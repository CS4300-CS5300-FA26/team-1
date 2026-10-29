"""
URL configuration for fitpro project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: # from django.contrib import admin  # admin disabled, see ADR-007
from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import include, path

from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('accounts/', include('accounts.urls')),
    # path('admin/', admin.site.urls),  # admin disabled, see ADR-007
    path('users/', views.user_profile_view, name='user_profile'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('dashboard/', views.dashboard, name='dashboard'),
]
