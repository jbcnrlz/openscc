import csv, datetime
from django.http import HttpResponse
from django.views import View
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, ListView, CreateView, DetailView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from .models import *
from .forms import *
from django.shortcuts import redirect
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings

class StudentRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Garante que o usuário logado seja um Aluno"""
    login_url = '/admin/login/'
    
    def test_func(self):
        return self.request.user.isAluno()

# --- Mixin de Segurança ---
class ProfessorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Garante que o usuário esteja logado e seja da equipe/professor"""
    login_url = '/admin/login/'
    
    def test_func(self):
        # Regra de acesso: precisa ser professor para acessar as views de ODIN. O método isProfessor() é adicionado dinamicamente ao User via monkey patching no models.py
        return self.request.user.isProfessor()

# --- 1. Dashboard ---
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'odin/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        
        # Checagens dinâmicas de papéis usando os métodos injetados no User
        is_aluno = hasattr(user, 'isAluno') and user.isAluno()
        is_cepe = hasattr(user, 'isMembroCEPE') and user.isMembroCEPE()
        
        context['is_aluno'] = is_aluno
        context['is_cepe'] = is_cepe

        if is_aluno:
            # ==========================================
            # MÉTRICAS EXCLUSIVAS DO ALUNO
            # ==========================================
            context['my_active_ic'] = ScientificProject.objects.filter(
                student=user, status='IN_PROGRESS'
            ).count()
            
            context['my_pending_ic'] = ScientificProject.objects.filter(
                student=user
            ).exclude(
                status__in=['IN_PROGRESS', 'FINISHED', 'REJECTED', 'REPORT_SUBMITTED']
            ).count()
            
        else:
            # ==========================================
            # MÉTRICAS DE COORDENAÇÃO E CAPTAÇÃO
            # ==========================================
            context['total_courses'] = Course.objects.filter(professor=user).count()
            context['total_disciplines'] = Discipline.objects.count() # Catálogo Global
            context['active_ppcs'] = PPCProposal.objects.filter(course__professor=user, is_active=True).count()
            context['active_campaigns'] = VestibularCampaign.objects.filter(created_by=user).count()
            
            # ==========================================
            # MÉTRICAS DE PESQUISA (Orientação e Ad-hoc)
            # ==========================================
            context['pending_advising'] = ScientificProject.objects.filter(advisor=user, status='PENDING_ADVISOR').count()
            context['pending_reviews'] = ScientificProject.objects.filter(reviewer=user, status='UNDER_REVIEW').count()
            
            # ==========================================
            # MÉTRICAS EXCLUSIVAS DA CEPE
            # ==========================================
            if is_cepe:
                context['cepe_queue'] = ScientificProject.objects.filter(status='SUBMITTED_CEPE').count()

        return context

# --- 2. Gestão de Cursos ---
class CourseListView(ProfessorRequiredMixin, ListView):
    model = Course
    template_name = 'odin/course_list.html'
    context_object_name = 'courses'
    
    def get_queryset(self):
        # Isolamento: Retorna APENAS os cursos do professor logado
        return Course.objects.filter(professor=self.request.user).order_by('name')

class CourseCreateView(ProfessorRequiredMixin, CreateView):
    model = Course
    form_class = CourseForm
    template_name = 'odin/course_form.html'
    success_url = reverse_lazy('odin:course_list')

    def form_valid(self, form):
        # Força o dono do curso a ser o usuário logado
        form.instance.professor = self.request.user
        return super().form_valid(form)

# --- 3. Gestão de Disciplinas (Catálogo) ---
class DisciplineListView(ProfessorRequiredMixin, ListView):
    model = Discipline
    template_name = 'odin/discipline_list.html'
    context_object_name = 'disciplines'

    def get_queryset(self):
        return Discipline.objects.all().order_by('name')

class DisciplineCreateView(ProfessorRequiredMixin, CreateView):
    model = Discipline
    form_class = DisciplineForm
    template_name = 'odin/discipline_form.html'
    success_url = reverse_lazy('odin:discipline_list')

class DisciplineUpdateView(ProfessorRequiredMixin, UpdateView):
    model = Discipline
    form_class = DisciplineForm
    template_name = 'odin/discipline_form.html'
    success_url = reverse_lazy('odin:discipline_list')

    def get_queryset(self):
        # SEGURANÇA: Garante que o professor só possa acessar a página de edição 
        # se a disciplina estiver vinculada a um curso dele. Se ele tentar acessar 
        # o ID de uma disciplina de outro professor, o Django retorna Erro 404.
        return Discipline.objects.all()
    
    def get_form_kwargs(self):
        # Injeta o usuário logado no formulário para filtrar os combos de Cursos e Pré-requisitos
        kwargs = super().get_form_kwargs()
        return kwargs

# --- 4. Gestão de PPCs ---
class PPCListView(ProfessorRequiredMixin, ListView):
    model = PPCProposal
    template_name = 'odin/ppc_list.html'
    context_object_name = 'ppcs'

    def get_queryset(self):
        # Agora retorna TODOS os PPCs do sistema, não apenas os do utilizador logado
        return PPCProposal.objects.all().order_by('-created_at')

class PPCCreateView(ProfessorRequiredMixin, CreateView):
    model = PPCProposal
    form_class = PPCProposalForm
    template_name = 'odin/ppc_form.html'
    success_url = reverse_lazy('odin:ppc_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        return kwargs

class PPCDetailView(ProfessorRequiredMixin, DetailView):
    model = PPCProposal
    template_name = 'odin/ppc_detail.html'
    context_object_name = 'ppc'

    def get_queryset(self):
        # Permite que qualquer professor acesse os detalhes de qualquer PPC
        return PPCProposal.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        matrix_items = self.object.matrix_items.select_related('discipline').order_by('semester', 'discipline__name')
        semesters = {}
        for item in matrix_items:
            if item.semester not in semesters:
                semesters[item.semester] = []
            semesters[item.semester].append(item)
            
        context['semesters'] = semesters
        
        # --- LÓGICA DE PERMISSÃO ---
        # Verifica se o utilizador logado é o professor dono do curso
        is_owner = self.object.course.professor == self.request.user
        context['is_owner'] = is_owner
        
        # Só injeta o formulário de montagem se for o dono
        if is_owner:
            context['matrix_form'] = CurriculumMatrixForm()
            
        return context

# --- 5. Adição de Disciplinas na Grade ---
class MatrixItemCreateView(ProfessorRequiredMixin, CreateView):
    """View sem template, processa o envio do form de alocação no PPCDetailView"""
    model = CurriculumMatrix
    form_class = CurriculumMatrixForm

    def form_valid(self, form):
        # 1. Recupera o ID do PPC via URL
        ppc_id = self.kwargs.get('ppc_id')
        # 2. Verifica se o PPC realmente existe e pertence a este professor (segurança)
        ppc = get_object_or_404(PPCProposal, id=ppc_id, course__professor=self.request.user)
        
        # 3. Associa a disciplina a este PPC e salva
        form.instance.ppc = ppc
        return super().form_valid(form)

    def get_success_url(self):
        # Retorna para a aba do PPC após adicionar
        return reverse_lazy('odin:ppc_detail', kwargs={'pk': self.kwargs['ppc_id']})

# --- Gestão de Eixos Tecnológicos ---
class TechnologicalAxisListView(ProfessorRequiredMixin, ListView):
    model = TechnologicalAxis
    template_name = 'odin/axis_list.html'
    context_object_name = 'axes'

class TechnologicalAxisCreateView(ProfessorRequiredMixin, CreateView):
    model = TechnologicalAxis
    fields = ['name', 'description'] # Podemos usar os fields padrão para acelerar
    template_name = 'odin/generic_form.html' # Um template genérico salva tempo aqui!
    success_url = reverse_lazy('odin:axis_list')

# --- Gestão de Modalidades ---
class ModalityListView(ProfessorRequiredMixin, ListView):
    model = Modality
    template_name = 'odin/modality_list.html'
    context_object_name = 'modalities'

class ModalityCreateView(ProfessorRequiredMixin, CreateView):
    model = Modality
    fields = ['name']
    template_name = 'odin/generic_form.html'
    success_url = reverse_lazy('odin:modality_list')

class CourseUpdateView(ProfessorRequiredMixin, UpdateView):
    model = Course
    form_class = CourseForm
    template_name = 'odin/course_form.html'
    success_url = reverse_lazy('odin:course_list')

    def get_queryset(self):
        # SEGURANÇA: Retorna apenas os cursos que pertencem ao professor logado.
        # Se tentarem acessar a URL de edição de um curso de outro professor, dará Erro 404.
        return Course.objects.filter(professor=self.request.user)
    
class MatrixItemDeleteView(ProfessorRequiredMixin, DeleteView):
    """Remove uma disciplina da grade do PPC"""
    model = CurriculumMatrix

    def get_queryset(self):
        # Segurança: só pode remover se o PPC pertencer a um curso do professor logado
        return CurriculumMatrix.objects.filter(ppc__course__professor=self.request.user)

    def get_success_url(self):
        # Redireciona de volta para a tela de detalhes do PPC
        return reverse_lazy('odin:ppc_detail', kwargs={'pk': self.object.ppc.id})
    
# --- Gestão de Eixos Formativos ---
class FormativeAxisListView(ProfessorRequiredMixin, ListView):
    model = FormativeAxis
    template_name = 'odin/formative_axis_list.html'
    context_object_name = 'axes'

class FormativeAxisCreateView(ProfessorRequiredMixin, CreateView):
    model = FormativeAxis
    form_class = FormativeAxisForm
    template_name = 'odin/generic_form.html' # Reaproveitamos o form genérico!
    success_url = reverse_lazy('odin:formative_axis_list')


# --- Gestão de Captação (Vestibular) ---

class VestibularCampaignListView(ProfessorRequiredMixin, ListView):
    model = VestibularCampaign
    template_name = 'odin/campaign_list.html'
    context_object_name = 'campaigns'

    def get_queryset(self):
        return VestibularCampaign.objects.filter(created_by=self.request.user).order_by('-start_date')
    
class VestibularCampaignCreateView(ProfessorRequiredMixin, CreateView):
    model = VestibularCampaign
    form_class = VestibularCampaignForm
    template_name = 'odin/campaign_form.html'
    success_url = reverse_lazy('odin:campaign_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)

class VestibularCampaignDetailView(ProfessorRequiredMixin, DetailView):
    """Esta View atua como o Painel de Previsão de Demanda (Yield Dashboard)"""
    model = VestibularCampaign
    template_name = 'odin/campaign_dashboard.html'
    context_object_name = 'campaign'

    def get_queryset(self):
        return VestibularCampaign.objects.filter(course__professor=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Injeta o motor matemático na view
        context['projections'] = self.object.get_yield_projections()
        
        # Histórico de registros diários
        context['records'] = self.object.daily_records.all()
        
        # Formulário para inserir dados diários rapidamente na mesma tela
        context['record_form'] = CampaignDailyRecordForm()
        
        return context

class DailyRecordCreateView(ProfessorRequiredMixin, CreateView):
    """Processa o formulário de novos pagantes do dia sem sair do painel"""
    model = CampaignDailyRecord
    form_class = CampaignDailyRecordForm

    def form_valid(self, form):
        campaign = get_object_or_404(VestibularCampaign, id=self.kwargs.get('campaign_id'), course__professor=self.request.user)
        form.instance.campaign = campaign
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('odin:campaign_dashboard', kwargs={'pk': self.kwargs['campaign_id']})

class VestibularCampaignUpdateView(ProfessorRequiredMixin, UpdateView):
    model = VestibularCampaign
    form_class = VestibularCampaignForm
    template_name = 'odin/campaign_form.html'

    def get_success_url(self):
        # Após salvar, redireciona de volta para o dashboard daquela campanha
        return reverse_lazy('odin:campaign_dashboard', kwargs={'pk': self.object.id})

# ==========================================
# 1. VISÃO DO COORDENADOR (Planejamento)
# ==========================================

class CampaignActionCreateView(ProfessorRequiredMixin, CreateView):
    """Coordenador cria uma ação dentro de uma campanha e delega a um professor"""
    model = CampaignAction
    form_class = CampaignActionForm
    template_name = 'odin/generic_form.html'
    
    def form_valid(self, form):
        # Vincula a ação à campanha atual da URL
        campaign = get_object_or_404(VestibularCampaign, id=self.kwargs.get('campaign_id'))
        form.instance.campaign = campaign
        return super().form_valid(form)

    def get_success_url(self):
        # Retorna para o dashboard da campanha
        return reverse_lazy('odin:campaign_dashboard', kwargs={'pk': self.kwargs['campaign_id']})

# ==========================================
# 2. VISÃO DO PROFESSOR (Execução em Campo)
# ==========================================

class MyActionsListView(ProfessorRequiredMixin, ListView):
    """Lista apenas as ações onde o usuário logado é o responsável"""
    model = CampaignAction
    template_name = 'odin/my_actions_list.html'
    context_object_name = 'actions'

    def get_queryset(self):
        # Filtro de segurança: traz apenas as ações delegadas para mim, ordenadas pela data
        return CampaignAction.objects.filter(responsible=self.request.user).order_by('scheduled_date')

class ActionExecutionDetailView(ProfessorRequiredMixin, DetailView):
    """Painel de Execução da Ação (Upload de fotos, gastos e leads)"""
    model = CampaignAction
    template_name = 'odin/action_execution.html'
    context_object_name = 'action'

    def get_queryset(self):
        # Garante que o professor só consiga abrir os detalhes das próprias ações
        return CampaignAction.objects.filter(responsible=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Injeta os 3 formulários vazios para o professor usar na mesma tela
        context['expense_form'] = ActionExpenseForm()
        context['photo_form'] = ActionPhotoForm()
        context['lead_form'] = CampaignLeadForm()
        
        return context

# ==========================================
# 3. PROCESSADORES DE FORMULÁRIOS (Endpoints)
# ==========================================

class ActionExpenseCreateView(ProfessorRequiredMixin, CreateView):
    model = ActionExpense
    form_class = ActionExpenseForm
    
    def form_valid(self, form):
        action = get_object_or_404(CampaignAction, id=self.kwargs.get('action_id'), responsible=self.request.user)
        form.instance.action = action
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('odin:action_execution', kwargs={'pk': self.kwargs['action_id']})

class CampaignLeadCreateView(ProfessorRequiredMixin, CreateView):
    model = CampaignLead
    form_class = CampaignLeadForm
    
    def form_valid(self, form):
        action = get_object_or_404(CampaignAction, id=self.kwargs.get('action_id'), responsible=self.request.user)
        form.instance.source_action = action
        form.instance.campaign = action.campaign # O lead pertence à campanha matriz
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('odin:action_execution', kwargs={'pk': self.kwargs['action_id']})

class ActionPhotoCreateView(ProfessorRequiredMixin, CreateView):
    model = ActionPhoto
    form_class = ActionPhotoForm
    
    def form_valid(self, form):
        action = get_object_or_404(CampaignAction, id=self.kwargs.get('action_id'), responsible=self.request.user)
        form.instance.action = action
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('odin:action_execution', kwargs={'pk': self.kwargs['action_id']})


class CampaignLeadListView(ProfessorRequiredMixin, ListView):
    """Visualização consolidada de todos os interessados (Leads)"""
    model = CampaignLead
    template_name = 'odin/lead_list.html'
    context_object_name = 'leads'

    def get_queryset(self):
        # Traz todos os leads das campanhas que pertencem aos cursos deste coordenador
        return CampaignLead.objects.filter(
            campaign__course__professor=self.request.user
        ).select_related(
            'campaign', 'source_action', 'interested_course'
        ).order_by('-created_at')

class ExportLeadsCSVView(ProfessorRequiredMixin, View):
    """Gera o arquivo CSV formatado para abrir perfeitamente no Excel pt-BR"""
    
    def get(self, request, *args, **kwargs):
        # Configura o tipo de resposta para forçar o download
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="base_de_leads_odin.csv"'
        
        # Adiciona o BOM (Byte Order Mark) para o Excel reconhecer os acentos (UTF-8)
        response.write(u'\ufeff'.encode('utf8'))
        
        # Usa ponto e vírgula para separar as colunas (Padrão Brasil do Excel)
        writer = csv.writer(response, delimiter=';')
        
        # Escreve o Cabeçalho
        writer.writerow([
            'Data de Cadastro', 
            'Campanha', 
            'Ação de Origem', 
            'Nome Completo', 
            'Celular / WhatsApp', 
            'E-mail', 
            'Curso de Interesse',
            'Contato Realizado?',
            'Conversão (Pago)?'
        ])
        
        # Busca os mesmos dados da tabela
        leads = CampaignLead.objects.filter(
            campaign__course__professor=request.user
        ).select_related('campaign', 'source_action', 'interested_course').order_by('-created_at')
        
        # Escreve as linhas
        for lead in leads:
            writer.writerow([
                lead.created_at.strftime('%d/%m/%Y %H:%M'),
                lead.campaign.name,
                lead.source_action.title if lead.source_action else 'Orgânico / Direto',
                lead.name,
                lead.phone,
                lead.email,
                lead.interested_course.name if lead.interested_course else 'Não informado',
                'Sim' if lead.contacted else 'Não',
                'Sim' if lead.converted_to_paid else 'Não'
            ])
            
        return response

# --- VISÃO DO ALUNO ---

class StudentICListView(StudentRequiredMixin, ListView):
    """Aluno visualiza seus próprios projetos"""
    model = ScientificProject
    template_name = 'odin/ic_student_list.html'
    context_object_name = 'projects'

    def get_queryset(self):
        return ScientificProject.objects.filter(student=self.request.user)

class StudentICCreateView(StudentRequiredMixin, CreateView):
    """PASSO 1: Aluno cria o projeto e escolhe orientador"""
    model = ScientificProject
    form_class = ICProjectCreateForm
    template_name = 'odin/ic_student_create_form.html' # <--- NOVO TEMPLATE DEDICADO
    success_url = reverse_lazy('odin:ic_student_list')

    def form_valid(self, form):
        form.instance.student = self.request.user
        form.instance.status = 'PENDING_ADVISOR'
        response = super().form_valid(form)
        
        # GATILHO DE E-MAIL (mantido): Avisa o Orientador
        send_mail(
            subject='Odin: Novo Convite de Orientação de IC',
            message=f"Olá Prof. {form.instance.advisor.first_name},\n\nO aluno {self.request.user.get_full_name()} convidou você para orientar o projeto '{form.instance.title}'.\n\nAcesse o painel para aceitar ou recusar.\n\nEquipe CEPE",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[form.instance.advisor.email],
            fail_silently=True,
        )
        return response

class StudentICSubmitView(StudentRequiredMixin, UpdateView):
    """PASSO 3: Aluno faz upload do projeto (Apenas envio inicial)"""
    model = ScientificProject
    form_class = ICProjectSubmitForm
    template_name = 'odin/ic_student_submit_form.html' # <--- NOVO TEMPLATE
    success_url = reverse_lazy('odin:ic_student_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['step'] = 2  # Indica para o HTML que é o passo 2
        return context

    def get_queryset(self):
        return ScientificProject.objects.filter(
            student=self.request.user, 
            status='ADVISOR_ACCEPTED'
        )

    def form_valid(self, form):
        form.instance.status = 'SUBMITTED_CEPE'
        return super().form_valid(form)

class AdvisorAcceptView(ProfessorRequiredMixin, View):
    def post(self, request, pk):
        project = get_object_or_404(ScientificProject, pk=pk, advisor=request.user, status='PENDING_ADVISOR')
        project.status = 'ADVISOR_ACCEPTED'
        project.save()
        
        # GATILHO DE E-MAIL: Avisa o Aluno
        send_mail(
            subject='Odin: Convite de Orientação Aceito!',
            message=f"Olá {project.student.first_name},\n\nÓtima notícia! O Prof. {request.user.get_full_name()} aceitou o convite para orientar o seu projeto '{project.title}'.\n\nAgora você já pode acessar o sistema Odin e realizar o upload (envio) da sua proposta em PDF para avaliação da CEPE.\n\nAtenciosamente,\nEquipe CEPE",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[project.student.email],
            fail_silently=True,
        )
        
        return redirect('odin:ic_advisor_list')

class ReviewerPendingListView(ProfessorRequiredMixin, ListView):
    """Parecerista visualiza projetos a ele designados"""
    model = ScientificProject
    template_name = 'odin/ic_reviewer_list.html'
    context_object_name = 'projects'

    def get_queryset(self):
        return ScientificProject.objects.filter(reviewer=self.request.user, status='UNDER_REVIEW')

class ReviewerEvaluateView(ProfessorRequiredMixin, UpdateView):
    """PASSO 5: Parecerista apenas emite o texto (não julga)"""
    model = ScientificProject
    form_class = ReviewerEvaluationForm
    template_name = 'odin/generic_form.html'
    success_url = reverse_lazy('odin:ic_reviewer_list')

    def get_queryset(self):
        return ScientificProject.objects.filter(reviewer=self.request.user, status='UNDER_REVIEW')

    def form_valid(self, form):
        form.instance.status = 'REVIEWED' # Devolve para a CEPE ler o parecer
        return super().form_valid(form)

class CEPEDecisionView(ProfessorRequiredMixin, UpdateView):
    model = ScientificProject
    form_class = CEPEDecisionForm
    template_name = 'odin/generic_form.html'
    success_url = reverse_lazy('odin:ic_cepe_list')

    def get_queryset(self):
        return ScientificProject.objects.filter(status='REVIEWED')

    def form_valid(self, form):
        form.instance.cepe_reviewer = self.request.user

        if form.instance.status in ['IN_PROGRESS', 'CHANGES_REQUESTED']:
            start = form.cleaned_data.get('start_date')
            form.instance.start_date = start
            if start:
                form.instance.end_date = start + datetime.timedelta(days=365)
        else:
            form.instance.start_date = None
            form.instance.end_date = None
            
        response = super().form_valid(form)
        
        # GATILHO DE E-MAIL: Avisa a dupla (Aluno e Orientador)
        status_nome = form.instance.get_status_display()
        send_mail(
            subject=f"Odin: Resultado CEPE - {status_nome}",
            message=f"Olá,\n\nA CEPE finalizou o julgamento do projeto '{form.instance.title}'.\n\nResultado Final: {status_nome}.\n\nAcesse o sistema Odin para ler os comentários detalhados e verificar os próximos passos da sua pesquisa.\n\nAtenciosamente,\nComitê de Pesquisa",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[form.instance.student.email, form.instance.advisor.email],
            fail_silently=True,
        )
        return response
    # --- VISÃO DA CEPE (Comitê) ---
class CEPEListView(ProfessorRequiredMixin, ListView):
    """Painel completo da CEPE"""
    model = ScientificProject
    template_name = 'odin/ic_cepe_list.html'
    context_object_name = 'pending_projects' # Aba 1: Sem parecerista

    def get_queryset(self):
        return ScientificProject.objects.filter(status='SUBMITTED_CEPE')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Aba 2: Projetos com parecer emitido, esperando o Deferimento da CEPE
        context['ready_for_decision'] = ScientificProject.objects.filter(status='REVIEWED')
        
        # Aba 3: Histórico (Em andamento, rejeitados, etc)
        context['tracked_projects'] = ScientificProject.objects.exclude(
            status__in=['DRAFT', 'PENDING_ADVISOR', 'ADVISOR_ACCEPTED', 'SUBMITTED_CEPE', 'REVIEWED']
        ).select_related('student', 'advisor', 'reviewer').order_by('-id')
        
        return context
        
class CEPEAssignReviewerView(ProfessorRequiredMixin, UpdateView):
    model = ScientificProject
    form_class = CEPEAssignReviewerForm
    template_name = 'odin/generic_form.html'
    success_url = reverse_lazy('odin:ic_cepe_list')

    def get_queryset(self):
        return ScientificProject.objects.filter(status='SUBMITTED_CEPE')

    def form_valid(self, form):
        form.instance.status = 'UNDER_REVIEW'
        response = super().form_valid(form)
        
        # GATILHO DE E-MAIL: Avisa o Parecerista
        send_mail(
            subject='Odin: Designação de Parecer Ad-hoc',
            message=f"Olá Prof. {form.instance.reviewer.first_name},\n\nA CEPE designou você como parecerista técnico ad-hoc para o projeto de Iniciação Científica '{form.instance.title}'.\n\nPor favor, acesse a aba 'Meus Pareceres' no sistema Odin para baixar a proposta e emitir sua avaliação técnica.\n\nAtenciosamente,\nComitê de Pesquisa",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[form.instance.reviewer.email],
            fail_silently=True,
        )
        return response

class CEPEChangeReviewerView(ProfessorRequiredMixin, UpdateView):
    """CEPE troca o parecerista de um projeto que já está em avaliação"""
    model = ScientificProject
    form_class = CEPEAssignReviewerForm
    template_name = 'odin/generic_form.html'
    success_url = reverse_lazy('odin:ic_cepe_list')

    def get_queryset(self):
        # Só permite trocar se o projeto estiver aguardando o parecer (UNDER_REVIEW)
        return ScientificProject.objects.filter(status='UNDER_REVIEW')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Uma pequena ajuda visual no cabeçalho do formulário genérico
        context['title'] = f"Alterar Parecerista: {self.object.title}"
        return context
        
    def form_valid(self, form):
        # Apenas salva o novo professor. O status já é 'UNDER_REVIEW', então não mexemos.
        return super().form_valid(form)

# --- Atualize a View do Orientador ---
class AdvisorICListView(ProfessorRequiredMixin, ListView):
    """Orientador aceita convites e acompanha seus orientandos"""
    model = ScientificProject
    template_name = 'odin/ic_advisor_list.html'
    context_object_name = 'pending_projects'

    def get_queryset(self):
        # Aba 1: Aguardando aceite do professor
        return ScientificProject.objects.filter(advisor=self.request.user, status='PENDING_ADVISOR')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Aba 2: Projetos que o professor já aceitou orientar (em andamento, avaliação, etc)
        context['tracked_projects'] = ScientificProject.objects.filter(
            advisor=self.request.user
        ).exclude(status='PENDING_ADVISOR').order_by('-id')
        return context

class ReviewerRefuseView(ProfessorRequiredMixin, View):
    """Parecerista recusa o convite e o projeto volta para a fila da CEPE"""
    
    def post(self, request, pk, *args, **kwargs):
        # Garante que o projeto pertence ao usuário logado e está aguardando avaliação
        project = get_object_or_404(
            ScientificProject, 
            pk=pk, 
            reviewer=request.user, 
            status='UNDER_REVIEW'
        )
        
        # Remove o parecerista atual e volta o status para a CEPE
        project.reviewer = None
        project.status = 'SUBMITTED_CEPE'
        project.save()
        
        messages.success(request, f"Você recusou a avaliação do projeto '{project.title}'. Ele foi devolvido à fila da CEPE.")
        return redirect('odin:ic_reviewer_list')

class ReviewerICListView(ProfessorRequiredMixin, ListView):
    """Painel onde o professor visualiza os projetos designados a ele para parecer ad-hoc"""
    model = ScientificProject
    template_name = 'odin/ic_reviewer_list.html'
    context_object_name = 'projects'

    def get_queryset(self):
        # Traz apenas os projetos que estão na mesa deste professor para avaliar
        return ScientificProject.objects.filter(
            reviewer=self.request.user, 
            status='UNDER_REVIEW'
        ).order_by('-id')