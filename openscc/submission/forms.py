from django import forms
from django.contrib.auth.models import User
from .models import Artigo
from django.core.exceptions import ValidationError

class ArtigoForm(forms.ModelForm):
    class Meta:
        model = Artigo
        fields = ['titulo','endereco']

        labels = { "titulo" : "Título", "endereco" : "Artigo" }

    def __init__(self, *args, **kwargs):
        super(ArtigoForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            visible.field.widget.attrs['class'] = 'form-control'

class UserForm(forms.ModelForm):
    password1 = forms.CharField(label="Senha", widget=forms.PasswordInput)
    password2 = forms.CharField(
        label="Confirme sua senha", widget=forms.PasswordInput
    )
    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError("Senhas não batem")
        return password2

    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        for visible in self.visible_fields():
            visible.field.widget.attrs['class'] = 'form-control'

    def save(self, commit=True):
        savedUser = super().save(commit=False)
        savedUser.set_password(self.cleaned_data["password1"])
        if commit:
            savedUser.save()

        return savedUser
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]