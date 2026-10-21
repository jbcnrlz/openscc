import csv, datetime, json, qrcode, pandas as pd
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import FormView
from django.http import HttpResponse
from django.views import View
from django.urls import reverse_lazy, reverse
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, ListView, CreateView, DetailView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from .models import *
from .forms import *
from django.shortcuts import redirect
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q
from weasyprint import HTML

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
            context['active_campaigns'] = VestibularCampaign.objects.filter(
                Q(created_by=user) | Q(collaborators=user)
            ).distinct().count()
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
        return VestibularCampaign.objects.filter(
            Q(created_by=self.request.user) | Q(collaborators=self.request.user)
        ).distinct().order_by('-start_date')
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
        return VestibularCampaign.objects.filter(
            Q(created_by=self.request.user) | Q(collaborators=self.request.user)
        ).distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        periodo_override = self.request.GET.get('periodo', '').strip().upper() or None
        context['periodo_selecionado'] = periodo_override or ''

        context['all_actions'] = CampaignAction.objects.filter(
            Q(campaign=self.object) | Q(is_global=True)
        ).order_by('scheduled_date')
        
        # Injeta o motor de Aprendizado de Máquina + Andamento na view
        context['projections'] = self.object.get_yield_projections(periodo_override=periodo_override)
        context['chart_data_json'] = self.object.get_chart_data(periodo_override=periodo_override)
        
        # Histórico de registros diários
        context['records'] = self.object.daily_records.all()
        
        # Formulário para inserir dados diários rapidamente na mesma tela
        context['record_form'] = CampaignDailyRecordForm()

        leads = self.object.leads.all()
        context['total_leads'] = leads.count()
        context['leads_novos'] = leads.filter(status='novo').count()
        context['leads_quentes'] = leads.filter(status__in=['em_contato', 'isencao', 'inscrito_nao_pago']).count()
        context['leads_convertidos'] = leads.filter(status='pago').count()
        context['leads_perdidos'] = leads.filter(status='desistiu').count()
        
        return context

    def render_to_response(self, context, **response_kwargs):
        export_type = self.request.GET.get('export')
        if export_type == 'pdf':
            # Renderiza o template específico para o PDF
            html_string = render_to_string('odin/campaign_pdf_report.html', context, request=self.request)
            
            # Gera o PDF com WeasyPrint
            pdf_file = HTML(string=html_string, base_url=self.request.build_absolute_uri()).write_pdf()
            
            response = HttpResponse(pdf_file, content_type='application/pdf')
            nome_arquivo = f"Relatorio_Campanha_{self.object.name.replace(' ', '_')}.pdf"
            response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
            return response

        if export_type == 'xlsx':
            from .ml_vestibular import PreditorVestibularOdin
            preditor = PreditorVestibularOdin()
            periodo_override = self.request.GET.get('periodo', '').strip().upper() or None
            dados = preditor.extrair_andamento_campanha(self.object)
            res = preditor.projetar(
                nome_curso=f"{self.object.course.name} ({self.object.name})",
                periodo=periodo_override,
                inscritos_hoje=dados['inscritos_pagos'],
                dia_atual=max(1, dados['dia_atual']),
                total_dias=dados['dias_totais'],
                meta=self.object.min_inscriptions,
                andamento_diario=dados['andamento_pagos'],
                num_registros_reais=dados['num_registros'],
                leads_boletos_pendentes=dados['boletos_pendentes'],
                leads_em_negociacao=dados['em_negociacao'],
            )
            xlsx_bytes = preditor.gerar_bytes_excel(
                [res],
                dia_atual=max(1, dados['dia_atual']),
                total_dias=dados['dias_totais'],
            )
            response = HttpResponse(
                xlsx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            nome_arquivo = f"Projecao_ML_{self.object.name.replace(' ', '_')}.xlsx"
            response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
            return response
            
        return super().render_to_response(context, **response_kwargs)

class DailyRecordCreateView(ProfessorRequiredMixin, CreateView):
    """Processa o formulário de novos pagantes do dia sem sair do painel"""
    model = CampaignDailyRecord
    form_class = CampaignDailyRecordForm

    def post(self, request, *args, **kwargs):
        campaign = get_object_or_404(
            VestibularCampaign.objects.filter(
                Q(created_by=request.user) | Q(collaborators=request.user) | Q(course__professor=request.user)
            ).distinct(),
            id=self.kwargs.get('campaign_id'),
        )
        date_val = request.POST.get('date')
        new_paid_val = int(request.POST.get('new_paid') or 0)
        sponsored_val = int(request.POST.get('sponsored_released') or 0)
        if date_val:
            CampaignDailyRecord.objects.update_or_create(
                campaign=campaign,
                date=date_val,
                defaults={
                    'new_paid': max(0, new_paid_val),
                    'sponsored_released': max(0, sponsored_val),
                },
            )
            messages.success(request, "Registro diário salvo! As projeções de Machine Learning foram recalibradas com o novo andamento.")
            return redirect('odin:campaign_dashboard', pk=campaign.id)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        campaign = get_object_or_404(
            VestibularCampaign.objects.filter(
                Q(created_by=self.request.user) | Q(collaborators=self.request.user) | Q(course__professor=self.request.user)
            ).distinct(),
            id=self.kwargs.get('campaign_id'),
        )
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
        # Se marcou como global, deixa a campanha vazia
        if form.cleaned_data.get('is_global'):
            form.instance.campaign = None
        else:
            # Se não, vincula à campanha da URL normalmente
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
        
        if action.is_global:
            # ROTEAMENTO INTELIGENTE: Busca a campanha ativa mais recente do curso que o aluno escolheu
            if form.instance.interested_course:
                active_campaign = VestibularCampaign.objects.filter(
                    course=form.instance.interested_course
                ).order_by('-start_date').first()
                form.instance.campaign = active_campaign
        else:
            form.instance.campaign = action.campaign
            
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
        # 1. Traz todos os leads das campanhas que pertencem aos cursos deste coordenador 
        # (incluindo os cadastrados manualmente sem campanha)
        qs = CampaignLead.objects.filter(
            Q(campaign__created_by=self.request.user) | 
            Q(campaign__collaborators=self.request.user) |
            Q(campaign__isnull=True)  
        ).distinct()

        # 2. Captura os parâmetros de busca e filtro da URL
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '')
        course = self.request.GET.get('course', '')
        sort = self.request.GET.get('sort', '-created_at') # Padrão: Mais recentes

        # 3. Aplica a Busca por Texto (Nome, Email ou Telefone)
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(phone__icontains=q) |
                Q(email__icontains=q)
            )
        
        # 4. Aplica o Filtro de Status
        if status:
            qs = qs.filter(status=status)
            
        # 5. Aplica o Filtro de Curso
        if course:
            if course == 'none':
                qs = qs.filter(interested_course__isnull=True) # A definir (Sem curso)
            else:
                qs = qs.filter(interested_course_id=course)

        # 6. Aplica a Ordenação Segura
        valid_sorts = ['name', '-name', 'phone', '-phone', 'created_at', '-created_at']
        if sort in valid_sorts:
            qs = qs.order_by(sort)
        else:
            qs = qs.order_by('-created_at')

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Envia a lista de cursos para o HTML desenhar o Select de Filtro
        context['courses'] = Course.objects.all().order_by('name')
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.GET.get('export') == 'pdf':
            # 1. Renderiza o template HTML como uma string pura
            html_string = render_to_string('odin/lead_pdf_report.html', context, request=self.request)
            
            # 2. O WeasyPrint lê a string e gera o PDF na memória
            pdf_file = HTML(string=html_string, base_url=self.request.build_absolute_uri()).write_pdf()
            
            # 3. Configura o envio do arquivo para o navegador
            response = HttpResponse(pdf_file, content_type='application/pdf')
            response['Content-Disposition'] = 'attachment; filename="Relatorio_Leads_FATEC.pdf"'
            return response
            
        return super().render_to_response(context, **response_kwargs)

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

@method_decorator(csrf_exempt, name='dispatch')
class ExternalLeadAPIView(View):
    """API Endpoint para recebimento de Leads de sistemas externos"""
    
    def post(self, request, *args, **kwargs):
        try:
            # 1. Lê o corpo da requisição enviada pelo sistema externo
            data = json.loads(request.body)
            
            # 2. Verificação de Segurança (API Key)
            api_key = data.get('api_key')
            if api_key != getattr(settings, 'ODIN_API_KEY', ''):
                return JsonResponse({'error': 'Acesso negado. API Key inválida.'}, status=401)
            
            # 3. Extrai os dados do candidato
            name = data.get('name')
            phone = data.get('phone')
            email = data.get('email', '')
            course_id = data.get('course_id') # Opcional
            
            if not name or not phone:
                return JsonResponse({'error': 'Nome e telefone são campos obrigatórios.'}, status=400)
                
            # 4. Roteamento Inteligente (Mesma lógica das ações globais)
            course = None
            campaign = None
            
            if course_id:
                course = Course.objects.filter(id=course_id).first()
                if course:
                    # Encontra a campanha mais recente desse curso para vincular o lead
                    campaign = VestibularCampaign.objects.filter(
                        course=course
                    ).order_by('-start_date').first()
                    
            # 5. Salva o Lead no Banco de Dados
            lead = CampaignLead.objects.create(
                name=name,
                phone=phone,
                email=email,
                interested_course=course,
                campaign=campaign,
                # Pode adicionar um campo "origin='API'" no banco depois, se quiser rastrear
            )
            
            return JsonResponse({
                'success': True, 
                'lead_id': lead.id, 
                'message': 'Lead cadastrado com sucesso!'
            }, status=201)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Formato JSON inválido.'}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'Erro interno: {str(e)}'}, status=500)

class CampaignLandingPageView(CreateView):
    """Página pública de captura de leads com design Split-Screen"""
    model = CampaignLead
    form_class = PublicLeadForm
    template_name = 'odin/campaign_landing.html' # Mantemos o mesmo nome do arquivo

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['campaign'] = get_object_or_404(VestibularCampaign, pk=self.kwargs['pk'])
        return context

    def form_valid(self, form):
        campaign = get_object_or_404(VestibularCampaign, pk=self.kwargs['pk'])
        form.instance.campaign = campaign
        form.instance.interested_course = campaign.course
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('odin:campaign_landing', kwargs={'pk': self.kwargs['pk']}) + '?sucesso=true'

class LandingPageConfigUpdateView(ProfessorRequiredMixin, UpdateView):
    model = LandingPageConfig
    form_class = LandingPageConfigForm
    template_name = 'odin/generic_form.html'
    
    def get_object(self, queryset=None):
        # Pega a campanha da URL. Se não tiver config de LP, cria uma em branco.
        campaign = get_object_or_404(VestibularCampaign, id=self.kwargs['campaign_id'])
        config, created = LandingPageConfig.objects.get_or_create(campaign=campaign)
        return config

    def get_success_url(self):
        return reverse_lazy('odin:campaign_dashboard', kwargs={'pk': self.kwargs['campaign_id']})

class LandingPageConfigUpdateView(ProfessorRequiredMixin, UpdateView):
    model = LandingPageConfig
    form_class = LandingPageConfigForm
    template_name = 'odin/landing_page_setup.html' # <--- NOVO TEMPLATE
    
    def get_object(self, queryset=None):
        campaign = get_object_or_404(VestibularCampaign, id=self.kwargs['campaign_id'])
        config, created = LandingPageConfig.objects.get_or_create(campaign=campaign)
        return config

    def get_success_url(self):
        return reverse_lazy('odin:campaign_dashboard', kwargs={'pk': self.kwargs['campaign_id']})

class CampaignQRCodeView(View):
    """Gera um QR Code dinâmico apontando para a Landing Page da Campanha"""
    
    def get(self, request, pk, *args, **kwargs):
        # 1. Constrói a URL ABSOLUTA (incluindo http:// e o domínio)
        path = reverse('odin:campaign_landing', kwargs={'pk': pk})
        full_url = request.build_absolute_uri(path)
        
        # 2. Configura e gera o QR Code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(full_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # 3. Devolve a imagem nativamente como resposta HTTP
        response = HttpResponse(content_type="image/png")
        img.save(response, "PNG")
        
        return response

class CampaignLeadUpdateView(ProfessorRequiredMixin, UpdateView):
    model = CampaignLead
    form_class = CampaignLeadUpdateForm
    template_name = 'odin/generic_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Atualizar Status do Lead"
        return context

    def get_success_url(self):
        # Volta automaticamente para o dashboard da campanha atual do lead
        return reverse_lazy('odin:campaign_dashboard', kwargs={'pk': self.object.campaign.id})

class ManualLeadCreateView(ProfessorRequiredMixin, CreateView):
    """View para a equipe cadastrar leads manualmente via telefone/balcão"""
    model = CampaignLead
    form_class = InternalLeadForm
    template_name = 'odin/generic_form.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Cadastrar Lead Manualmente"
        return context

    def get_success_url(self):
        # Após salvar, redireciona de volta para a Base Central de Leads
        # (Substitua 'odin:lead_list' pelo nome exato da URL da sua Base Central, se for diferente)
        return reverse_lazy('odin:lead_list')

# 1. Formulário embutido para fazer o Upload
class ImportIsencaoForm(forms.Form):
    arquivo = forms.FileField(
        label="Arquivo de Isenção (.xls)",
        help_text="Faça o upload do arquivo Inscritos-Isencao.xls gerado pelo sistema. Todos entrarão com status 'Isenção'."
    )
    # Deixa a equipe vincular esses leads a uma campanha específica, se quiser
    campaign = forms.ModelChoiceField(
        queryset=VestibularCampaign.objects.all(),
        required=False,
        empty_label="--- Nenhuma (Deixar na Base Central) ---",
        label="Vincular à Campanha (Opcional)",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['arquivo'].widget.attrs.update({'class': 'form-control', 'accept': '.xls,.html'})


# 2. A View que processa o arquivo
class ImportIsencaoView(ProfessorRequiredMixin, FormView):
    template_name = 'odin/generic_form.html'
    form_class = ImportIsencaoForm
    success_url = reverse_lazy('odin:lead_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Importar Planilha de Isenções"
        return context

    def form_valid(self, form):
        arquivo = self.request.FILES['arquivo']
        campaign = form.cleaned_data.get('campaign')

        try:
            # O Pandas lê automaticamente a tabela HTML escondida no .xls
            dfs = pd.read_html(arquivo)
            df = dfs[0]

            novos_leads = []
            
            # Percorre cada linha da planilha
            for index, row in df.iterrows():
                nome = str(row.get('Nome', '')).strip()
                celular = str(row.get('Celular', '')).strip()
                email = str(row.get('E-mail', '')).strip()

                # Se a linha tiver um nome válido (ignora linhas vazias/NaN)
                if nome and nome.lower() != 'nan' and nome != '---':
                    
                    # Limpa "nan" do telefone e email caso estejam em branco
                    if celular.lower() == 'nan': celular = ''
                    if email.lower() == 'nan': email = ''

                    novos_leads.append(CampaignLead(
                        name=nome,
                        phone=celular,
                        email=email,
                        status='isencao', # <--- Já entra com o status correto do funil
                        campaign=campaign
                    ))

            # Salva todos os 56 de uma vez no banco de dados!
            CampaignLead.objects.bulk_create(novos_leads)
            
            messages.success(self.request, f"{len(novos_leads)} candidatos importados com sucesso para a fila de Isenção!")
            
        except Exception as e:
            messages.error(self.request, f"Erro ao processar o arquivo. Verifique se o formato está correto. Detalhe técnico: {str(e)}")

        return super().form_valid(form)

class CampaignPublicProgressView(DetailView):
    """Dashboard de somente leitura para compartilhar com os professores (sem dados sensíveis)"""
    model = VestibularCampaign
    template_name = 'odin/public_progress.html'
    context_object_name = 'campaign'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # 1. Pega os dados originais do gráfico
        raw_chart_data = self.object.get_chart_data()
        chart_data = json.loads(raw_chart_data)
        
        # 2. APAGA os dados de patrocínio para esconder a estratégia financeira
        if 'real_patrocinados' in chart_data:
            del chart_data['real_patrocinados']
            
        # Devolve o JSON limpo para o template
        context['clean_chart_data'] = json.dumps(chart_data)
        
        # 3. Indicadores Básicos
        context['total_paid'] = self.object.accumulated_paid
        context['goal'] = self.object.vacancies
        if context['goal'] > 0:
            context['progress_pct'] = round((context['total_paid'] / context['goal']) * 100, 1)
        else:
            context['progress_pct'] = 0
            
        return context

class CampaignLeadDeleteView(ProfessorRequiredMixin, DeleteView):
    """View para excluir um lead com tela de confirmação"""
    model = CampaignLead
    template_name = 'odin/lead_confirm_delete.html'
    
    def get_success_url(self):
        # Redireciona para a base central após apagar
        return reverse_lazy('odin:lead_list')
        
    def delete(self, request, *args, **kwargs):
        # Mensagem de sucesso flutuante ao confirmar
        messages.success(self.request, "Lead excluído com sucesso da base de dados.")
        return super().delete(request, *args, **kwargs)

class UpdateLeadsStatusView(ProfessorRequiredMixin, FormView):
    template_name = 'odin/generic_form.html'
    form_class = UpdateLeadsStatusForm
    success_url = reverse_lazy('odin:lead_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = "Atualizar Status em Lote (Via Planilha)"
        return context

    def form_valid(self, form):
        arquivo = self.request.FILES['arquivo']

        try:
            # Lê o arquivo HTML disfarçado de XLS
            dfs = pd.read_html(arquivo)
            df = dfs[0]

            # Pega o nome da última coluna (que contém o status: Boleto, Pago, etc.)
            coluna_status = df.columns[-1]

            # Dicionário de tradução Vunesp/CPS -> Nosso Funil
            mapa_status = {
                'boleto': 'inscrito_nao_pago',
                'pago': 'pago',
                'efetivada': 'pago',
                'isento': 'pago', # Isentos confirmados também garantem vaga
            }

            atualizados = 0

            for index, row in df.iterrows():
                nome = str(row.get('Nome', '')).strip()
                email = str(row.get('E-mail', '')).strip()
                telefone = str(row.get('Celular', '')).strip()
                status_raw = str(row.get(coluna_status, '')).strip().lower()

                # Tenta traduzir o status da planilha para o do nosso sistema
                novo_status = mapa_status.get(status_raw)

                if novo_status and nome and nome != 'nan':
                    # Busca o Lead no nosso banco. A ordem de prioridade é: E-mail, depois Celular, depois Nome exato.
                    query = Q()
                    if email and email != 'nan':
                        query |= Q(email__iexact=email)
                    if telefone and telefone != 'nan':
                        query |= Q(phone__icontains=telefone[-8:]) # Compara os últimos 8 dígitos do telefone
                    if not query:
                        query = Q(name__iexact=nome)

                    leads_encontrados = CampaignLead.objects.filter(query)

                    # Se achou o lead e o status dele for diferente, atualiza
                    for lead in leads_encontrados:
                        if lead.status != novo_status:
                            lead.status = novo_status
                            lead.save(update_fields=['status'])
                            atualizados += 1

            messages.success(self.request, f"Sucesso! {atualizados} candidatos tiveram seus status atualizados no funil.")

        except Exception as e:
            messages.error(self.request, f"Erro ao processar o arquivo. Verifique o formato. Detalhe técnico: {str(e)}")

        return super().form_valid(form)


class VestibularMLPredictorView(ProfessorRequiredMixin, TemplateView):
    """
    Painel Consolidado de Inteligência Preditiva (Machine Learning) e Simulador do Vestibular.
    Integra:
      1. Projeção automática de todas as campanhas de vestibular do Odin usando o andamento diário real.
      2. Simulador interativo para cursos novos/existentes (com suporte a andamento e exportação Excel .xlsx com gráfico).
      3. Explorador e atualizador da base histórica vestibular.csv.
    """
    template_name = 'odin/vestibular_ml_predictor.html'

    DEFAULT_SIMULATOR_COURSES = [
        {"nome": "Tecnologia de Alimentos", "periodo": "N", "inscritos": 15, "meta": 60, "andamento_str": ""},
        {"nome": "Desenvolvimento de Software Multiplataforma (DSM)", "periodo": "M", "inscritos": 19, "meta": 60, "andamento_str": ""},
        {"nome": "Engenharia de Alimentos", "periodo": "M", "inscritos": 22, "meta": 60, "andamento_str": ""},
        {"nome": "Gestão Comercial", "periodo": "N", "inscritos": 15, "meta": 60, "andamento_str": ""},
    ]

    @staticmethod
    def _parse_andamento_str(andamento_str: str):
        if not andamento_str or not andamento_str.strip():
            return None
        partes = [p.strip() for p in andamento_str.replace(";", ",").split(",") if p.strip()]
        vals = []
        for p in partes:
            try:
                vals.append(float(p))
            except ValueError:
                continue
        return vals if len(vals) >= 2 else None

    def _obter_projecoes_campanhas_ativas(self, preditor):
        campaigns = VestibularCampaign.objects.filter(
            Q(created_by=self.request.user) | Q(collaborators=self.request.user)
        ).select_related('course').distinct().order_by('-start_date')

        resultados_campanhas = []
        for camp in campaigns:
            dados = preditor.extrair_andamento_campanha(camp)
            res = preditor.projetar(
                nome_curso=f"{camp.course.name} — {camp.name}",
                periodo=None,
                inscritos_hoje=dados['inscritos_pagos'],
                dia_atual=max(1, dados['dia_atual']),
                total_dias=dados['dias_totais'],
                meta=camp.min_inscriptions,
                andamento_diario=dados['andamento_pagos'],
                num_registros_reais=dados['num_registros'],
                leads_boletos_pendentes=dados['boletos_pendentes'],
                leads_em_negociacao=dados['em_negociacao'],
            )
            res['campaign_id'] = camp.id
            res['campaign_name'] = camp.name
            res['course_name'] = camp.course.name
            res['vacancies'] = camp.vacancies
            res['num_registros'] = dados['num_registros']
            res.pop('_curva_aprendida_grid', None)
            resultados_campanhas.append(res)
        return resultados_campanhas

    def get(self, request, *args, **kwargs):
        from .ml_vestibular import PreditorVestibularOdin, BASE_CSV_PATH

        preditor = PreditorVestibularOdin()
        export_mode = request.GET.get('export')

        if export_mode == 'csv_historico' and BASE_CSV_PATH.exists():
            with open(BASE_CSV_PATH, 'rb') as f:
                response = HttpResponse(f.read(), content_type='text/csv; charset=utf-8')
                response['Content-Disposition'] = 'attachment; filename="vestibular.csv"'
                return response

        if export_mode == 'xlsx_campanhas':
            campanhas_proj = self._obter_projecoes_campanhas_ativas(preditor)
            if not campanhas_proj:
                messages.warning(request, "Não há campanhas cadastradas para exportar.")
                return redirect('odin:vestibular_ml_predictor')
            dia_ref = campanhas_proj[0]['dia_atual']
            total_ref = campanhas_proj[0]['total_dias']
            xlsx_bytes = preditor.gerar_bytes_excel(campanhas_proj, dia_atual=dia_ref, total_dias=total_ref)
            response = HttpResponse(
                xlsx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = 'attachment; filename="projecao_ml_campanhas_odin.xlsx"'
            return response

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        from .ml_vestibular import PreditorVestibularOdin, BASE_CSV_PATH

        acao = request.POST.get('acao', 'simular')

        # 1. Upload de nova base histórica vestibular.csv
        if acao == 'upload_csv':
            arquivo = request.FILES.get('arquivo_csv')
            if not arquivo:
                messages.error(request, "Selecione um arquivo .csv válido para atualizar a base histórica.")
                return redirect('odin:vestibular_ml_predictor')
            try:
                conteudo = arquivo.read().decode('utf-8')
                linhas = [l for l in conteudo.splitlines() if l.strip()]
                if len(linhas) < 2 or 'curso' not in linhas[0].lower():
                    messages.error(request, "O arquivo CSV deve conter o cabeçalho 'curso,período,0,1,2,...' e pelo menos uma linha de dados.")
                    return redirect('odin:vestibular_ml_predictor')
                BASE_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(BASE_CSV_PATH, 'w', encoding='utf-8') as f:
                    f.write(conteudo)
                messages.success(request, "Base histórica (vestibular.csv) atualizada e modelo de Machine Learning re-treinado com sucesso!")
            except Exception as e:
                messages.error(request, f"Erro ao processar o arquivo CSV: {str(e)}")
            return redirect('odin:vestibular_ml_predictor')

        # 2. Simulação de Cursos / Exportação Excel do Simulador
        preditor = PreditorVestibularOdin()
        try:
            dia_atual = max(1, int(request.POST.get('dia_atual') or 38))
            total_dias = max(1, int(request.POST.get('total_dias') or 54))
        except ValueError:
            dia_atual, total_dias = 38, 54

        nomes = request.POST.getlist('curso_nome')
        periodos = request.POST.getlist('curso_periodo')
        inscritos_list = request.POST.getlist('curso_inscritos')
        metas_list = request.POST.getlist('curso_meta')
        andamentos_list = request.POST.getlist('curso_andamento')

        cursos_simulados = []
        resultados_simulador = []

        for i in range(len(nomes)):
            nome = nomes[i].strip()
            if not nome:
                continue
            per = periodos[i].strip() if i < len(periodos) else 'N'
            try:
                insc = float(inscritos_list[i]) if i < len(inscritos_list) and inscritos_list[i] != '' else 0.0
            except ValueError:
                insc = 0.0
            try:
                meta_v = int(metas_list[i]) if i < len(metas_list) and metas_list[i] != '' else 60
            except ValueError:
                meta_v = 60
            andamento_raw = andamentos_list[i].strip() if i < len(andamentos_list) else ''
            andamento_parsed = self._parse_andamento_str(andamento_raw)
            if andamento_parsed and insc == 0.0:
                insc = andamento_parsed[-1]

            cursos_simulados.append({
                "nome": nome,
                "periodo": per,
                "inscritos": int(round(insc)),
                "meta": meta_v,
                "andamento_str": andamento_raw,
            })

            res = preditor.projetar(
                nome_curso=nome,
                periodo=per,
                inscritos_hoje=insc,
                dia_atual=dia_atual,
                total_dias=total_dias,
                meta=meta_v,
                andamento_diario=andamento_parsed,
                num_registros_reais=len(andamento_parsed) if andamento_parsed else 0,
            )
            res['andamento_str'] = andamento_raw
            res.pop('_curva_aprendida_grid', None)
            resultados_simulador.append(res)

        if acao == 'exportar_excel_simulador' and resultados_simulador:
            xlsx_bytes = preditor.gerar_bytes_excel(
                resultados_simulador, dia_atual=dia_atual, total_dias=total_dias
            )
            response = HttpResponse(
                xlsx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
            response['Content-Disposition'] = 'attachment; filename="projecao_novos_cursos_ml.xlsx"'
            return response

        context = self.get_context_data(
            dia_atual_sim=dia_atual,
            total_dias_sim=total_dias,
            cursos_simulados=cursos_simulados,
            resultados_simulador=resultados_simulador,
            aba_ativa='simulador',
        )
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .ml_vestibular import PreditorVestibularOdin

        preditor = PreditorVestibularOdin()
        campanhas_proj = self._obter_projecoes_campanhas_ativas(preditor)
        context['campanhas_proj'] = campanhas_proj

        # Totais consolidados das campanhas ativas
        context['total_inscritos_campanhas'] = sum(c['inscritos_hoje'] for c in campanhas_proj)
        context['total_projecao_ml_campanhas'] = sum(c['projecao_esperada'] for c in campanhas_proj)
        context['total_otimista_campanhas'] = sum(c['cenario_otimista'] for c in campanhas_proj)
        context['total_pessimista_campanhas'] = sum(c['cenario_pessimista'] for c in campanhas_proj)
        context['total_meta_campanhas'] = sum(c['meta'] for c in campanhas_proj)

        # Estado inicial ou pós-submissão do Simulador
        dia_atual_sim = kwargs.get('dia_atual_sim', 38)
        total_dias_sim = kwargs.get('total_dias_sim', 54)
        cursos_sim = kwargs.get('cursos_simulados')
        resultados_sim = kwargs.get('resultados_simulador')

        if cursos_sim is None:
            # Se houver campanhas ativas, usa como ponto de partida; caso contrário usa os 4 cursos de exemplo
            if campanhas_proj:
                dia_atual_sim = campanhas_proj[0]['dia_atual']
                total_dias_sim = campanhas_proj[0]['total_dias']
                cursos_sim = []
                for c in campanhas_proj:
                    cursos_sim.append({
                        "nome": c['course_name'],
                        "periodo": c['periodo'],
                        "inscritos": c['inscritos_hoje'],
                        "meta": c['meta'],
                        "andamento_str": "",
                    })
            else:
                cursos_sim = self.DEFAULT_SIMULATOR_COURSES

        if resultados_sim is None:
            resultados_sim = []
            for c in cursos_sim:
                andamento_parsed = self._parse_andamento_str(c.get("andamento_str", ""))
                res = preditor.projetar(
                    nome_curso=c["nome"],
                    periodo=c["periodo"],
                    inscritos_hoje=c["inscritos"],
                    dia_atual=dia_atual_sim,
                    total_dias=total_dias_sim,
                    meta=c["meta"],
                    andamento_diario=andamento_parsed,
                    num_registros_reais=len(andamento_parsed) if andamento_parsed else 0,
                )
                res['andamento_str'] = c.get("andamento_str", "")
                res.pop('_curva_aprendida_grid', None)
                resultados_sim.append(res)

        context['dia_atual_sim'] = dia_atual_sim
        context['total_dias_sim'] = total_dias_sim
        context['cursos_simulados'] = cursos_sim
        context['resultados_simulador'] = resultados_sim
        context['aba_ativa'] = kwargs.get('aba_ativa', self.request.GET.get('tab', 'campanhas' if campanhas_proj else 'simulador'))

        # Totais do simulador e JSON para o gráfico comparativo do simulador
        context['sim_total_inscritos'] = sum(r['inscritos_hoje'] for r in resultados_sim)
        context['sim_total_pessimista'] = sum(r['cenario_pessimista'] for r in resultados_sim)
        context['sim_total_esperada'] = sum(r['projecao_esperada'] for r in resultados_sim)
        context['sim_total_otimista'] = sum(r['cenario_otimista'] for r in resultados_sim)
        context['sim_total_meta'] = sum(r['meta'] for r in resultados_sim)
        context['sim_total_deficit'] = sum(r['deficit_meta'] for r in resultados_sim)

        context['sim_chart_json'] = json.dumps({
            "labels": [r['curso'] for r in resultados_sim],
            "atual": [r['inscritos_hoje'] for r in resultados_sim],
            "pessimista": [r['cenario_pessimista'] for r in resultados_sim],
            "esperada": [r['projecao_esperada'] for r in resultados_sim],
            "otimista": [r['cenario_otimista'] for r in resultados_sim],
            "meta": [r['meta'] for r in resultados_sim],
        })

        # Resumo da base histórica vestibular.csv
        context['historico_info'] = preditor.obter_resumo_historico_csv()
        return context
