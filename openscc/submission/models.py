from django.db import models
from django.contrib.auth.models import User
import datetime
# Create your models here.
class Conferencia(models.Model):
    nome = models.CharField(max_length=400)
    sigla = models.CharField(max_length=20,default="")
    submissaoOpen = models.DateField()
    submissaoClose = models.DateField()
    dataEventoInicio = models.DateField()
    dataEventoFim = models.DateField()

    def __str__(self):
        return self.sigla
    
    def getListaDias(self):
        diasDaSemana = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 
                      'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
        qtDias = (self.dataEventoFim - self.dataEventoInicio).days    
        diasConf = []
        for i in range(qtDias + 1):
            dataEvent = self.dataEventoInicio + datetime.timedelta(days=i)
            diasConf.append((diasDaSemana[dataEvent.weekday()],dataEvent.strftime("%d/%m/%Y")))

        return diasConf


class Autores(models.Model):
    nome = models.CharField(max_length=250)
    email = models.CharField(max_length=250)
    filiacao = models.CharField(max_length=400)
    principal = models.IntegerField()

class Artigo(models.Model):
    titulo = models.CharField(max_length=400)
    status = models.IntegerField()
    endereco = models.FileField()
    dataEnvio = models.DateField()
    autores = models.ManyToManyField(Autores)
    conferenciaAtual = models.OneToOneField(Conferencia,default=None,on_delete=models.CASCADE)

class EnderecoInstituicao(models.Model):
    logradouro = models.CharField(max_length=200)
    numero = models.CharField(max_length=5)
    bairro = models.CharField(max_length=200)
    cidade = models.CharField(max_length=100)
    complemento = models.CharField(max_length=200,null=True)
    cep = models.CharField(max_length=9)

class Instituicoes(models.Model):
    nome = models.CharField(max_length=400)
    telefone = models.CharField(max_length=20)
    endereco = models.ForeignKey(EnderecoInstituicao,on_delete=models.CASCADE)

class Participante(models.Model):
    user = models.OneToOneField(User,on_delete=models.CASCADE)
    instituicao = models.OneToOneField(Instituicoes, on_delete=models.CASCADE)

class Palestrante(models.Model):
    nome = models.CharField(max_length=400)
    descricao = models.TextField()

    def __str__(self):
        return self.nome

class TipoAtividade(models.Model):
    nome = models.CharField(max_length=50)
    cor = models.CharField(max_length=6)

    def __str__(self):
        return self.nome

class Atividade(models.Model):
    nome = models.CharField(max_length=150)
    descricao = models.TextField()
    data = models.DateTimeField()
    local = models.CharField(max_length=100)
    tipo = models.ForeignKey(TipoAtividade,on_delete=models.CASCADE)
    palestrante = models.ForeignKey(Palestrante,on_delete=models.CASCADE,null=True,blank=True)
    conferencia = models.ForeignKey(Conferencia,on_delete=models.CASCADE)

    def __str__(self):
        return self.nome
