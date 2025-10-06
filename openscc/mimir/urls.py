from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from .viewsClasses.PerguntasTemplate import PerguntasView

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
    path('imprimirGabarito/<int:prova_id>/', views.imprimirGabarito, name='imprimirGabarito')    
]