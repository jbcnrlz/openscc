from django.urls import path
from . import views

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
]