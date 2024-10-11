from django.urls import path

from . import views

app_name = 'submission'

urlpatterns = [
    path("", views.login, name="login"),
    path("cadUser",views.cadUser, name="createUser"),
    path("conferencia/<id>/",views.conferencia,name="conferencia"),
    path("conferencia/<id>/<data>/",views.conferencia,name="conferenciaWithDate")
]