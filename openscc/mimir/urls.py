from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from .viewsClasses.PerguntasTemplate import PerguntasView
from .viewsClasses.TemaListView import TemaListView
from .viewsClasses.ProblemasView import ProblemaListView, ProblemaDetailView, GerarProblemaView, ProblemaCreateView, RegerarParteView, ProblemaDeleteView, ProblemaDeleteAjaxView

app_name = 'mimir'

urlpatterns = [    
    path("",views.dashboardProfessor,name='home'),
    path('upload/', views.uploadFile, name='uploadFile'),
    path("gerarPerguntas/",views.generateQuestions,name='gerarPerguntas'),    
    path("removerUploadSource/",views.deleteFile,name='excluirFonte'),
    path("salvarPerguntas/",views.saveQuestion,name='salvarPerguntas'),
    path("dashboardProfessor/",views.dashboardProfessor,name='dashboardProfessor'),
    path("listarFontes/",views.visualizarFontes,name='visualizarFontes'),
    path("adicionarFonte/",views.addFonte,name='addFontes'),
    path('alterarFonte/<int:fonte_id>/', views.updateFonte, name='updateFonte'),
    path('deletarFonte/<int:fonte_id>/', views.deletarFonte, name='deletarFonte'),
    path('listarPerguntas/', PerguntasView.as_view(), name='visualizarPerguntas'),
    path('gerarPerguntasForm/', views.gerarPerguntas, name='gerarPerguntasForm'),
    path('salvarPerguntasForm/', views.salvarPerguntasForm, name='salvarPerguntasForm'),
    path('visualizarPerguntasFonte/<int:pID>/', views.visualizarPerguntasFonte, name='visualizarPergunta'),
    path('editarPergunta/<int:pID>/', views.editarPergunta, name='editarPergunta'),
    path('deletarPergunta/<int:pID>/', views.deletarPergunta, name='deletarPergunta'),
    path('criarProva/', views.criarProva, name='criarProva'),
    path('editarProva/<int:prova_id>/', views.editarProva, name='editarProva'),
    path('listarProvas/', views.listarProvas, name='listarProvas'),
    path('adicionarPerguntaExistente/<int:prova_id>/', views.adicionarPerguntaExistente, name='adicionarPerguntaExistente'),
    path('removerPerguntaProva/<int:prova_id>/<int:pergunta_id>/', views.removerPerguntaProva, name='removerPerguntaProva'),
    path('opcoesImpressao/<int:prova_id>/', views.opcoesImpressao, name='opcoesImpressao'),
    path('imprimirProva/<int:prova_id>/', views.imprimirProva, name='imprimirProva'),
    path('imprimirFolhaResposta/<int:prova_id>/', views.imprimirFolhaResposta, name='imprimirFolhaResposta'),
    path('imprimirGabarito/<int:prova_id>/', views.imprimirGabarito, name='imprimirGabarito') ,
    path('listarTemas/', TemaListView.as_view(), name='listarTemas'),
    path('criarTema/', views.temaCreate, name='criarTema'),
    path('editarTema/<int:pk>/', views.temaUpdate, name='editarTema'),
    path('deletarTema/<int:pk>/', views.temaDelete, name='deletarTema'), 
    path('problemas/', ProblemaListView.as_view(), name='problemaList'),  
    path('problema/novo/', ProblemaCreateView.as_view(), name='problemaCreate'),
    path('problema/gerar/', GerarProblemaView.as_view(), name='gerarProblema'),
    path('problema/<int:pk>/', ProblemaDetailView.as_view(), name='problemaDetail'),
    path('problema/<int:problema_id>/regerar-parte/', RegerarParteView.as_view(), name='regerarParte'),
    path('problema/<int:pk>/excluir/', ProblemaDeleteView.as_view(), name='problemaDelete'),
    path('problema/<int:pk>/delete-ajax/', ProblemaDeleteAjaxView.as_view(), name='problemaDeleteAjax'),
    path('problema/<int:problema_id>/regerar-parte/', RegerarParteView.as_view(), name='regerarParte'),
    path('problema/<int:problema_id>/regerar-parte/<int:parte_ordem>/', RegerarParteView.as_view(), name='regerarParteEspecifica'),
]