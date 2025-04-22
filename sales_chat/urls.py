from django.urls import path
from . import views

app_name = "sales_chat"

urlpatterns = [
    path("", views.chat_room, name="chat_room"),          
    path("stream/", views.chat_stream, name="chat_stream"),
    path("coach/", views.coach_advice, name="coach"),  
]
