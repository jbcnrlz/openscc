from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import DetailView, View, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.contrib import messages
from django.urls import reverse_lazy
import requests
import json
from ..models import Problema, GuiaTutor, Parte
from ..forms import EditarGuiaTutorForm  # Vamos criar este formulário
from commons.services import chamarApiLLM, extrair_texto_pdf, criarPromptGuiaTutor

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.contrib import messages
import requests
import json
from ..models import Problema, GuiaTutor, Parte
from commons.services import chamarApiLLM, extrair_texto_pdf, criarPromptGuiaTutor

class GerarGuiaTutorView(LoginRequiredMixin, View):
    def post(self, request, problema_id):
        problema = get_object_or_404(Problema, id=problema_id)
        
        try:
            # Verificar se já existe um guia
            guia, created = GuiaTutor.objects.get_or_create(problema=problema)
            print(problema)
            # Gerar conteúdo do guia
            conteudo_guia = self.gerar_guia_tutor(problema)
            print(conteudo_guia)
            if conteudo_guia:
                guia.conteudo = conteudo_guia
                guia.save()
                
                if created:
                    messages.success(request, 'Guia do Tutor gerado com sucesso!')
                else:
                    messages.success(request, 'Guia do Tutor atualizado com sucesso!')
            else:
                messages.error(request, 'Erro ao gerar o Guia do Tutor. Tente novamente.')
                
        except Exception as e:
            messages.error(request, f'Erro ao gerar guia: {str(e)}')
        
        return redirect('mimir:problemaDetail', pk=problema_id)
    
    def gerar_guia_tutor(self, problema):
        # Obter todas as partes do problema
        partes = Parte.objects.filter(problema=problema).order_by('ordem')
        texto_problema = "\n\n".join([f"Parte {p.ordem}: {p.enunciado}" for p in partes])
        
        # Obter informações das fontes
        fontes_info = ""
        for fp in problema.fontes.all():
            conteudo_extraido = extrair_texto_pdf([fp.fonte.path,fp.nome])
            texto_completo = "\n".join(conteudo_extraido)
            fontes_info += f"FONTE - {fp.nome}\n" + texto_completo + "\n\n"
        
        prompt = criarPromptGuiaTutor(
            problema.titulo,
            problema.tema.nome,
            problema.assunto.nome,
            [obj.descricao for obj in problema.objetivos.all()],
            texto_problema,
            fontes_info,
            problema.assunto.layoutGuiaTutor or ""
        )
        print(prompt)
        return prompt.content if hasattr(prompt, 'content') else str(prompt)   

class VisualizarGuiaTutorView(LoginRequiredMixin, DetailView):
    model = Problema
    template_name = 'mimir/guiaTutor.html'
    context_object_name = 'problema'
    
    def get_queryset(self):
        return Problema.objects.filter(assunto__user=self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['guia_tutor'] = getattr(self.object, 'guia_tutor', None)
        return context

class AtualizarGuiaTutorView(LoginRequiredMixin, View):
    def post(self, request, problema_id):
        problema = get_object_or_404(Problema, id=problema_id)
        
        try:
            guia = GuiaTutor.objects.get(problema=problema)
            novo_conteudo = self.gerar_guia_tutor(problema)
            
            if novo_conteudo:
                guia.conteudo = novo_conteudo
                guia.save()
                messages.success(request, 'Guia do Tutor atualizado com sucesso!')
            else:
                messages.error(request, 'Erro ao atualizar o Guia do Tutor.')
                
        except GuiaTutor.DoesNotExist:
            messages.error(request, 'Guia do Tutor não encontrado. Gere um novo guia.')
        except Exception as e:
            messages.error(request, f'Erro ao atualizar guia: {str(e)}')
        
        return redirect('mimir:visualizarGuiaTutor', pk=problema_id)
    
    def gerar_guia_tutor(self, problema):
        # Obter todas as partes do problema
        partes = Parte.objects.filter(problema=problema).order_by('ordem')
        texto_problema = "\n\n".join([f"Parte {p.ordem}: {p.enunciado}" for p in partes])
        
        # Obter informações das fontes
        fontes_info = ""
        for fp in problema.fontes.all():
            conteudo_extraido = extrair_texto_pdf([fp.fonte.path,fp.nome])
            texto_completo = "\n".join(conteudo_extraido)
            fontes_info += f"FONTE - {fp.nome}\n" + texto_completo + "\n\n"
        
        prompt = criarPromptGuiaTutor(
            problema.titulo,
            problema.tema.nome,
            problema.assunto.nome,
            [obj.descricao for obj in problema.objetivos.all()],
            texto_problema,
            fontes_info,
            problema.assunto.layoutGuiaTutor or ""
        )
        
        return chamarApiLLM(prompt)    
    
class EditarGuiaTutorView(LoginRequiredMixin, UpdateView):
    model = GuiaTutor
    form_class = EditarGuiaTutorForm
    template_name = 'mimir/editarGuiaTutor.html'
    context_object_name = 'guia_tutor'
    
    def get_object(self, queryset=None):
        problema_id = self.kwargs.get('problema_id')
        problema = get_object_or_404(Problema, id=problema_id, assunto__user=self.request.user)
        guia_tutor = get_object_or_404(GuiaTutor, problema=problema)
        return guia_tutor
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['problema'] = self.object.problema
        return context
    
    def get_success_url(self):
        messages.success(self.request, 'Guia do Tutor editado com sucesso!')
        return reverse_lazy('mimir:visualizarGuiaTutor', kwargs={'pk': self.object.problema.id})