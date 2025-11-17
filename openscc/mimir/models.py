from django.db import models
from django.contrib.auth.models import User
from django.core.validators import ValidationError
import datetime
from django.utils import timezone
# Create your models here.

def isProfessor(self):
    """
    Verifica se o usuário pertence a um grupo específico
    """
    return self.groups.filter(name="Professor").exists()

User.add_to_class('isProfessor', isProfessor)

def isAluno(self):
    """
    Verifica se o usuário pertence a um grupo específico
    """
    return self.groups.filter(name="Aluno").exists()

User.add_to_class('isAluno', isAluno)

def isMembroAutorizado(self):
    """
    Verifica se o usuário pertence a um dos grupos autorizados
    """
    return self.groups.filter(name__in=["Professor", "Aluno"]).exists()

User.add_to_class('isMembroAutorizado', isMembroAutorizado)

class Assunto(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    nome = models.CharField(max_length=200, blank=False, null=False)
    layoutGuiaTutor = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nome

class TiposDePergunta(models.Model):    
    descricao = models.CharField(max_length=200, blank=False, null=False)
    textoParaLLM = models.TextField(blank=False, null=True)

    def __str__(self):
        return self.descricao

class PapelTimbrado(models.Model):
    nome = models.CharField(max_length=200, blank=False, null=False)
    papelTimbrado = models.FileField(upload_to='papeis/')

class Fontes(models.Model):
    fonte = models.FileField(upload_to='fontes/')
    nome = models.CharField(max_length=200, blank=False, null=False)
    dataCriacao = models.DateTimeField(auto_now_add=True)
    descricao = models.TextField(blank=True, null=True)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, default=1)

    def __str__(self):
        return self.nome

class Pergunta(models.Model):
    assunto = models.ForeignKey(Assunto, on_delete=models.CASCADE)
    pergunta = models.TextField(blank=False, null=False)
    gabarito = models.TextField(blank=False, null=False)
    tipoDePergunta = models.ForeignKey(TiposDePergunta, on_delete=models.CASCADE,default=1)

    @property
    def imagens(self):
        return self.imagempergunta_set.all()
    
    def get_primeira_prova(self):
        """Retorna a primeira prova associada a esta pergunta"""
        return self.prova_set.first()
    
    def get_primeira_prova_id(self):
        """Retorna o ID da primeira prova ou None"""
        primeira_prova = self.prova_set.first()
        return primeira_prova.id if primeira_prova else None

    def aplicar_feedback(self, feedback):
        """
        Aplica o feedback do especialista sobrepondo a pergunta e gabarito
        """
        if feedback.comentarios:
            # Divide o feedback em pergunta e gabarito (assumindo um formato específico)
            partes = feedback.comentarios.split('---GABARITO---')
            if len(partes) >= 1:
                self.pergunta = partes[0].strip()
            if len(partes) >= 2:
                self.gabarito = partes[1].strip()
            self.save()
    
    def get_texto_com_feedback(self):
        """
        Retorna o texto com feedback aplicado ou o original
        """
        feedback_utilizado = self.feedbacks.filter(status='utilizado').first()
        if feedback_utilizado and feedback_utilizado.comentarios:
            partes = feedback_utilizado.comentarios.split('---GABARITO---')
            return partes[0].strip() if len(partes) >= 1 else self.pergunta
        return self.pergunta
    
    def get_gabarito_com_feedback(self):
        """
        Retorna o gabarito com feedback aplicado ou o original
        """
        feedback_utilizado = self.feedbacks.filter(status='utilizado').first()
        if feedback_utilizado and feedback_utilizado.comentarios:
            partes = feedback_utilizado.comentarios.split('---GABARITO---')
            return partes[1].strip() if len(partes) >= 2 else self.gabarito
        return self.gabarito

class Prova(models.Model):
    titulo = models.CharField(max_length=200, blank=False, null=False)
    descricao = models.TextField(blank=False, null=False)
    dataCriacao = models.DateTimeField(auto_now_add=True)
    dataAtualizacao = models.DateTimeField(auto_now=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE,unique=False)
    assunto = models.ForeignKey(Assunto, on_delete=models.CASCADE)
    perguntas = models.ManyToManyField(Pergunta)

class ImagemPergunta(models.Model):
    pergunta = models.ForeignKey(Pergunta, on_delete=models.CASCADE, related_name='imagens')
    imagem = models.ImageField(upload_to='perguntas/')
    criado_em = models.DateTimeField(auto_now_add=True)

class ObjetivosAprendizagem(models.Model):
    descricao = models.CharField(max_length=200, blank=False, null=False)

    def __str__(self):
        return self.descricao

class Tema(models.Model):
    nome = models.CharField(max_length=200, blank=False, null=False)
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, default=1)

    def __str__(self):
        return self.nome

class Problema(models.Model):
    titulo = models.CharField(max_length=200, blank=False, null=False)
    assunto = models.ForeignKey(Assunto, on_delete=models.CASCADE)
    criado_em = models.DateTimeField(auto_now_add=True)
    dataAplicacao = models.DateTimeField()
    objetivos = models.ManyToManyField(ObjetivosAprendizagem)
    tema = models.ForeignKey(Tema, on_delete=models.CASCADE)
    fontes = models.ManyToManyField('Fontes', blank=True)

class Parte(models.Model):
    problema = models.ForeignKey(Problema, on_delete=models.CASCADE, related_name='partes')
    enunciado = models.TextField(blank=False, null=False)    
    ordem = models.IntegerField(default=1)

    def get_feedbacks_pendentes(self):
        """Retorna feedbacks pendentes para esta parte"""
        return self.feedbacks.filter(status='pendente')
    
    def get_feedbacks_utilizados(self):
        """Retorna feedbacks utilizados para esta parte"""
        return self.feedbacks.filter(status='utilizado')
    
    def tem_feedbacks_pendentes(self):
        """Verifica se há feedbacks pendentes"""
        return self.feedbacks.filter(status='pendente').exists()
    
    def aplicar_feedback(self, feedback):
        """
        Aplica o feedback do especialista sobrepondo o enunciado
        """
        if feedback.comentarios:
            self.enunciado = feedback.comentarios.strip()
            self.save()
    
    def get_enunciado_com_feedback(self):
        """
        Retorna o enunciado com feedback aplicado ou o original
        """
        feedback_utilizado = self.feedbacks.filter(status='utilizado').first()
        if feedback_utilizado and feedback_utilizado.comentarios:
            return feedback_utilizado.comentarios.strip()
        return self.enunciado

    @property
    def midias(self):
        """Property para acessar as mídias da parte"""
        return self.midiaparte_set.all()

class MidiaParte(models.Model):
    """
    Model para armazenar mídias (imagens, áudios, PDFs) associadas a partes do problema
    """
    TIPO_MIDIA_CHOICES = [
        ('imagem', 'Imagem'),
        ('audio', 'Áudio'),
        ('pdf', 'PDF'),
        ('video', 'Vídeo'),
        ('documento', 'Documento'),
    ]
    
    parte = models.ForeignKey(Parte, on_delete=models.CASCADE, related_name='midias')
    arquivo = models.FileField(
        upload_to='partes_midia/%Y/%m/%d/',
        help_text="Faça upload de imagens, áudios, PDFs ou outros documentos"
    )
    tipo = models.CharField(max_length=20, choices=TIPO_MIDIA_CHOICES, default='imagem')
    descricao = models.CharField(max_length=255, blank=True, null=True, help_text="Descrição opcional da mídia")
    criado_em = models.DateTimeField(auto_now_add=True)
    ordem = models.IntegerField(default=1, help_text="Ordem de exibição da mídia")
    
    class Meta:
        verbose_name = 'Mídia da Parte'
        verbose_name_plural = 'Mídias das Partes'
        ordering = ['parte', 'ordem', 'criado_em']
    
    def __str__(self):
        return f"Mídia {self.id} - Parte {self.parte.ordem} - {self.get_tipo_display()}"
    
    def get_icone_tipo(self):
        """Retorna o ícone correspondente ao tipo de mídia"""
        icones = {
            'imagem': 'fas fa-image',
            'audio': 'fas fa-music',
            'pdf': 'fas fa-file-pdf',
            'video': 'fas fa-video',
            'documento': 'fas fa-file-alt',
        }
        return icones.get(self.tipo, 'fas fa-file')
    
    def is_imagem(self):
        return self.tipo == 'imagem'
    
    def is_audio(self):
        return self.tipo == 'audio'
    
    def is_pdf(self):
        return self.tipo == 'pdf'
    
    def is_video(self):
        return self.tipo == 'video'

class GuiaTutor(models.Model):
    problema = models.OneToOneField(Problema, on_delete=models.CASCADE, related_name='guia_tutor')
    conteudo = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Guia do Tutor"
        verbose_name_plural = "Guias do Tutor"
    
    def __str__(self):
        return f"Guia do Tutor - {self.problema.titulo}"

class FeedbackEspecialista(models.Model):
    """
    Model para armazenar feedbacks de especialistas sobre partes de problemas OU perguntas de provas
    """
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('respondido', 'Respondido'),
        ('utilizado', 'Utilizado'),
    ]

    TIPO_CHOICES = [
        ('problema', 'Problema'),
        ('pergunta', 'Pergunta'),
    ]

    # Campos para problemas
    parte = models.ForeignKey(
        Parte, 
        on_delete=models.CASCADE, 
        related_name='feedbacks',
        null=True,
        blank=True
    )
    
    # Campos para perguntas
    pergunta = models.ForeignKey(
        Pergunta,
        on_delete=models.CASCADE,
        related_name='feedbacks', 
        null=True,
        blank=True
    )
    
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        default='problema'
    )

    especialista = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='feedbacks_enviados'
    )
    solicitante = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='feedbacks_solicitados'
    )
    
    comentarios = models.TextField(
        verbose_name='Comentários do Especialista',
        help_text='Feedback detalhado',
        blank=True
    )
    resposta_autor = models.TextField(
        blank=True, 
        null=True,
        verbose_name='Resposta do Autor'
    )
    
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pendente'
    )
    
    mensagem_solicitacao = models.TextField(
        blank=True, 
        null=True,
        verbose_name='Mensagem da Solicitação'
    )
    
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    respondido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Feedback de Especialista'
        verbose_name_plural = 'Feedbacks de Especialistas'
        ordering = ['-criado_em']

    def __str__(self):
        if self.tipo == 'problema':
            return f"Feedback para Parte {self.parte.ordem} - {self.especialista.get_full_name()}"
        else:
            return f"Feedback para Pergunta - {self.especialista.get_full_name()}"

    def marcar_como_utilizado(self):
        self.status = 'utilizado'
        self.save()

    def responder(self, resposta):
        self.resposta_autor = resposta
        self.status = 'respondido'
        self.respondido_em = timezone.now()
        self.save()

    @property
    def utilizado(self):
        return self.status == 'utilizado'

    @property
    def pendente(self):
        return self.status == 'pendente'

    def clean(self):
        if not self.parte and not self.pergunta:
            raise ValidationError('Deve ser associado a uma parte de problema ou uma pergunta.')
        if self.parte and self.pergunta:
            raise ValidationError('Não pode estar associado a uma parte e uma pergunta simultaneamente.')
        
    def aceitar_feedback(self):
        """
        Aceita e aplica o feedback do especialista, sobrepondo o conteúdo original
        """
        if self.tipo == 'problema' and self.parte:
            self.parte.aplicar_feedback(self)
        elif self.tipo == 'pergunta' and self.pergunta:
            self.pergunta.aplicar_feedback(self)
        
        self.status = 'utilizado'
        self.respondido_em = timezone.now()
        self.save()

    def rejeitar_feedback(self, resposta_autor=None):
        """
        Rejeita o feedback (opcionalmente com resposta do autor)
        """
        self.resposta_autor = resposta_autor
        self.status = 'respondido'
        self.respondido_em = timezone.now()
        self.save()

# Adicione ao models.py
class ProvaAluno(models.Model):
    """
    Model para gerenciar a relação aluno-prova (modelo intermediário)
    """
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('em_andamento', 'Em Andamento'),
        ('concluida', 'Concluída'),
        ('corrigida', 'Corrigida'),
    ]

    # ForeignKeys para os dois modelos relacionados
    aplicacao_prova = models.ForeignKey(
        'AplicacaoProva', 
        on_delete=models.CASCADE,
        related_name='provas_alunos'
    )
    aluno = models.ForeignKey(User, on_delete=models.CASCADE)
    
    # Removemos a FK direta para Prova, pois já temos através de aplicacao_prova
    data_inicio = models.DateTimeField(auto_now_add=True)
    data_conclusao = models.DateTimeField(null=True, blank=True)
    data_entrega = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    tempo_decorrido = models.DurationField(default=datetime.timedelta(0))
    nota_final = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ['aplicacao_prova', 'aluno']
        verbose_name = 'Prova do Aluno'
        verbose_name_plural = 'Provas dos Alunos'

    def __str__(self):
        return f"{self.aluno.username} - {self.aplicacao_prova.prova.titulo}"

    @property
    def prova(self):
        """Property para acessar a prova através da aplicação"""
        return self.aplicacao_prova.prova

    def iniciar_prova(self):
        """Marca a prova como iniciada"""
        self.status = 'em_andamento'
        self.data_inicio = timezone.now()
        self.save()

    def finalizar_prova(self):
        """Marca a prova como concluída"""
        self.status = 'concluida'
        self.data_conclusao = timezone.now()
        self.save()

    def calcular_nota(self):
        """Calcula a nota automaticamente baseada nas respostas corretas"""
        respostas = self.respostas.all()
        total_perguntas = self.aplicacao_prova.prova.perguntas.count()
        if total_perguntas == 0:
            return 0
        
        corretas = 0
        for resposta in respostas:
            if resposta.resposta_texto and resposta.pergunta.gabarito:
                # Comparação simples - em um sistema real você teria lógica mais complexa
                if resposta.resposta_texto.strip().lower() == resposta.pergunta.gabarito.strip().lower():
                    corretas += 1
        
        self.nota_final = (corretas / total_perguntas) * 10
        self.save()
        return self.nota_final

class RespostaAluno(models.Model):
    """
    Model para armazenar as respostas dos alunos às perguntas
    """
    aluno = models.ForeignKey(User, on_delete=models.CASCADE)
    pergunta = models.ForeignKey(Pergunta, on_delete=models.CASCADE)
    prova_aluno = models.ForeignKey(ProvaAluno, on_delete=models.CASCADE, related_name='respostas')
    resposta_texto = models.TextField(blank=True, null=True)
    resposta_arquivo = models.FileField(upload_to='respostas_alunos/', blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['aluno', 'pergunta', 'prova_aluno']
        verbose_name = 'Resposta do Aluno'
        verbose_name_plural = 'Respostas dos Alunos'

    def __str__(self):
        return f"Resposta de {self.aluno.username} para {self.pergunta.id}"

class AplicacaoProva(models.Model):
    """
    Model para gerenciar a aplicação de provas para turmas/alunos
    """
    prova = models.ForeignKey(Prova, on_delete=models.CASCADE)
    alunos = models.ManyToManyField(
        User, 
        through=ProvaAluno,
        related_name='aplicacoes_prova'
    )
    data_disponivel = models.DateTimeField()
    data_limite = models.DateTimeField()
    tempo_limite = models.DurationField(help_text="Tempo limite para realização da prova")
    disponivel = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Aplicação de Prova'
        verbose_name_plural = 'Aplicações de Provas'

    def __str__(self):
        return f"Aplicação: {self.prova.titulo}"

    def esta_disponivel(self):
        """Verifica se a prova está disponível para realização"""
        agora = timezone.now()
        return (self.disponivel and 
                self.data_disponivel <= agora <= self.data_limite)

    def adicionar_aluno(self, aluno):
        """Adiciona um aluno à aplicação da prova"""
        ProvaAluno.objects.get_or_create(
            aplicacao_prova=self,
            aluno=aluno,
            defaults={'status': 'pendente'}
        )

    def remover_aluno(self, aluno):
        """Remove um aluno da aplicação da prova"""
        ProvaAluno.objects.filter(aplicacao_prova=self, aluno=aluno).delete()