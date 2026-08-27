import math
from datetime import date
from django.db import models
from django.db.models import Sum
from django.db import models
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from mimir.models import isProfessor
from mimir.models import isAluno
from django.utils import timezone
import datetime

def isMembroCEPE(self):
    """
    Verifica se o usuário pertence a um grupo específico
    """
    return self.groups.filter(name="CEPE").exists()

User.add_to_class('isAluno', isAluno)
User.add_to_class('isProfessor', isProfessor)

User.add_to_class('isMembroCEPE', isMembroCEPE)

class ScientificProject(models.Model):
    STATUS_CHOICES = [
        ('DRAFT', 'Rascunho (Aluno)'),
        ('PENDING_ADVISOR', 'Aguardando Aceite do Orientador'),
        ('ADVISOR_ACCEPTED', 'Aceito (Aguardando Submissão)'),
        ('SUBMITTED_CEPE', 'Na CEPE (Aguardando Parecerista)'),
        ('UNDER_REVIEW', 'Com Parecerista Ad-hoc'),
        ('REVIEWED', 'Parecer Emitido (Aguardando CEPE)'),
        ('CHANGES_REQUESTED', 'Aprovado com Mudanças'),
        ('IN_PROGRESS', 'Aprovado / Em Andamento'),
        ('REJECTED', 'Rejeitado'),
        ('REPORT_SUBMITTED', 'Relatório Final Entregue'),
        ('FINISHED', 'Concluído'),
    ]

    title = models.CharField(max_length=255, verbose_name="Título do Projeto")
    
    # Atores do Processo
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='my_ics')
    advisor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='advised_ics')
    reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_ics')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    
    # Arquivos e Avaliação
    project_file = models.FileField(upload_to='ic/proposals/', null=True, blank=True)
    final_report_file = models.FileField(upload_to='ic/reports/', null=True, blank=True)
    reviewer_feedback = models.TextField(blank=True, verbose_name="Parecer Técnico")
    
    # Controle de Prazos
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_renewed = models.BooleanField(default=False)

    cepe_feedback = models.TextField(blank=True, null=True, verbose_name="Observações da CEPE")
    cepe_reviewer = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='cepe_judgments',
        verbose_name="Membro da CEPE Responsável"
    )

    def approve_project(self):
        """Inicia a vigência de 1 ano ao ser aprovado pelo parecerista"""
        self.status = 'IN_PROGRESS'
        self.start_date = timezone.now().date()
        self.end_date = self.start_date + datetime.timedelta(days=365)
        self.save()

    def renew_project(self):
        """Renova por mais 1 ano (limite de 1 renovação)"""
        if not self.is_renewed and self.end_date:
            self.end_date = self.end_date + datetime.timedelta(days=365)
            self.is_renewed = True
            self.save()

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

class VestibularCampaign(models.Model):
    """Campanha de Captação e Previsão de Demanda (Yield Management)"""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='campaigns')
    name = models.CharField(max_length=150, verbose_name="Nome da Campanha (Ex: Vestibular 2026/1)")
    
    # 1. Período da Campanha (Captação)
    start_date = models.DateField(verbose_name="Início da Captação")
    end_date = models.DateField(verbose_name="Fim da Campanha")
    
    # 2. Período Oficial de Inscrições (NOVO)
    inscription_start_date = models.DateField(null=True, blank=True, verbose_name="Início das Inscrições")
    inscription_end_date = models.DateField(null=True, blank=True, verbose_name="Fim das Inscrições")
    
    # Restrições do Modelo de Otimização
    vacancies = models.PositiveIntegerField(verbose_name="Vagas Disponíveis")
    min_inscriptions = models.PositiveIntegerField(default=60, verbose_name="Mínimo de Inscritos Totais")
    
    # Taxas de Presença (1 - Evasão)
    yield_paid = models.FloatField(default=0.60, verbose_name="Taxa de Presença Esperada (Pagantes)")
    yield_sponsored = models.FloatField(default=0.72, verbose_name="Taxa de Presença Esperada (Patrocinados)")
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='my_campaigns',
        null=True, 
        blank=True
    )

    collaborators = models.ManyToManyField(
        User,
        related_name='collaborating_campaigns',
        blank=True,
        verbose_name="Colaboradores"
    )

    class Meta:
        verbose_name = "Campanha de Vestibular"
        verbose_name_plural = "Campanhas de Vestibular"
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} - {self.course.name}"

    @property
    def total_days(self):
        """Total de dias da campanha"""
        return max(1, (self.end_date - self.start_date).days + 1)
        
    @property
    def elapsed_days(self):
        """Quantos dias já se passaram desde o início"""
        hoje = date.today()
        if hoje < self.start_date: return 0
        if hoje > self.end_date: return self.total_days
        return (hoje - self.start_date).days + 1

    @property
    def accumulated_paid(self):
        return self.daily_records.aggregate(total=Sum('new_paid'))['total'] or 0

    @property
    def accumulated_sponsored(self):
        return self.daily_records.aggregate(total=Sum('sponsored_released'))['total'] or 0

    def get_yield_projections(self):
        """O Motor de Inferência: Retorna a projeção final e a cota ideal de patrocínio"""
        if self.elapsed_days == 0:
            return {'projecao_final_pagantes': 0, 's_alvo': 0, 'liberar_hoje': 0}

        # 1. Gera a Curva Logística Histórica (S-Curve) puramente com Math (sem numpy)
        dias = self.total_days
        step = 6.0 / (dias - 1) if dias > 1 else 0
        curva = [1 / (1 + math.exp(-(-3.0 + (i * step)))) for i in range(dias)]
        curva_historica = [c / curva[-1] for c in curva] # Normalizada para bater 100% no último dia

        # 2. Descobre onde estamos na curva
        dia_index = self.elapsed_days - 1
        progresso_esperado = curva_historica[dia_index]
        
        pagantes_atuais = self.accumulated_paid
        patrocinios_atuais = self.accumulated_sponsored

        # 3. Estima pagantes totais ao fim do funil
        if progresso_esperado < 0.05 or pagantes_atuais == 0:
            projecao_final = 0
        else:
            projecao_final = pagantes_atuais / progresso_esperado

        # 4. Calcula o número ótimo de patrocínios (Controlador)
        gap_vagas = self.vacancies - (self.yield_paid * projecao_final)
        s_vagas = max(0, gap_vagas / self.yield_sponsored)
        s_volume = max(0, self.min_inscriptions - projecao_final)
        
        s_alvo = math.ceil(max(s_vagas, s_volume))
        liberar_hoje = max(0, s_alvo - patrocinios_atuais)

        return {
            'progresso_esperado_pct': round(progresso_esperado * 100, 1),
            'projecao_final_pagantes': int(projecao_final),
            's_alvo': s_alvo,
            'liberar_hoje': liberar_hoje

        }

    def get_chart_data(self):
        """Prepara os dados da campanha garantindo a devolução de um JSON válido"""
        import json
        import math
        from datetime import timedelta
        
        try:
            dias = self.total_days
            labels = [(self.start_date + timedelta(days=i)).strftime('%d/%m') for i in range(dias)]

            # S-Curve
            step = 6.0 / (dias - 1) if dias > 1 else 0
            curva = [1 / (1 + math.exp(-(-3.0 + (i * step)))) for i in range(dias)]
            curva_historica = [c / curva[-1] for c in curva]

            # Projeção
            projecoes = self.get_yield_projections()
            projecao = projecoes.get('projecao_final_pagantes', 0) if projecoes else 0
            
            if projecao == 0:
                taxa = self.yield_paid if self.yield_paid > 0 else 0.60
                projecao = int(self.vacancies / taxa)
                
            linha_projetada = [round(c * projecao) for c in curva_historica]

            # Dados Reais
            records = list(self.daily_records.all().order_by('date'))
            records_dict = {r.date: r for r in records}

            linha_real_pagantes = []
            linha_real_patrocinados = []
            acumulado_p = 0
            acumulado_s = 0

            for i in range(dias):
                current_date = self.start_date + timedelta(days=i)
                
                if i < self.elapsed_days:
                    if current_date in records_dict:
                        acumulado_p += records_dict[current_date].new_paid
                        acumulado_s += records_dict[current_date].sponsored_released
                    linha_real_pagantes.append(acumulado_p)
                    linha_real_patrocinados.append(acumulado_s)
                else:
                    linha_real_pagantes.append(None)
                    linha_real_patrocinados.append(None)

            return json.dumps({
                'labels': labels,
                'projetada': linha_projetada,
                'real_pagantes': linha_real_pagantes,
                'real_patrocinados': linha_real_patrocinados,
            })
            
        except Exception as e:
            # Em caso de falha matemática, forçamos o envio de um JSON de erro válido
            return json.dumps({
                'labels': ['Erro de Cálculo', str(e)],
                'projetada': [0, 0],
                'real_pagantes': [0, 0],
                'real_patrocinados': [0, 0]
            })        
class CampaignDailyRecord(models.Model):
    """Input diário do funil para corrigir as predições do algoritmo"""
    campaign = models.ForeignKey(VestibularCampaign, on_delete=models.CASCADE, related_name='daily_records')
    date = models.DateField(default=date.today, verbose_name="Data de Registro")
    
    new_paid = models.PositiveIntegerField(default=0, verbose_name="Novos Inscrições Pagas")
    sponsored_released = models.PositiveIntegerField(default=0, verbose_name="Patrocínios Liberados Hoje")
    
    class Meta:
        ordering = ['-date']
        unique_together = ('campaign', 'date') # Apenas 1 registro por dia por campanha

    def __str__(self):
        return f"{self.date.strftime('%d/%m/%Y')} - {self.campaign.name}"

# --- 7. Gestão de Ações e Leads do Vestibular (CRM) ---

class CampaignAction(models.Model):
    """Eventos, feiras escolares ou ações de panfletagem de uma campanha"""
    STATUS_CHOICES = [
        ('PLANNED', 'Planejada'),
        ('EXECUTING', 'Em Execução'),
        ('COMPLETED', 'Concluída'),
        ('CANCELLED', 'Cancelada'),
    ]

    campaign = models.ForeignKey(
        VestibularCampaign, 
        on_delete=models.CASCADE, 
        related_name='actions',
        null=True,   # <--- Adicionado
        blank=True   # <--- Adicionado
    )

    is_global = models.BooleanField(
        default=False,
        verbose_name="Ação Global (Válida para todas as campanhas)"
    )
    
    title = models.CharField(max_length=200, verbose_name="Título da Ação (Ex: Feira na Escola Estadual)")
    description = models.TextField(verbose_name="Descrição e Objetivos", blank=True)
    scheduled_date = models.DateField(verbose_name="Data Prevista")
    location = models.CharField(max_length=200, verbose_name="Local / Endereço", blank=True)
    
    # Responsável pela execução
    responsible = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='campaign_actions', verbose_name="Responsável")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PLANNED', verbose_name="Status")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ação da Campanha"
        verbose_name_plural = "Ações da Campanha"
        ordering = ['-scheduled_date']

    def __str__(self):
        return f"{self.title} - {self.campaign.name}"


class ActionExpense(models.Model):
    """Prestação de contas: Notas fiscais, recibos de combustível, alimentação, etc."""
    action = models.ForeignKey(CampaignAction, on_delete=models.CASCADE, related_name='expenses')
    
    description = models.CharField(max_length=200, verbose_name="Descrição do Gasto (Ex: Gasolina, Lanche)")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    date_incurred = models.DateField(default=date.today, verbose_name="Data do Gasto")
    
    # O upload_to requer que MEDIA_ROOT e MEDIA_URL estejam configurados no settings.py
    receipt_file = models.FileField(upload_to='campaigns/receipts/', verbose_name="Comprovante (NF/Recibo)", null=True, blank=True)

    def __str__(self):
        return f"R$ {self.amount} - {self.description}"


class ActionPhoto(models.Model):
    """Fotos tiradas durante a ação para registro ou uso do marketing"""
    action = models.ForeignKey(CampaignAction, on_delete=models.CASCADE, related_name='photos')
    
    image = models.ImageField(upload_to='campaigns/photos/', verbose_name="Foto da Ação")
    caption = models.CharField(max_length=255, verbose_name="Legenda ou Contexto", blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class CampaignLead(models.Model):
    """Base Central de Interessados (Pré-inscrição)"""
    campaign = models.ForeignKey(
        VestibularCampaign, 
        on_delete=models.CASCADE, 
        related_name='leads',
        null=True,   # <--- Adicionado
        blank=True   # <--- Adicionado
    )
    
    # Rastreabilidade: de onde essa pessoa veio?
    source_action = models.ForeignKey(CampaignAction, on_delete=models.SET_NULL, null=True, blank=True, related_name='captured_leads', verbose_name="Ação de Origem")
    
    # Dados do prospecto
    name = models.CharField(max_length=200, verbose_name="Nome Completo")
    email = models.EmailField(verbose_name="E-mail", blank=True)
    phone = models.CharField(max_length=20, verbose_name="Celular / WhatsApp")
    
    # Qual curso chamou a atenção dele?
    interested_course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, verbose_name="Curso de Interesse")
    
    # Status de conversão para a equipe de captação trabalhar depois
    contacted = models.BooleanField(default=False, verbose_name="Já foi contatado?")
    converted_to_paid = models.BooleanField(default=False, verbose_name="Pagou a Inscrição?")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Interessado (Lead)"
        verbose_name_plural = "Interessados (Leads)"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.interested_course.name if self.interested_course else 'Sem curso definido'}"