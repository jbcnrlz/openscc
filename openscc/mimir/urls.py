from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from .viewsClasses.PerguntasTemplate import PerguntasView
from .viewsClasses.TemaListView import TemaListView
from .viewsClasses.ProblemasView import ProblemaListView, ProblemaDetailView, GerarProblemaView, ProblemaCreateView, RegerarParteView, ProblemaDeleteView, ProblemaDeleteAjaxView
from .viewsClasses.GuiaTutorView import GerarGuiaTutorView, VisualizarGuiaTutorView, AtualizarGuiaTutorView
from .viewsClasses.ExportarPDFView import ExportarProblemaPDFView, ExportarGuiaTutorPDFView, ExportarCompletoPDFView
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
     path('problema/<int:problema_id>/gerar-guia-tutor/', GerarGuiaTutorView.as_view(), name='gerarGuiaTutor'),
     path('problema/<int:pk>/guia-tutor/', VisualizarGuiaTutorView.as_view(), name='visualizarGuiaTutor'),
     path('problema/<int:problema_id>/atualizar-guia-tutor/', AtualizarGuiaTutorView.as_view(), name='atualizarGuiaTutor'),
     path('problema/<int:problema_id>/exportar-pdf/', ExportarProblemaPDFView.as_view(), name='exportarPDF'),
     path('problema/<int:problema_id>/exportar-guia-pdf/', ExportarGuiaTutorPDFView.as_view(), name='exportarGuiaPDF'),
     path('problema/<int:problema_id>/exportar-completo-pdf/', ExportarCompletoPDFView.as_view(), name='exportarCompletoPDF'),
     path('problema/<int:problema_id>/parte/<int:parte_ordem>/solicitar-feedback/', views.solicitarFeedback, name='solicitarFeedback'),
     path('problema/<int:problema_id>/parte/<int:parte_ordem>/feedbacks/', views.visualizarFeedbacksParte, name='visualizarFeedbacksParte'),
     path('feedback/<int:feedback_id>/marcar-utilizado/', views.marcarFeedbackUtilizado, name='marcarFeedbackUtilizado'),
     path('feedback/<int:feedback_id>/responder/', views.responderFeedback, name='responderFeedback'),
     path('feedback/<int:feedback_id>/fornecer/', views.fornecerFeedback, name='fornecerFeedback'),
     path('feedback/<int:feedback_id>/excluir/', views.excluirFeedback, name='excluirFeedback'),
     path('meus-feedbacks/', views.meusFeedbacks, name='meusFeedbacks'),
     # Adicione estas URLs no urls.py
     path('prova/<int:prova_id>/pergunta/<int:pergunta_id>/solicitar-feedback/', 
          views.solicitarFeedbackPergunta, name='solicitarFeedbackPergunta'),
     path('prova/<int:prova_id>/pergunta/<int:pergunta_id>/feedbacks/', 
          views.visualizarFeedbacksPergunta, name='visualizarFeedbacksPergunta'),
     path('aceitar-feedback/<int:feedback_id>/', views.aceitarFeedback, name='aceitarFeedback'),
     path('rejeitar-feedback/<int:feedback_id>/', views.rejeitarFeedback, name='rejeitarFeedback'),
     path('visualizar-prova/<int:prova_id>/', views.visualizarProvaEspecialista, name='visualizarProvaEspecialista'),
     path('visualizar-prova/<int:prova_id>/feedback/<int:feedback_id>/', views.visualizarProvaEspecialista, name='visualizarProvaEspecialistaComFeedback'),
]