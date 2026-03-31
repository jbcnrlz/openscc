from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, ListView, CreateView, DetailView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

from .models import *
from .forms import *

# --- Mixin de Segurança ---
class ProfessorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Garante que o usuário esteja logado e seja da equipe/professor"""
    login_url = '/admin/login/'
    
    def test_func(self):
        # Regra de acesso: precisa ser staff ou superusuário
        return self.request.user.is_staff or self.request.user.is_superuser

# --- 1. Dashboard ---
class DashboardView(ProfessorRequiredMixin, TemplateView):
    template_name = 'odin/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Mantém a contagem de cursos isolada para o professor logado
        context['total_courses'] = Course.objects.filter(professor=self.request.user).count()
        
        # --- CORREÇÃO AQUI ---
        # Como o catálogo agora é global, contamos todas as disciplinas disponíveis na instituição
        context['total_disciplines'] = Discipline.objects.count()
        # ---------------------
        
        # Mantém a contagem de PPCs isolada para o professor logado
        context['active_ppcs'] = PPCProposal.objects.filter(course__professor=self.request.user, is_active=True).count()
        
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
    success_url = reverse_lazy('course_list')

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
    success_url = reverse_lazy('discipline_list')

class DisciplineUpdateView(ProfessorRequiredMixin, UpdateView):
    model = Discipline
    form_class = DisciplineForm
    template_name = 'odin/discipline_form.html'
    success_url = reverse_lazy('discipline_list')

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
        return PPCProposal.objects.filter(course__professor=self.request.user).order_by('-created_at')

class PPCCreateView(ProfessorRequiredMixin, CreateView):
    model = PPCProposal
    form_class = PPCProposalForm
    template_name = 'odin/ppc_form.html'
    success_url = reverse_lazy('ppc_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        return kwargs

class PPCDetailView(ProfessorRequiredMixin, DetailView):
    """Painel principal que agrupa as disciplinas na Grade Curricular"""
    model = PPCProposal
    template_name = 'odin/ppc_detail.html'
    context_object_name = 'ppc'

    def get_queryset(self):
        # Impede que um professor veja a grade do PPC de outro professor
        return PPCProposal.objects.filter(course__professor=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Pega as disciplinas atreladas a este PPC ordenadas pelo semestre
        matrix_items = self.object.matrix_items.select_related('discipline').order_by('semester', 'discipline__name')
        
        # Agrupa os itens por semestre
        semesters = {}
        for item in matrix_items:
            if item.semester not in semesters:
                semesters[item.semester] = []
            semesters[item.semester].append(item)
            
        context['semesters'] = semesters
        
        # Envia o formulário com o usuário logado para carregar o combo de disciplinas
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
        return reverse_lazy('ppc_detail', kwargs={'pk': self.kwargs['ppc_id']})

# --- Gestão de Eixos Tecnológicos ---
class TechnologicalAxisListView(ProfessorRequiredMixin, ListView):
    model = TechnologicalAxis
    template_name = 'odin/axis_list.html'
    context_object_name = 'axes'

class TechnologicalAxisCreateView(ProfessorRequiredMixin, CreateView):
    model = TechnologicalAxis
    fields = ['name', 'description'] # Podemos usar os fields padrão para acelerar
    template_name = 'odin/generic_form.html' # Um template genérico salva tempo aqui!
    success_url = reverse_lazy('axis_list')

# --- Gestão de Modalidades ---
class ModalityListView(ProfessorRequiredMixin, ListView):
    model = Modality
    template_name = 'odin/modality_list.html'
    context_object_name = 'modalities'

class ModalityCreateView(ProfessorRequiredMixin, CreateView):
    model = Modality
    fields = ['name']
    template_name = 'odin/generic_form.html'
    success_url = reverse_lazy('modality_list')

class CourseUpdateView(ProfessorRequiredMixin, UpdateView):
    model = Course
    form_class = CourseForm
    template_name = 'odin/course_form.html'
    success_url = reverse_lazy('course_list')

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
        return reverse_lazy('ppc_detail', kwargs={'pk': self.object.ppc.id})
    
# --- Gestão de Eixos Formativos ---
class FormativeAxisListView(ProfessorRequiredMixin, ListView):
    model = FormativeAxis
    template_name = 'odin/formative_axis_list.html'
    context_object_name = 'axes'

class FormativeAxisCreateView(ProfessorRequiredMixin, CreateView):
    model = FormativeAxis
    form_class = FormativeAxisForm
    template_name = 'odin/generic_form.html' # Reaproveitamos o form genérico!
    success_url = reverse_lazy('formative_axis_list')