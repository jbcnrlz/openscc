from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from mimir.models import isProfessor

User.add_to_class('isProfessor', isProfessor)

class FormativeAxis(models.Model):
    """Cadastro global de Eixos Formativos com seleção de cor"""
    name = models.CharField(max_length=200, verbose_name="Nome do Eixo Formativo")
    color = models.CharField(max_length=7, default="#0d6efd", verbose_name="Cor de Exibição")

    class Meta:
        verbose_name = "Eixo Formativo"
        verbose_name_plural = "Eixos Formativos"
        ordering = ['name']

    def __str__(self):
        return self.name

class TechnologicalAxis(models.Model):
    """Cadastro global de Eixos Tecnológicos"""
    name = models.CharField(max_length=150, unique=True, verbose_name="Eixo Tecnológico")
    description = models.TextField(blank=True, verbose_name="Descrição do Eixo")

    class Meta:
        verbose_name = "Eixo Tecnológico"
        verbose_name_plural = "Eixos Tecnológicos"
        ordering = ['name']

    def __str__(self):
        return self.name

class Modality(models.Model):
    """Cadastro global de Modalidades de Ensino"""
    name = models.CharField(max_length=50, unique=True, verbose_name="Modalidade")

    class Meta:
        verbose_name = "Modalidade"
        verbose_name_plural = "Modalidades"
        ordering = ['name']

    def __str__(self):
        return self.name

# --- 1. Dados Institucionais e Legais ---

class Course(models.Model):
    """Representa os Dados Gerais do Curso [cite: 2703, 2709]"""
    professor = models.ForeignKey(User, on_delete=models.CASCADE, related_name='my_courses')
    
    name = models.CharField(max_length=200, verbose_name="Nome do Curso")
    reference_axis = models.ForeignKey(TechnologicalAxis, on_delete=models.PROTECT, verbose_name="Eixo Tecnológico")
    modality = models.ForeignKey(Modality, on_delete=models.PROTECT, verbose_name="Modalidade")    
    
    # Prazos e Vagas [cite: 2709]
    min_semesters = models.PositiveIntegerField(verbose_name="Prazo mínimo de integralização")
    max_semesters = models.PositiveIntegerField(verbose_name="Prazo máximo de integralização")
    total_vacancies = models.PositiveIntegerField(verbose_name="Vagas totais semestrais")

    def __str__(self):
        return self.name

class PPCProposal(models.Model):
    """Contextualização e Histórico de Atualizações do PPC [cite: 2423, 2475]"""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='ppcs')
    version_semester = models.CharField(max_length=20, verbose_name="Ano/Semestre (Ex: 2024/1º Sem.)")
    update_type = models.CharField(max_length=100, verbose_name="Tipo (Implantação, Reestruturação)")
    legal_act = models.CharField(max_length=255, verbose_name="Ato Legal (Portaria/Decreto)")
    
    # Justificativa e Objetivos [cite: 2718, 2758]
    justification = models.TextField(verbose_name="Justificativa")
    general_objective = models.TextField(verbose_name="Objetivo do Curso")
    graduate_profile = models.TextField(verbose_name="Perfil Profissional do Egresso")
    
    is_active = models.BooleanField(default=False, verbose_name="PPC Vigente?")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PPC {self.course.name} - {self.version_semester}"

# --- 2. Competências e Infraestrutura ---

class Competence(models.Model):
    """Perfil Profissional: Mapeamento de competências profissionais e socioemocionais [cite: 2811, 2872]"""
    COMPETENCE_TYPES = [
        ('PROFESSIONAL', 'Profissional'),
        ('SOCIOEMOTIONAL', 'Socioemocional'),
    ]
    description = models.TextField(verbose_name="Descrição da Competência")
    type = models.CharField(max_length=20, choices=COMPETENCE_TYPES)

    def __str__(self):
        return f"[{self.get_type_display()}] {self.description[:50]}..."

class Infrastructure(models.Model):
    """Mapeamento de Laboratórios ou Ambientes de Aprendizagem [cite: 4734, 4738]"""
    name = models.CharField(max_length=150, verbose_name="Laboratório ou Ambiente")
    capacity = models.PositiveIntegerField(verbose_name="Capacidade")
    location = models.CharField(max_length=150, verbose_name="Localização")

    def __str__(self):
        return self.name

# --- 3. Catálogo de Componentes Curriculares (Ementário) ---

class Discipline(models.Model):
    """A forma base de uma disciplina, refletindo o ementário detalhado [cite: 3014, 3018, 3030]"""
    
    name = models.CharField(max_length=200, verbose_name="Componente")
    code = models.CharField(max_length=20, unique=True, verbose_name="Sigla")
    formative_axis = models.ForeignKey(FormativeAxis, on_delete=models.PROTECT, verbose_name="Eixo Formativo")
    
    # Carga Horária Detalhada (Aulas) 
    theory_classes = models.PositiveIntegerField(default=0, verbose_name="Aulas Presenciais (Sala)")
    lab_classes = models.PositiveIntegerField(default=0, verbose_name="Aulas Presenciais (Lab.)")
    online_classes = models.PositiveIntegerField(default=0, verbose_name="Aulas On-line")
    
    # Estrutura Pedagógica [cite: 3030, 3033, 3035, 3046]
    learning_objectives = models.TextField(verbose_name="Objetivos de Aprendizagem", blank=True)
    syllabus = models.TextField(verbose_name="Ementa", blank=True)
    methodology = models.TextField(verbose_name="Metodologias Propostas",blank=True)
    assessment_criteria = models.TextField(verbose_name="Instrumentos de Avaliação Propostos",blank=True)
    
    # Bibliografias [cite: 3048, 3053]
    basic_bibliography = models.TextField(verbose_name="Bibliografia Básica", blank=True)
    complementary_bibliography = models.TextField(verbose_name="Bibliografia Complementar",blank=True)

    # Relacionamentos M2M para rastreabilidade [cite: 2884, 4744]
    competencies = models.ManyToManyField(Competence, related_name='disciplines', verbose_name="Competências Desenvolvidas")
    labs_required = models.ManyToManyField(Infrastructure, blank=True, related_name='disciplines')

    prerequisites = models.ManyToManyField(
        'self', 
        symmetrical=False, 
        blank=True, 
        related_name='required_by', 
        verbose_name="Pré-requisitos"
    )

    @property
    def total_classes(self):
        return self.theory_classes + self.lab_classes + self.online_classes

    def __str__(self):
        return f"{self.code} - {self.name}"

# --- 4. A Matriz Curricular (A Grade do PPC) ---

class CurriculumMatrix(models.Model):
    """Tabela de componentes e distribuição por semestre no PPC [cite: 2952, 2978]"""
    OFFERING_TYPES = [
        ('PRESENCIAL', 'Presencial'),
        ('ONLINE', 'On-line'),
    ]

    ppc = models.ForeignKey(PPCProposal, on_delete=models.CASCADE, related_name='matrix_items')
    discipline = models.ForeignKey(Discipline, on_delete=models.PROTECT, related_name='curriculum_allocations')
    
    semester = models.PositiveIntegerField(validators=[MinValueValidator(1)], verbose_name="Semestre")
    offering = models.CharField(max_length=20, choices=OFFERING_TYPES, default='PRESENCIAL', verbose_name="Oferta")
    is_elective = models.BooleanField(default=False, verbose_name="É optativa?") # O asterisco (*) no documento [cite: 2979]

    class Meta:
        ordering = ['semester', 'discipline__name']
        unique_together = ('ppc', 'discipline')

    def __str__(self):
        return f"{self.semester}º Sem - {self.discipline.name} ({self.ppc.version_semester})"

# --- 5. Outros Componentes Curriculares ---

class ComplementaryComponent(models.Model):
    """Componentes com horas externas à matriz de aulas [cite: 2998, 4609, 4641, 4668]"""
    COMPONENT_TYPES = [
        ('TG', 'Trabalho de Graduação'),
        ('ESTAGIO', 'Estágio Curricular Supervisionado'),
        ('AACC', 'Atividades Acadêmico-Científico-Culturais'),
    ]
    
    ppc = models.ForeignKey(PPCProposal, on_delete=models.CASCADE, related_name='complementary_components')
    type = models.CharField(max_length=20, choices=COMPONENT_TYPES)
    total_hours = models.PositiveIntegerField(verbose_name="Total de Horas")
    start_semester = models.PositiveIntegerField(verbose_name="Obrigatório a partir do Semestre")
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.get_type_display()} - {self.ppc}"
