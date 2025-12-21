from django.urls import path
from .views import process_audio

urlpatterns = [
    path('process/', process_audio),
]
