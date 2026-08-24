from django import forms
from .models import *
from django.contrib.auth.models import Group
class FormativeAxisForm(forms.ModelForm):
    class Meta:
        model = FormativeAxis
        fields = ['name', 'color']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Núcleo Básico'}),
            # O type='color' transforma o input numa paleta de cores clicável!
            'color': forms.TextInput(attrs={'class': 'form-control form-control-color', 'type': 'color'}),
        }

class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['name', 'reference_axis', 'modality', 'min_semesters', 'max_semesters', 'total_vacancies']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: CST em Gestão Empresarial'}),
            'reference_axis': forms.Select(attrs={'class': 'form-select'}),
            'modality': forms.Select(attrs={'class': 'form-select'}),
            'min_semesters': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'max_semesters': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'total_vacancies': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }

class DisciplineForm(forms.ModelForm):
    class Meta:
        model = Discipline
        fields = [
            'code', 'name', 'formative_axis','prerequisites', 
            'theory_classes', 'lab_classes', 'online_classes',
            'learning_objectives', 'syllabus', 'methodology', 
            'assessment_criteria', 'basic_bibliography', 'complementary_bibliography'
        ]
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: INF-061'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Informática Aplicada à Gestão'}),
            'formative_axis': forms.Select(attrs={'class': 'form-select'}),
            'theory_classes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'lab_classes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'online_classes': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'learning_objectives': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'syllabus': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'methodology': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'assessment_criteria': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'basic_bibliography': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'complementary_bibliography': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'prerequisites': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
        }

    def __init__(self, *args, **kwargs):
        # Removemos a lógica do 'user' daqui
        super().__init__(*args, **kwargs)
        
        # Puxa todas as disciplinas globais do sistema
        qs = Discipline.objects.all().order_by('name')
        
        # Se for edição, exclui a própria disciplina da lista de opções de pré-requisito
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
            
        self.fields['prerequisites'].queryset = qs

class PPCProposalForm(forms.ModelForm):
    class Meta:
        model = PPCProposal
        fields = [
            'course', 'version_semester', 'update_type', 'legal_act', 
            'justification', 'general_objective', 'graduate_profile', 'is_active'
        ]
        widgets = {
            'course': forms.Select(attrs={'class': 'form-select'}),
            'version_semester': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 2026/1º Sem.'}),
            'update_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Implantação ou Reestruturação'}),
            'legal_act': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Portaria nº X'}),
            'justification': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'general_objective': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'graduate_profile': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            # O professor só pode criar um PPC para um curso dele
            self.fields['course'].queryset = Course.objects.filter(professor=user)

class CurriculumMatrixForm(forms.ModelForm):
    class Meta:
        model = CurriculumMatrix
        fields = ['discipline', 'semester', 'offering', 'is_elective']
        widgets = {
            'discipline': forms.Select(attrs={'class': 'form-select'}),
            'semester': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'offering': forms.Select(attrs={'class': 'form-select'}),
            'is_elective': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        # Removemos o 'user' daqui também
        super().__init__(*args, **kwargs)
        # Ao montar a grade, lista TODAS as disciplinas do catálogo da instituição
        self.fields['discipline'].queryset = Discipline.objects.all().order_by('name')

class VestibularCampaignForm(forms.ModelForm):
    class Meta:
        model = VestibularCampaign
        fields = ['course', 'name', 'start_date', 'end_date', 'vacancies', 'min_inscriptions', 'yield_paid', 'yield_sponsored']
        widgets = {
            'course': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome da Campanha'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'vacancies': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'min_inscriptions': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'yield_paid': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'yield_sponsored': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

# 1. TRADUÇÃO DOS RÓTULOS (LABELS)
        labels = {
            'course': 'Curso Referência',
            'name': 'Nome da Campanha',
            'start_date': 'Data de Início',
            'end_date': 'Data de Encerramento',
            'vacancies': 'Vagas Ofertadas',
            'min_inscriptions': 'Meta de Inscritos',
            'yield_paid': 'Custo Planejado (Lead Pago)',
            'yield_sponsored': 'Verba de Patrocínio',
        }
        
        # 2. COMPONENTES VISUAIS (WIDGETS)
        widgets = {
            'course': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Vestibular de Inverno 2026'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'vacancies': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'min_inscriptions': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'yield_paid': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'yield_sponsored': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }

class CampaignDailyRecordForm(forms.ModelForm):
    class Meta:
        model = CampaignDailyRecord
        fields = ['date', 'new_paid', 'sponsored_released']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

# --- Visão do Coordenador ---
class CampaignActionForm(forms.ModelForm):
    class Meta:
        model = CampaignAction
        fields = ['title', 'description', 'scheduled_date', 'location', 'responsible']
        widgets = {
            'scheduled_date': forms.DateInput(attrs={'type': 'date'}),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Opcional: Filtrar a combo 'responsible' para mostrar apenas professores ativos
        # self.fields['responsible'].queryset = User.objects.filter(is_active=True)

# --- Visão do Professor (Execução) ---
class ActionExpenseForm(forms.ModelForm):
    class Meta:
        model = ActionExpense
        fields = ['description', 'amount', 'date_incurred', 'receipt_file']
        widgets = {
            'date_incurred': forms.DateInput(attrs={'type': 'date'}),
        }

class ActionPhotoForm(forms.ModelForm):
    class Meta:
        model = ActionPhoto
        fields = ['image', 'caption']

class CampaignLeadForm(forms.ModelForm):
    class Meta:
        model = CampaignLead
        fields = ['name', 'phone', 'email', 'interested_course']

# 1. Formulário do Aluno (Fase 1: Cadastro Inicial)
class ICProjectCreateForm(forms.ModelForm):
    class Meta:
        model = ScientificProject
        fields = ['title', 'advisor']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtra a lista para mostrar APENAS usuários do grupo "Professor"
        self.fields['advisor'].queryset = User.objects.filter(
            groups__name="Professor", 
            is_active=True
        ).order_by('first_name')

# 2. Formulário do Aluno (Fase 2: Submissão do Arquivo)
class ICProjectSubmitForm(forms.ModelForm):
    class Meta:
        model = ScientificProject
        fields = ['project_file']

# 3. Formulário da CEPE (Designar Parecerista)
class CEPEAssignReviewerForm(forms.ModelForm):
    class Meta:
        model = ScientificProject
        fields = ['reviewer']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Filtra a lista de pareceristas APENAS para professores ativos
        qs = User.objects.filter(groups__name="Professor", is_active=True).order_by('first_name')
        
        # Regra de negócio: O orientador NÃO pode ser o parecerista do próprio aluno
        if self.instance and self.instance.advisor:
            qs = qs.exclude(id=self.instance.advisor.id)
            
        self.fields['reviewer'].queryset = qs
# 4. Formulário do Parecerista Ad-hoc
class ReviewerEvaluationForm(forms.ModelForm):
    class Meta:
        model = ScientificProject
        fields = ['reviewer_feedback'] # Removemos o campo 'status' daqui
        widgets = {
            'reviewer_feedback': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 8, 
                'placeholder': 'Descreva sua análise técnica e conclua com sua recomendação (Ex: Recomendo o deferimento com ressalvas...)'
            }),
        }
        # 5. Formulário do Aluno (Fase Final: Relatório)

# NOVO: Formulário de Decisão Final da CEPE
class CEPEDecisionForm(forms.ModelForm):
    class Meta:
        model = ScientificProject
        fields = ['status', 'cepe_feedback']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select fw-bold border-primary mb-3'}),
            'cepe_feedback': forms.Textarea(attrs={
                'class': 'form-control', 
                'rows': 4, 
                'placeholder': 'Justificativa ou observações finais da CEPE (Opcional caso deferido, obrigatório caso indeferido)...'
            }),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = [
            ('', 'Selecione o Veredito Final da CEPE...'),
            ('IN_PROGRESS', 'Deferido (Aprovado)'),
            ('CHANGES_REQUESTED', 'Deferido com Ressalvas'),
            ('REJECTED', 'Indeferido (Rejeitado)'),
        ]

class ICFinalReportForm(forms.ModelForm):
    class Meta:
        model = ScientificProject
        fields = ['final_report_file']