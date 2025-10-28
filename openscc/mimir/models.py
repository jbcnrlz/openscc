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