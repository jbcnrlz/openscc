from django.db import models
from django.contrib.auth.models import User
import datetime, uuid
# Create your models here.
class Conferencia(models.Model):
    nome = models.CharField(max_length=400)
    sigla = models.CharField(max_length=20,default="")
    submissaoOpen = models.DateField()
    submissaoClose = models.DateField()
    dataEventoInicio = models.DateField()
    dataEventoFim = models.DateField()
    logo = models.FileField(upload_to='images/')
    slug = models.SlugField(default="",null=False)
    conteudoHtml = models.TextField(blank=True,null=True)

    def __str__(self):
        return self.sigla
    
    def getListaDias(self,currSelDate):
        diasDaSemana = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 
                      'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
        qtDias = (self.dataEventoFim - self.dataEventoInicio).days    
        diasConf = []
        for i in range(qtDias + 1):
            dataEvent = self.dataEventoInicio + datetime.timedelta(days=i)
            if type(currSelDate) is datetime.date:
                currSelection = 0 if dataEvent != currSelDate else 1
            else:
                currSelection = 0 if dataEvent != currSelDate.date() else 1
            diasConf.append((diasDaSemana[dataEvent.weekday()],dataEvent.strftime("%d/%m/%Y"),currSelection))

        return diasConf

class Autores(models.Model):
    nome = models.CharField(max_length=250)
    email = models.CharField(max_length=250)
    filiacao = models.CharField(max_length=400)
    principal = models.IntegerField()

    def __str__(self):
        return self.nome + " - " + self.email

def content_file_name(instance, filename):
    newFilename = str(uuid.uuid4()) + filename[filename.rfind('.'):]
    return f'artigos/{newFilename}'
class Artigo(models.Model):
    titulo = models.CharField(max_length=400)
    status = models.IntegerField()
    endereco = models.FileField(upload_to=content_file_name)
    dataEnvio = models.DateField()
    autores = models.ManyToManyField(Autores)
    conferenciaAtual = models.OneToOneField(Conferencia,default=None,on_delete=models.CASCADE, unique=False)
    user = models.OneToOneField(User,on_delete=models.CASCADE, unique=False)

    def getStatusPaper(self):
        if self.status == 0:
            return "Aguardando avaliação"
        elif self.status == 1:
            return "Aprovado"
        elif self.status == 3:
            return "Reprovado"
        elif self.status == 2:
            return "Aceito com modificações"
        else:
            return "Desconhecido"

    def __str__(self):
        return self.titulo + " - " + self.user.username

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
    conferencia = models.ForeignKey(Conferencia,on_delete=models.CASCADE,related_name='atividades')
    participantes = models.ManyToManyField(User,through='ParticipanteAtividade')

    def isAlreadyPresent(self,userID):
        ptav = ParticipanteAtividade.objects.filter(atividade=self,user__id=userID).first()
        if ptav is not None:
            return ptav.presenca
        else:
            return False

    def isUserRegitered(self,userID):
        for u in self.participantes.all():
            if u.id == userID:
                return True
        
        return False

    def canUserRegister(self,userID):        
        atvs = Atividade.objects.filter(data__exact=self.data,participantes__id=userID).all()
        print(atvs)
        if atvs.exists():
            print("ja existe")
            return False
        return True

    def __str__(self):
        return self.nome
    
class ParticipanteAtividade(models.Model):
    atividade = models.ForeignKey(Atividade,on_delete=models.CASCADE)
    user = models.ForeignKey(User,on_delete=models.CASCADE)
    presenca = models.BooleanField(default=False)
    data_registro = models.DateTimeField()

    class Meta:
        db_table = 'submission_atividade_participantes'
        managed = False

    def __str__(self):
        return f"{self.participante.username} - {self.atividade.nome}"
