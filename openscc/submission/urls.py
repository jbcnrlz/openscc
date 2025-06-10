from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

app_name = 'submission'

urlpatterns = [    
    path("",views.conferencias,name='home'),
    path("login", auth_views.LoginView.as_view(template_name='submissao/login.html',next_page='',redirect_authenticated_user=True), name="login"),
    path("logout",views.logoutView,name='logout'),
    path("cadUser",views.cadUser, name="createUser"),
    path("conferencia/<slug>/",views.conferencia,name="conferencia"),
    path("conferencia/<slug>/<data>/",views.conferencia,name="conferenciaWithDate"),
    path("inscricao/<id>/",views.inscricao,name='inscricaoAtividade'),
    path("removerInscricao/<idAtv>/",views.removerInscricao,name='removerInscricao'),
    path("accounts/profile/",views.profile,name='perfil'),
    path("conferencias/",views.conferencias,name='confList'),
    path("inscritos/",view=views.visualizeSubscription,name='inscritos'),
    path("submissaoPaper/<slug>/",view=views.submissaoDesc,name='paginaSubmissao'),
    path("submissionForm/<slug>/",view=views.submissionForm,name='submissionForm'),
    path("accounts/papers/",view=views.artigos,name='artigos'),
    path("artigo/<id>/",view=views.detailsPaper,name='artigo'),
    path('atividade/<int:atvId>/participante/<int:partId>/presenca/', 
         views.generateQRCode, name='generateQRCode'),
    path('presenca/<int:atvId>/<int:partId>/', 
         views.contabilizarPresenca, name='presenca'),
]