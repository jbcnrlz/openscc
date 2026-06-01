from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

app_name = 'submission'

urlpatterns = [    
     path("",views.conferencias,name='home'),
     path(
     "login/",
     auth_views.LoginView.as_view(
          template_name='submissao/login.html',
          redirect_authenticated_user=True
     ),
     name="login"
     ),
     path("logout/",views.logoutView,name='logout'),
     path("cadUser/",views.cadUser, name="createUser"),
     path("conferencia/<slug:slug>/",views.conferencia,name="conferencia"),
     path("conferencia/<slug:slug>/<str:data>/",views.conferencia,name="conferenciaWithDate"),
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
     path('atividade/<int:id>/inscricao/', views.inscricao, name='inscricaoAtividade'),
     path('atividade/<int:idAtv>/remover/', views.removerInscricao, name='removerInscricao'),
     path('submission-status/<slug:slug>/', views.submissionStatus, name='submission_status'),
     path('certificados/', views.meusCertificados, name='meusCertificados'),
     path('certificado/<uuid:codigo_validacao>/', views.visualizarCertificado, name='visualizarCertificado'),
     path('certificado/validar/<uuid:codigo_validacao>/', views.validarCertificado, name='validarCertificado'),
     path('certificado/<uuid:codigo>/pdf/', views.gerarPdfCertificado, name='gerarPdfCertificado'),
     path('validar-certificado/<uuid:codigo_validacao>/', views.validarCertificado, name='validarCertificado'),
     path('atividade/<int:idAtv>/emitir-certificado/', views.emitirCertificadoAtividade, name='emitirCertificadoAtividade'),
     #path('certificado/emitir/<int:atividade_id>/', views.emitirCertificado, name='emitirCertificado'),
     #path('certificado/<uuid:codigo_validacao>/pdf/', views.gerarPdfCertificado, name='gerarPdfCertificado'),
     #path('admin/certificados/relatorio/', views.relatorioCertificados, name='relatorioCertificados'),
     #path('admin/certificados/relatorio/<slug:conferencia_slug>/', views.relatorioCertificados, name='relatorioCertificadosConferencia'),
     #path('admin/certificados/emitir-em-massa/<int:atividade_id>/', views.emitirCertificadosEmMassa, name='emitirCertificadosEmMassa'),
     #path('admin/certificados/configuracoes/', views.gerenciarConfiguracoes, name='gerenciarConfiguracoes'),
# URLs de layouts e geração automática
     #path('admin/certificados/layouts/<int:conferencia_id>/', views.gerenciarLayoutsCertificado, name='gerenciar_layouts_certificado'),
     #path('admin/certificados/layout/<int:layout_id>/editar/', views.editarLayoutCertificado, name='editar_layout_certificado'),
     #path('admin/certificados/layout/<int:layout_id>/aplicar-todos/', views.aplicarLayoutTodos, name='aplicar_layout_a_todos'),
     #path('admin/certificados/especiais/<int:conferencia_id>/', views.gerarCertificadosEspeciais, name='gerar_certificados_especiais'),
]