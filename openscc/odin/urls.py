from django.urls import path
from . import views

app_name = 'odin'

urlpatterns = [
    # Dashboard
    path('', views.DashboardView.as_view(), name='dashboard'),
    
    # Cursos
    path('cursos/', views.CourseListView.as_view(), name='course_list'),
    path('cursos/novo/', views.CourseCreateView.as_view(), name='course_create'),
    path('cursos/<int:pk>/editar/', views.CourseUpdateView.as_view(), name='course_update'),
    
    # Disciplinas
    path('disciplinas/', views.DisciplineListView.as_view(), name='discipline_list'),
    path('disciplinas/nova/', views.DisciplineCreateView.as_view(), name='discipline_create'),
    path('disciplinas/<int:pk>/editar/', views.DisciplineUpdateView.as_view(), name='discipline_update'),
    
    # PPCs e Matriz Curricular
    path('ppcs/', views.PPCListView.as_view(), name='ppc_list'),
    path('ppcs/novo/', views.PPCCreateView.as_view(), name='ppc_create'),
    path('ppcs/<int:pk>/', views.PPCDetailView.as_view(), name='ppc_detail'),
    path('ppcs/<int:ppc_id>/adicionar-disciplina/', views.MatrixItemCreateView.as_view(), name='matrix_item_create'),

    # --- NOVAS ROTAS: Configurações Institucionais ---
    
    # Eixos Tecnológicos
    path('configuracoes/eixos/', views.TechnologicalAxisListView.as_view(), name='axis_list'),
    path('configuracoes/eixos/novo/', views.TechnologicalAxisCreateView.as_view(), name='axis_create'),
    
    # Modalidades
    path('configuracoes/modalidades/', views.ModalityListView.as_view(), name='modality_list'),
    path('configuracoes/modalidades/nova/', views.ModalityCreateView.as_view(), name='modality_create'),

    path('ppcs/<int:pk>/', views.PPCDetailView.as_view(), name='ppc_detail'),
    path('ppcs/<int:ppc_id>/adicionar-disciplina/', views.MatrixItemCreateView.as_view(), name='matrix_item_create'),
    # --- NOVA ROTA ---
    path('ppcs/item-matriz/<int:pk>/remover/', views.MatrixItemDeleteView.as_view(), name='matrix_item_delete'),

    path('configuracoes/eixos-formativos/', views.FormativeAxisListView.as_view(), name='formative_axis_list'),
    path('configuracoes/eixos-formativos/novo/', views.FormativeAxisCreateView.as_view(), name='formative_axis_create'),
    path('vestibular/', views.VestibularCampaignListView.as_view(), name='campaign_list'),
    path('vestibular/nova/', views.VestibularCampaignCreateView.as_view(), name='campaign_create'),
    path('vestibular/<int:pk>/', views.VestibularCampaignDetailView.as_view(), name='campaign_dashboard'),
    path('vestibular/<int:campaign_id>/registro/', views.DailyRecordCreateView.as_view(), name='daily_record_create'),

    # Adicione esta linha junto das outras rotas de vestibular:
    path('vestibular/<int:pk>/editar/', views.VestibularCampaignUpdateView.as_view(), name='campaign_update'),

# ... suas rotas anteriores ...

    # --- Visão do Coordenador: Criar Ação e Delegar ---
    path('vestibular/<int:campaign_id>/acao/nova/', views.CampaignActionCreateView.as_view(), name='action_create'),

    # --- Visão do Professor: Minhas Ações ---
    path('minhas-acoes/', views.MyActionsListView.as_view(), name='my_actions_list'),
    path('acao/<int:pk>/execucao/', views.ActionExecutionDetailView.as_view(), name='action_execution'),
    
    # --- Endpoints de Processamento (Forms da Execução) ---
    path('acao/<int:action_id>/despesa/', views.ActionExpenseCreateView.as_view(), name='action_expense_create'),
    path('acao/<int:action_id>/foto/', views.ActionPhotoCreateView.as_view(), name='action_photo_create'),
    path('acao/<int:action_id>/lead/', views.CampaignLeadCreateView.as_view(), name='action_lead_create'),
    # --- Base Central de Leads ---
    path('leads/', views.CampaignLeadListView.as_view(), name='lead_list'),
    path('leads/exportar/', views.ExportLeadsCSVView.as_view(), name='lead_export_csv'),
    # ==========================================
    # MÓDULO DE INICIAÇÃO CIENTÍFICA (IC)
    # ==========================================

    # --- 1. Visão do Aluno ---
    path('ic/meus-projetos/', views.StudentICListView.as_view(), name='ic_student_list'),
    path('ic/novo/', views.StudentICCreateView.as_view(), name='ic_student_create'),
    path('ic/<int:pk>/submeter/', views.StudentICSubmitView.as_view(), name='ic_student_submit'),
    # (Futuro) path('ic/<int:pk>/relatorio/', views.StudentICReportView.as_view(), name='ic_student_report'),

    # --- 2. Visão do Orientador ---
    path('ic/orientacoes-pendentes/', views.AdvisorICListView.as_view(), name='ic_advisor_list'),
    path('ic/<int:pk>/aceitar/', views.AdvisorAcceptView.as_view(), name='ic_advisor_accept'),
    # --- 3. Visão da CEPE (Comitê) ---
    path('ic/cepe/painel/', views.CEPEListView.as_view(), name='ic_cepe_list'),
    path('ic/cepe/<int:pk>/designar/', views.CEPEAssignReviewerView.as_view(), name='ic_cepe_assign'),
    # --- 4. Visão do Parecerista Ad-hoc ---
    path('ic/pareceres-pendentes/', views.ReviewerPendingListView.as_view(), name='ic_reviewer_list'),
    path('ic/<int:pk>/avaliar/', views.ReviewerEvaluateView.as_view(), name='ic_reviewer_evaluate'),
    # --- 3. Visão da CEPE (Comitê) ---
    path('ic/cepe/painel/', views.CEPEListView.as_view(), name='ic_cepe_list'),
    path('ic/cepe/<int:pk>/designar/', views.CEPEAssignReviewerView.as_view(), name='ic_cepe_assign'),
    path('ic/cepe/<int:pk>/alterar-parecerista/', views.CEPEChangeReviewerView.as_view(), name='ic_cepe_change_reviewer'), # <--- NOVA ROTA
    path('ic/cepe/<int:pk>/julgar/', views.CEPEDecisionView.as_view(), name='ic_cepe_decision'),

    # --- 4. Visão do Parecerista Ad-hoc ---
    path('ic/parecerista/painel/', views.ReviewerICListView.as_view(), name='ic_reviewer_list'),
    path('ic/parecerista/<int:pk>/avaliar/', views.ReviewerEvaluateView.as_view(), name='ic_reviewer_evaluate'),
    path('ic/parecerista/<int:pk>/recusar/', views.ReviewerRefuseView.as_view(), name='ic_reviewer_refuse'), # <--- NOVA ROTA AQUI
]