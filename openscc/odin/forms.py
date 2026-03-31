from django import forms
from .models import *

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