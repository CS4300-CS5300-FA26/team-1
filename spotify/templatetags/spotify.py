"""Spotify parts of other apps' pages, so those apps' views don't need to know about Spotify.

{% load spotify %}
{% spotify_profile_section %}        on the profile page
{% spotify_sign_in_button "login" %}  on the log-in page ("signup" on the sign-up page)
"""

from django import template

from ..config import is_configured
from ..models import SpotifyAccount

register = template.Library()


@register.inclusion_tag('spotify/_profile_section.html', takes_context=True)
def spotify_profile_section(context):
    user = context['request'].user
    return {
        'account': SpotifyAccount.objects.filter(user=user).first(),
        'configured': is_configured(),
        'has_password': user.has_usable_password(),
        'csrf_token': context.get('csrf_token'),
    }


@register.inclusion_tag('spotify/_sign_in_button.html', takes_context=True)
def spotify_sign_in_button(context, mode):
    return {'configured': is_configured(), 'mode': mode, 'csrf_token': context.get('csrf_token')}
