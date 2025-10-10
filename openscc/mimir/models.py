from django.db import models
from django.contrib.auth.models import User
import datetime
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
    problema = models.ForeignKey(Problema, on_delete=models.CASCADE)
    enunciado = models.TextField(blank=False, null=False)    
    ordem = models.IntegerField(default=1)