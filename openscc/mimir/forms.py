from .models import Fontes, Assunto, TiposDePergunta, Pergunta, Prova, Tema, Problema, ObjetivosAprendizagem, FeedbackEspecialista, AplicacaoProva, VinculoAlunoAssunto
from django import forms
from django.core.validators import FileExtensionValidator
from django.contrib.auth.models import User
import datetime
class TemaForm(forms.ModelForm):
    class Meta:
        model = Tema
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Digite o nome do tema'
            })
        }
    
    def clean_nome(self):
        nome = self.cleaned_data['nome']
        if len(nome.strip()) < 3:
            raise forms.ValidationError('O nome do tema deve ter pelo menos 3 caracteres.')
        return nome

class ProvaForm(forms.ModelForm):
    class Meta:
        model = Prova
        fields = ['titulo', 'descricao', 'assunto']
        widgets = {
            'titulo': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Título da prova'
            }),
            'descricao': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Descrição da prova',
                'rows': 3
            }),
            'assunto': forms.Select(attrs={
                'class': 'form-control'
            })
        }

class PerguntaForm(forms.ModelForm):
    class Meta:
        model = Pergunta
        fields = ['assunto', 'pergunta', 'gabarito', 'tipoDePergunta']
        labels = {
            'assunto': 'Assunto',
            'pergunta': 'Enunciado da Pergunta',
            'gabarito': 'Resposta Correta (Gabarito)',
            'tipoDePergunta': 'Tipo de Pergunta'
        }
        widgets = {
            'pergunta': forms.Textarea(attrs={
                'rows': 6,
                'placeholder': 'Digite o enunciado completo da pergunta...',
                'class': 'form-control'
            }),
            'gabarito': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': 'Digite a resposta correta...',
                'class': 'form-control'
            }),
            'assunto': forms.Select(attrs={'class': 'form-select'}),
            'tipoDePergunta': forms.Select(attrs={'class': 'form-select'})
        }
    
    def __init__(self, user, *args, **kwargs):
        # Extrair 'instance' do kwargs antes de chamar o super
        instance = kwargs.get('instance', None)
        
        # Chamar o super corretamente
        super().__init__(*args, **kwargs)
        
        # Filtrar assuntos apenas do usuário logado
        self.fields['assunto'].queryset = Assunto.objects.filter(user=user)
        self.fields['tipoDePergunta'].queryset = TiposDePergunta.objects.all()

class FontesForm(forms.ModelForm):
    class Meta:
        model = Fontes
        fields = ['fonte','nome','descricao']
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control",'accept': '.pdf'}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "fonte": forms.FileInput(attrs={"class": "form-control"})
        }

    def __init__(self, *args, **kwargs):
        super(FontesForm, self).__init__(*args, **kwargs)        
        # Adiciona validação de extensão
        self.fields['fonte'].validators.append(
            FileExtensionValidator(allowed_extensions=['pdf'])
        )

class GeracaoPerguntasForm(forms.Form):
    fontes_selecionadas = forms.ModelMultipleChoiceField(
        queryset=Fontes.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="Fontes de Conteúdo"
    )
    
    # Campo dinâmico para quantidade por tipo
    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fontes_selecionadas'].queryset = Fontes.objects.filter(user=user)
        
        # Adiciona campos dinâmicos para cada tipo de pergunta
        tipos = TiposDePergunta.objects.all()
        for tipo in tipos:
            self.fields[f'quantidade_{tipo.id}'] = forms.IntegerField(
                min_value=0,
                max_value=50,
                initial=0,
                label=f"Quantidade - {tipo.nome}",
                required=False
            )
    
    assunto = forms.ModelChoiceField(
        queryset=Assunto.objects.none(),
        label="Assunto para as perguntas"
    )
    
    prompt_personalizado = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4}),
        required=False,
        label="Prompt Personalizado",
        help_text="Deixe em branco para usar o prompt padrão"
    )
    
    nivel_dificuldade = forms.ChoiceField(
        choices=[('facil', 'Fácil'), ('medio', 'Médio'), ('dificil', 'Difícil')],
        initial='medio'
    )
    
    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fontes_selecionadas'].queryset = Fontes.objects.filter(user=user)
        self.fields['assunto'].queryset = Assunto.objects.filter(user=user)

class GerarProblemaForm(forms.Form):
    tema = forms.ModelChoiceField(
        queryset=Tema.objects.none(),
        label="Tema",
        required=True
    )
    assunto = forms.ModelChoiceField(
        queryset=Assunto.objects.all(),
        label="Assunto",
        required=True
    )
    fontes = forms.ModelMultipleChoiceField(
        queryset=Fontes.objects.none(),
        label="Fontes de Referência",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Selecione as fontes que serão usadas como base para gerar o problema"
    )
    objetivos = forms.ModelMultipleChoiceField(
        queryset=ObjetivosAprendizagem.objects.all(),
        label="Objetivos de Aprendizagem",
        required=True,
        widget=forms.CheckboxSelectMultiple
    )
    num_partes = forms.IntegerField(
        label="Número de Partes",
        min_value=1,
        max_value=10,
        initial=3,
        required=True
    )
    contexto_inicial = forms.CharField(
        label="Contexto Inicial",
        widget=forms.Textarea(attrs={'rows': 4}),
        required=True,
        help_text="Descreva o cenário inicial do problema"
    )
    data_aplicacao = forms.DateTimeField(
        label="Data de Aplicação",
        required=True,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'})
    )
    
    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tema'].queryset = Tema.objects.filter(usuario=user)
        self.fields['fontes'].queryset = Fontes.objects.filter(user=user)

class RegerarParteForm(forms.Form):
    parte_ordem = forms.IntegerField(
        label="Número da Parte para Regerar",
        min_value=1,
        required=True
    )
    instrucoes = forms.CharField(
        label="Instruções para Regerar",
        widget=forms.Textarea(attrs={
            'rows': 4,
            'class': 'form-control',
            'placeholder': 'Ex: Adicione mais detalhes sobre os exames...\nMude o desfecho para...\nInclua informações sobre...'
        }),
        required=True,
        help_text="Descreva como você quer que esta parte seja modificada. Seja específico sobre o que mudar, adicionar ou remover."
    )
    
    def __init__(self, *args, **kwargs):
        max_partes = kwargs.pop('max_partes', None)
        super().__init__(*args, **kwargs)
        if max_partes:
            self.fields['parte_ordem'].widget.attrs['max'] = max_partes

class ProblemaForm(forms.ModelForm):
    fontes = forms.ModelMultipleChoiceField(
        queryset=Fontes.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )
    class Meta:
        model = Problema
        fields = ['titulo', 'assunto', 'tema', 'dataAplicacao', 'objetivos', 'fontes']
        widgets = {
            'dataAplicacao': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'objetivos': forms.CheckboxSelectMultiple(),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['tema'].queryset = Tema.objects.filter(usuario=user)
            self.fields['fontes'].queryset = Fontes.objects.filter(user=user)

class SolicitarFeedbackForm(forms.Form):
    """Form para solicitar feedback de especialista"""
    especialista_id = forms.IntegerField(
        widget=forms.HiddenInput(),
        required=True
    )
    mensagem = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Descreva quais aspectos você gostaria que o especialista avalie...'
        }),
        required=False,
        label='Mensagem para o Especialista'
    )

class ResponderFeedbackForm(forms.ModelForm):
    """Form para responder ao feedback recebido"""
    class Meta:
        model = FeedbackEspecialista
        fields = ['resposta_autor']
        widgets = {
            'resposta_autor': forms.Textarea(attrs={
                'rows': 6,
                'placeholder': 'Agradeça o feedback e comente como pretende utilizá-lo nas melhorias...',
                'class': 'form-control'
            }),
        }
        labels = {
            'resposta_autor': 'Sua Resposta'
        }

# forms.py
class AplicacaoProvaForm(forms.ModelForm):
    alunos = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(groups__name='Aluno'),
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
        required=False,  # Tornar opcional
        help_text="Selecione alunos individualmente (opcional)"
    )
    
    class Meta:
        model = AplicacaoProva
        fields = ['data_disponivel', 'data_limite', 'tempo_limite', 'disponivel', 'alunos']
        widgets = {
            'data_disponivel': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'data_limite': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'tempo_limite': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '02:00:00'}),
            'disponivel': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        assunto_id = self.data.get('assunto')
        alunos_selecionados = cleaned_data.get('alunos')
        
        # Validar que pelo menos uma forma de seleção foi usada
        if not assunto_id and not alunos_selecionados:
            raise forms.ValidationError(
                "Selecione um assunto para aplicar a prova ou selecione alunos manualmente."
            )
        
        return cleaned_data

class VinculoAlunoAssuntoForm(forms.ModelForm):
    class Meta:
        model = VinculoAlunoAssunto
        fields = ['aluno', 'assunto', 'ano', 'semestre']
        widgets = {
            'aluno': forms.Select(attrs={'class': 'form-select'}),
            'assunto': forms.Select(attrs={'class': 'form-select'}),
            'ano': forms.Select(attrs={'class': 'form-select'}),
            'semestre': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filtrar apenas usuários que são alunos
        self.fields['aluno'].queryset = User.objects.filter(groups__name='Aluno')
        # Filtrar assuntos do usuário atual (professor)
        if 'initial' in kwargs and 'user' in kwargs['initial']:
            user = kwargs['initial']['user']
            self.fields['assunto'].queryset = Assunto.objects.filter(user=user)

class VincularMultiplosAlunosForm(forms.Form):
    assunto = forms.ModelChoiceField(
        queryset=Assunto.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    ano = forms.ChoiceField(
        choices=VinculoAlunoAssunto.ANO_CHOICES,
        initial=int(datetime.date.today().year),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    semestre = forms.ChoiceField(
        choices=VinculoAlunoAssunto.SEMESTRE_CHOICES,
        initial=1,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    alunos = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(groups__name='Aluno'),
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
        required=True
    )
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['assunto'].queryset = Assunto.objects.filter(user=user)