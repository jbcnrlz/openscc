from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, CreateView, View, DeleteView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from ..models import Problema, Parte, Assunto
from ..forms import ProblemaForm, GerarProblemaForm, RegerarParteForm
from commons.services import criarPromptParaParte, chamarApiLLM, extrair_texto_pdf, regerarParte
from django.contrib.auth.models import User
from django.http import Http404
class ProblemaListView(LoginRequiredMixin, ListView):
    model = Problema
    template_name = 'mimir/problemaList.html'
    context_object_name = 'problemas'
    paginate_by = 10

    def get_queryset(self):
        return Problema.objects.filter(assunto__user=self.request.user)

class ProblemaDetailView(LoginRequiredMixin, DetailView):
    model = Problema
    template_name = 'mimir/problemaDetail.html'
    context_object_name = 'problema'

    def get_queryset(self):
        # Retorna todos os problemas para verificação manual de permissão
        return Problema.objects.all()

    def get_object(self, queryset=None):
        # Obtém o objeto normalmente
        obj = super().get_object(queryset)
        
        # Verifica as permissões
        user = self.request.user
        eh_autor = obj.assunto.usuario == user
        tem_feedback = obj.partes.filter(feedbacks__especialista=user).exists()
        
        if not (eh_autor or tem_feedback):            
            raise Http404("Problema não encontrado ou você não tem permissão para visualizá-lo.")
            
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        problema = self.object
        user = self.request.user
        
        # Obter partes ordenadas
        partes = problema.partes.all().order_by('ordem')
        
        # Verificar se o usuário é o autor do problema
        eh_autor = problema.assunto.user == user
        
        # Obter lista de especialistas (apenas para autores)
        especialistas = User.objects.filter(
            is_active=True,
            groups__name='Especialista'
        ).exclude(
            id=user.id
        ).order_by('first_name', 'last_name') if eh_autor else User.objects.none()
        
        context['partes'] = partes        
        context['regerar_form'] = RegerarParteForm(max_partes=partes.count()) if eh_autor else None
        context['especialistas'] = especialistas
        context['eh_autor'] = eh_autor
        context['user'] = user
        
        return context
class GerarProblemaView(LoginRequiredMixin, View):
    template_name = 'mimir/gerarProblema.html'
    
    def get(self, request):
        form = GerarProblemaForm(user=request.user)
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        form = GerarProblemaForm(request.user, request.POST)
        
        if form.is_valid():
            try:
                # Dados do formulário
                tema = form.cleaned_data['tema']
                assunto = form.cleaned_data['assunto']
                objetivos = form.cleaned_data['objetivos']
                fontes_selecionadas = form.cleaned_data['fontes']
                num_partes = form.cleaned_data['num_partes']
                contexto_inicial = form.cleaned_data['contexto_inicial']
                
                # Criar problema base
                problema = Problema.objects.create(
                    titulo=f"Problema em {tema.nome} - {assunto.nome}",
                    assunto=assunto,
                    tema=tema,
                    dataAplicacao=form.cleaned_data['data_aplicacao'],
                )
                problema.objetivos.set(objetivos)
                problema.fontes.set(fontes_selecionadas)

                completoTudo = ""
                for fp in fontes_selecionadas:
                    conteudo_extraido = extrair_texto_pdf([fp.fonte.path,fp.nome])
                    texto_completo = "\n".join(conteudo_extraido)
                    completoTudo += f"FONTE - {fp.nome}\n" + texto_completo + "\n\n"
                    
                # Gerar partes sequencialmente
                partes_geradas = self.gerar_partes_sequenciais(
                    tema.nome, 
                    assunto.nome, 
                    [obj.descricao for obj in objetivos],
                    num_partes, 
                    contexto_inicial,
                    completoTudo
                )
                
                # Salvar partes no banco
                for i, enunciado in enumerate(partes_geradas, 1):
                    Parte.objects.create(
                        problema=problema,
                        enunciado=enunciado,
                        ordem=i
                    )
                
                messages.success(request, 'Problema gerado com sucesso!')
                return redirect('mimir:problemaDetail', pk=problema.pk)
                
            except Exception as e:
                messages.error(request, f'Erro ao gerar problema: {str(e)}')
                return render(request, self.template_name, {'form': form})
        
        return render(request, self.template_name, {'form': form})
    
    def gerar_partes_sequenciais(self, tema, assunto, objetivos, num_partes, contexto_inicial,conteudo_fontes):
        partes = []
        contexto_accumulado = contexto_inicial
        
        for parte_num in range(1, num_partes + 1):
            prompt = criarPromptParaParte(tema, assunto, objetivos, parte_num, num_partes, contexto_accumulado,conteudo_fontes)
            resposta = chamarApiLLM(prompt)
            if resposta:
                partes.append(resposta)
                contexto_accumulado += f"\n\nParte {parte_num}: {resposta}"
            else:
                # Fallback se a API falhar
                partes.append(f"Parte {parte_num}: Desenvolvimento do problema.")
        
        return partes

class RegerarParteView(LoginRequiredMixin, View):
    def get(self, request, problema_id, parte_ordem=None):
        problema = get_object_or_404(Problema, id=problema_id)

        if parte_ordem is None:
            parte_ordem = request.GET.get('parte_ordem')

        try:
            parte = get_object_or_404(Parte, problema=problema, ordem=parte_ordem)
            
            form = RegerarParteForm(initial={
                'parte_ordem': parte_ordem,
                'instrucoes': f"Melhore a parte {parte_ordem} mantendo o contexto geral..."
            })
            
            context = {
                'problema': problema,
                'parte': parte,
                'form': form,
                'parte_ordem': parte_ordem
            }
            return render(request, 'mimir/regerarParteForm.html', context)
        except (ValueError, Parte.DoesNotExist):
            messages.error(request, f'Parte {parte_ordem} não encontrada.')
            return self.mostrar_selecao_parte(request, problema)
    
    def mostrar_selecao_parte(self, request, problema):
        """Mostra página para selecionar qual parte regerar"""
        partes = Parte.objects.filter(problema=problema).order_by('ordem')
        context = {
            'problema': problema,
            'partes': partes
        }
        return render(request, 'mimir/selecionarParteRegerar.html', context)

    def post(self, request, problema_id,parte_ordem=None):
        problema = get_object_or_404(Problema, id=problema_id)        
        
        # Se parte_ordem não veio na URL, pega do formulário
        parte_ordem = request.POST.get('parte_ordem')

        form = RegerarParteForm(request.POST)

        if form.is_valid():
            parte_ordem = form.cleaned_data['parte_ordem']
            instrucoes = form.cleaned_data['instrucoes']
            
            try:
                # Obter a parte específica
                parte = Parte.objects.get(problema=problema, ordem=parte_ordem)
                
                # Obter partes anteriores para contexto
                partes_anteriores = Parte.objects.filter(
                    problema=problema, 
                    ordem__lt=parte_ordem
                ).order_by('ordem')
                
                contexto_anterior = problema.contexto_inicial if hasattr(problema, 'contexto_inicial') else ""
                for p in partes_anteriores:
                    contexto_anterior += f"\n\nParte {p.ordem}: {p.enunciado}"
                
                # Obter conteúdo das fontes
                completoTudo = ""
                for fp in problema.fontes.all():
                    conteudo_extraido = extrair_texto_pdf([fp.fonte.path,fp.nome])
                    texto_completo = "\n".join(conteudo_extraido)
                    completoTudo += f"FONTE - {fp.nome}\n" + texto_completo + "\n\n"
                
                # Gerar nova parte
                prompt = regerarParte(
                    problema.tema.nome, 
                    problema.assunto.nome,
                    [obj.descricao for obj in problema.objetivos.all()],
                    parte_ordem, 
                    contexto_anterior,
                    completoTudo,
                    instrucoes,
                    parte.enunciado
                )
                nova_parte = chamarApiLLM(prompt)
                
                if nova_parte:
                    # Atualizar a parte existente
                    parte.enunciado = nova_parte
                    parte.save()
                    
                    messages.success(request, f'Parte {parte_ordem} regerada com sucesso!')
                else:
                    messages.error(request, 'Erro ao regerar a parte. Tente novamente.')
                    
            except Parte.DoesNotExist:
                messages.error(request, 'Parte não encontrada.')
            except Exception as e:
                messages.error(request, f'Erro ao regerar parte: {str(e)}')
        
        return redirect('mimir:problemaDetail', pk=problema_id)

class ProblemaCreateView(LoginRequiredMixin, CreateView):
    model = Problema
    form_class = ProblemaForm
    template_name = 'mimir/problemaForm.html'
    success_url = reverse_lazy('mimir:problemaList')
    
    def form_valid(self, form):
        return super().form_valid(form)
    
class ProblemaDeleteView(LoginRequiredMixin, DeleteView):
    model = Problema
    template_name = 'mimir/problemaConfirmDelete.html'
    success_url = reverse_lazy('mimir:problemaList')
    context_object_name = 'problema'

    def get_queryset(self):
        return Problema.objects.filter(tema__usuario=self.request.user)

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Problema excluído com sucesso!')
        return super().delete(request, *args, **kwargs)

class ProblemaDeleteAjaxView(LoginRequiredMixin, View):
    """View para exclusão via AJAX"""
    
    def post(self, request, pk):
        problema = get_object_or_404(Problema, pk=pk)
        
        try:
            problema_title = problema.titulo
            problema.delete()
            return JsonResponse({
                'success': True,
                'message': f'Problema "{problema_title}" excluído com sucesso!'
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Erro ao excluir problema: {str(e)}'
            })