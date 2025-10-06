from .models import Fontes, Assunto, TiposDePergunta, Pergunta, Prova
from django import forms
from django.core.validators import FileExtensionValidator

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