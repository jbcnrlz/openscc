from django.db import models
from django.contrib.auth.models import User
import datetime, uuid
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from decimal import Decimal
# Create your models here.
def isMembroAutorizado(self):
    """
    Verifica se o usuário pertence a um dos grupos autorizados
    """
    return self.groups.filter(name__in=["Professor", "Aluno"]).exists()

User.add_to_class('isMembroAutorizado', isMembroAutorizado)

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
    
    class Meta:
        verbose_name = "Autor"
        verbose_name_plural = "Autores"
        ordering = ['-principal', 'nome']
    
    def clean(self):
        """Validações do autor"""
        if self.email and not '@' in self.email:
            raise ValidationError({'email': 'E-mail inválido.'})

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
    
    class Meta:
        verbose_name = "Artigo"
        verbose_name_plural = "Artigos"
        ordering = ['-dataEnvio']
    
    def clean(self):
        """Validações adicionais do modelo"""
        if self.dataEnvio and self.dataEnvio > timezone.now().date():
            raise ValidationError({'dataEnvio': 'A data de envio não pode ser no futuro.'})
    
    def pode_editar(self, user):
        """Verifica se o usuário pode editar o artigo"""
        return self.user == user and self.status == 0  # Apenas se estiver aguardando avaliação
    
    def get_prazo_avaliacao(self):
        """Calcula prazo estimado para avaliação"""
        if self.status == 0:  # Aguardando avaliação
            dias_decorridos = (timezone.now().date() - self.dataEnvio).days
            return max(0, 30 - dias_decorridos)  # Prazo de 30 dias
        return None

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
    endereco = models.ForeignKey(EnderecoInstituicao, on_delete=models.CASCADE)
    logo = models.ImageField(upload_to='logos_instituicoes/', blank=True, null=True)
    sigla = models.CharField(max_length=50, blank=True, null=True)
    site = models.URLField(blank=True, null=True)
    ativa = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Instituição"
        verbose_name_plural = "Instituições"
        ordering = ['nome']
    
    def __str__(self):
        return self.nome

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

    def get_conflicting_activities(self, user_id):
        """Retorna atividades conflitantes para o usuário"""
        from django.db.models import Q
        return Atividade.objects.filter(
            Q(data__date=self.data.date()),
            Q(data__time=self.data.time()),
            participantes__id=user_id
        ).exclude(id=self.id)
    
    def get_user_participation(self, user_id):
        """Retorna o objeto de participação do usuário"""
        try:
            return ParticipanteAtividade.objects.get(
                atividade=self,
                user__id=user_id
            )
        except ParticipanteAtividade.DoesNotExist:
            return None
    
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

class LayoutCertificado(models.Model):
    """Único modelo para controle de configuração de certificados"""
    nome = models.CharField(max_length=200)
    conferencia = models.ForeignKey(Conferencia, on_delete=models.CASCADE, related_name='layouts_certificado')
    ativo = models.BooleanField(default=True)
    padrao = models.BooleanField(default=False, help_text="Layout padrão para a conferência")
    
    # Relacionamento com instituições
    instituicoes = models.ManyToManyField(
        'Instituicoes', 
        blank=True,
        related_name='layouts_certificado',
        help_text="Instituições associadas a este layout"
    )
    
    # Configurações de design
    imagem_fundo = models.ImageField(upload_to='layouts_certificados/', blank=True, null=True)
    cor_fundo = models.CharField(max_length=7, default="#FFFFFF")
    cor_texto_titulo = models.CharField(max_length=7, default="#000000")
    cor_texto_corpo = models.CharField(max_length=7, default="#333333")
    fonte_titulo = models.CharField(max_length=100, default="'Times New Roman', serif")
    fonte_corpo = models.CharField(max_length=100, default="'Arial', sans-serif")
    
    # Textos do certificado
    texto_cabecalho = models.TextField(
        null=True,blank=True,
        default="Certificamos que {nome} participou da atividade {atividade}, "
                "realizada em {data}, como parte da {conferencia} ({sigla}), "
                "com carga horária de {carga_horaria} horas."
    )
    texto_rodape = models.TextField(blank=True, null=True)
    
    # Assinaturas (armazenadas como JSON)
    assinaturas = models.JSONField(default=list, blank=True, help_text="Formato: [{'nome': 'Nome', 'cargo': 'Cargo', 'imagem': 'url/imagem'}]")
    
    # Logos personalizados (além das instituições)
    logos_personalizados = models.JSONField(
        default=list, 
        blank=True, 
        help_text="Logos adicionais. Formato: [{'nome': 'Nome', 'url': 'url/logo', 'tamanho': 'pequeno|medio|grande'}]"
    )
    
    # Ordem de exibição (para instituições e logos)
    ordem_exibicao = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordem de exibição dos logos. Formato: ['instituicao_1', 'personalizado_1', 'instituicao_2']"
    )
    
    # Configurações específicas
    carga_horaria_padrao = models.DecimalField(max_digits=4, decimal_places=2, default=2.00)
    
    # Configuração de exibição de logos
    mostrar_logo_evento = models.BooleanField(default=True, help_text="Mostrar logo do evento (conferência)")
    mostrar_logo_instituicoes = models.BooleanField(default=True, help_text="Mostrar logos das instituições")
    mostrar_logos_personalizados = models.BooleanField(default=True, help_text="Mostrar logos personalizados")
    
    # Layout dos logos
    layout_logos = models.CharField(
        max_length=20,
        choices=[
            ('horizontal', 'Horizontal (em linha)'),
            ('vertical', 'Vertical (em coluna)'),
            ('grid', 'Grid (matriz)'),
        ],
        default='horizontal'
    )
    
    cidade = models.CharField(
        max_length=200, 
        blank=True, 
        null=True,
        help_text="Cidade onde ocorreu o evento (ex: 'São Paulo, SP')"
    )

    class Meta:
        verbose_name = "Layout de Certificado"
        verbose_name_plural = "Layouts de Certificados"
        ordering = ['-padrao', '-ativo', 'nome']
    
    def __str__(self):
        return f"{self.nome} ({self.conferencia.nome})"
    
    def save(self, *args, **kwargs):
        # Se marcar como padrão, desmarcar outros padrões da mesma conferência
        if self.padrao:
            LayoutCertificado.objects.filter(conferencia=self.conferencia, padrao=True).update(padrao=False)
        super().save(*args, **kwargs)
    
    def get_todos_logos_ordenados(self):
        """Retorna todos os logos ordenados para exibição"""
        logos = []
        
        # 1. Logo do evento (se configurado)
        if self.mostrar_logo_evento and self.conferencia and self.conferencia.logo:
            try:
                logos.append({
                    'tipo': 'evento',
                    'nome': self.conferencia.nome,
                    'url': self.conferencia.logo.url,
                    'tamanho': 'grande',
                    'ordem_key': 'evento'
                })
            except (AttributeError, ValueError):
                # Se não tiver logo ou URL, ignora
                pass
        
        # 2. Logos das instituições (se configurado)
        if self.mostrar_logo_instituicoes:
            for instituicao in self.instituicoes.filter(ativa=True):
                if instituicao and instituicao.logo:
                    try:
                        logos.append({
                            'tipo': 'instituicao',
                            'nome': instituicao.nome or f"Instituição {instituicao.id}",
                            'sigla': instituicao.sigla or '',
                            'url': instituicao.logo.url,
                            'tamanho': 'medio',
                            'ordem_key': f'instituicao_{instituicao.id}',
                            'instituicao_id': instituicao.id
                        })
                    except (AttributeError, ValueError):
                        # Se não tiver logo ou URL, ignora
                        pass
        
        # 3. Logos personalizados (se configurado)
        if self.mostrar_logos_personalizados and self.logos_personalizados:
            if isinstance(self.logos_personalizados, list):
                for i, logo in enumerate(self.logos_personalizados):
                    if isinstance(logo, dict):
                        # Verifica se tem os campos mínimos
                        url = logo.get('url')
                        if url:
                            logos.append({
                                'tipo': 'personalizado',
                                'nome': logo.get('nome', f'Logo {i+1}'),
                                'url': url,
                                'tamanho': logo.get('tamanho', 'medio'),
                                'ordem_key': f'personalizado_{i}'
                            })
        
        # 4. Ordenar conforme ordem_exibicao, se definida
        if self.ordem_exibicao and isinstance(self.ordem_exibicao, list):
            try:
                # Criar um mapeamento para ordenação
                ordem_dict = {item: idx for idx, item in enumerate(self.ordem_exibicao)}
                
                def ordenar_logo(logo):
                    ordem_key = logo.get('ordem_key', '')
                    return ordem_dict.get(ordem_key, 999)
                
                logos.sort(key=ordenar_logo)
            except (TypeError, ValueError):
                # Se houver erro na ordenação, mantém a ordem original
                pass
        
        return logos
    
    def get_assinaturas_formatadas(self):
        """Retorna as assinaturas formatadas para exibição"""
        return self.assinaturas if isinstance(self.assinaturas, list) else []
    
    def get_logos_formatados(self):
        """Retorna os logos formatados para exibição (compatibilidade)"""
        # Método de compatibilidade com código existente
        return self.logos_personalizados if isinstance(self.logos_personalizados, list) else []
    
    def get_logo_instituicao(self, instituicao_id):
        """Retorna o logo de uma instituição específica"""
        if instituicao_id:
            try:
                instituicao = Instituicoes.objects.get(id=instituicao_id)
                if instituicao.logo:
                    return instituicao.logo.url
            except Instituicoes.DoesNotExist:
                pass
        return None
    
    def get_configuracao_css(self):
        """Retorna configurações CSS para o layout"""
        css = {
            'background-color': self.cor_fundo,
            'color': self.cor_texto_corpo,
        }
        
        if self.imagem_fundo:
            css['background-image'] = f"url('{self.imagem_fundo.url}')"
            css['background-size'] = 'cover'
            css['background-position'] = 'center'
        
        return css
class Certificado(models.Model):
    """Modelo minimalista para certificados"""
    TIPO_CHOICES = [
        ('participacao', 'Participação'),
        ('apresentacao', 'Apresentação'),
        ('organizacao', 'Organização'),
        ('palestrante', 'Palestrante'),
        ('comissao', 'Membro de Comissão'),
        ('voluntario', 'Voluntário'),
        ('outro', 'Outro'),
    ]
    
    codigo_validacao = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    participante = models.ForeignKey(User, on_delete=models.CASCADE, related_name='certificados')
    atividade = models.ForeignKey(Atividade, on_delete=models.CASCADE, related_name='certificados', null=True, blank=True)
    layout = models.ForeignKey(LayoutCertificado, on_delete=models.CASCADE, related_name='certificados')
    
    tipo_certificado = models.CharField(max_length=20, choices=TIPO_CHOICES, default='participacao')
    data_atividade = models.DateField(default=timezone.now)
    carga_horaria = models.DecimalField(max_digits=4, decimal_places=2, default=2.00, validators=[MinValueValidator(0)])
    
    hash_validacao = models.CharField(max_length=64, blank=True)
    emitido = models.BooleanField(default=True)
    data_emissao = models.DateTimeField(auto_now_add=True)
    data_impressao = models.DateTimeField(null=True, blank=True)
    impressoes = models.IntegerField(default=0)
    publicado = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['participante', 'atividade', 'tipo_certificado']
        verbose_name = "Certificado"
        verbose_name_plural = "Certificados"
        ordering = ['-data_emissao']
    
    def __str__(self):
        return f"Certificado: {self.participante.get_full_name()} - {self.atividade.nome if self.atividade else 'Geral'}"
    
    def save(self, *args, **kwargs):
        """Gera hash de validação ao salvar"""
        if not self.hash_validacao:
            import hashlib
            texto = f"{self.codigo_validacao}{self.participante.id}{self.atividade.id if self.atividade else '0'}{self.data_emissao}"
            self.hash_validacao = hashlib.sha256(texto.encode()).hexdigest()
        
        # Se não tem data da atividade, usa data atual
        if not self.data_atividade:
            self.data_atividade = timezone.now().date()
        
        # Se não tem layout, usa o layout padrão da conferência
        if not self.layout and self.atividade:
            layout_padrao = LayoutCertificado.objects.filter(
                conferencia=self.atividade.conferencia,
                padrao=True,
                ativo=True
            ).first()
            if layout_padrao:
                self.layout = layout_padrao
        
        super().save(*args, **kwargs)
    
    def get_data_extenso(self, dataUsar=None):
        dataUsar = dataUsar if dataUsar else self.data_atividade
        """Retorna a data por extenso em português"""
        if not dataUsar:
            return ""
        
        meses = [
            'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
            'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'
        ]
        
        dia = dataUsar.day
        mes = meses[dataUsar.month - 1]
        ano = dataUsar.year
        
        return f"{dia} de {mes} de {ano}"
    
    def get_cidade_evento(self):
        """Retorna a cidade do evento"""
        # Primeiro tenta pegar do layout
        if self.layout and self.layout.cidade:
            return self.layout.cidade
        
        # Tenta pegar da primeira instituição
        if self.layout and self.layout.instituicoes.exists():
            instituicao = self.layout.instituicoes.first()
            if instituicao and instituicao.endereco:
                cidade_estado = instituicao.endereco.cidade
                if instituicao.endereco.estado:  # Adicione campo estado se necessário
                    cidade_estado += f", {instituicao.endereco.estado}"
                return cidade_estado
        
        # Fallback para cidade genérica
        return "Local do Evento"
    
    def get_texto_certificado(self):
        """Retorna o texto do certificado baseado no layout"""
        if self.layout:
            texto = self.layout.texto_cabecalho
            
            # Obter data por extenso
            data_extenso = self.get_data_extenso()
            
            # Obter cidade
            cidade = self.get_cidade_evento()
            
            # Substitui variáveis
            substituicoes = {
                '{nome}': self.participante.get_full_name() or self.participante.username,
                '{atividade}': self.atividade.nome if self.atividade else '',
                '{conferencia}': self.atividade.conferencia.nome if self.atividade else '',
                '{sigla}': self.atividade.conferencia.sigla if self.atividade else '',
                '{data}': self.data_atividade.strftime('%d/%m/%Y'),
                '{data_extenso}': data_extenso,
                '{cidade}': cidade,
                '{ano}': str(self.data_atividade.year),
                '{carga_horaria}': str(self.carga_horaria),
                '{tipo_atividade}': self.atividade.tipo.nome if self.atividade and self.atividade.tipo else '',
                '{tipo_certificado}': self.get_tipo_certificado_display(),
                '{instituicoes}': ', '.join([inst.nome for inst in self.layout.instituicoes.filter(ativa=True)]),
                '{instituicoes_siglas}': ', '.join([inst.sigla for inst in self.layout.instituicoes.filter(ativa=True) if inst.sigla]),
            }
            
            for chave, valor in substituicoes.items():
                texto = texto.replace(chave, valor)
            
            return texto
        return ""
    
    def get_rodape_certificado(self):
        """Retorna o texto do rodapé do layout"""
        return self.layout.texto_rodape or ""
    
    def get_assinaturas(self):
        """Retorna as assinaturas do layout"""
        return self.layout.get_assinaturas_formatadas()
    
    def get_todos_logos(self):
        """Retorna todos os logos ordenados do layout"""
        return self.layout.get_todos_logos_ordenados()
    
    def get_configuracao_css(self):
        """Retorna configurações CSS do layout"""
        return self.layout.get_configuracao_css() if self.layout else {}
    
    def get_layout_logos(self):
        """Retorna o tipo de layout para os logos"""
        return self.layout.layout_logos if self.layout else 'horizontal'
    
    def get_logo_evento(self):
        """Retorna o logo do evento (conferência)"""
        if self.layout and self.layout.mostrar_logo_evento and self.atividade and self.atividade.conferencia.logo:
            return self.atividade.conferencia.logo.url
        return None
    
    def pode_emitir(self):
        """Verifica se pode emitir certificado"""
        from django.utils import timezone
        hoje = timezone.now().date()
        
        # Verifica se a atividade já ocorreu
        if self.data_atividade > hoje:
            return False
        
        # Para certificados de participação, verifica presença
        if self.tipo_certificado == 'participacao' and self.atividade:
            try:
                participacao = ParticipanteAtividade.objects.get(
                    atividade=self.atividade,
                    user=self.participante
                )
                return participacao.presenca
            except ParticipanteAtividade.DoesNotExist:
                return False
        
        return True
    
    def registrar_impressao(self):
        """Registra uma impressão do certificado"""
        self.impressoes += 1
        self.data_impressao = timezone.now()
        self.save()
    
    def get_url_validacao(self, request):
        """Retorna URL completa para validação do certificado"""
        from django.urls import reverse
        url = reverse('submission:validarCertificado', args=[str(self.codigo_validacao)])
        return request.build_absolute_uri(url)
    
    def gerar_codigo_qr(self, request):
        """Gera código QR para validação"""
        import qrcode
        from io import BytesIO
        
        url_validacao = self.get_url_validacao(request)
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url_validacao)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
