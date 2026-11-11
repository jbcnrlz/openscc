from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from ..models import Pergunta, Assunto, TiposDePergunta

class PerguntasView(LoginRequiredMixin, ListView):
    model = Pergunta
    template_name = 'mimir/listarPerguntas.html'
    context_object_name = 'perguntas'
    paginate_by = 10
    
    def get_queryset(self):
        qs = Pergunta.objects.all().select_related('assunto', 'assunto__user', 'tipoDePergunta').order_by('-id')

        escopo = (self.request.GET.get('escopo') or 'todas').strip()
        if escopo == 'minhas':
            qs = qs.filter(assunto__user=self.request.user)

        search = (self.request.GET.get('search') or '').strip()
        assunto_id = (self.request.GET.get('assunto') or '').strip()
        tipo_id = (self.request.GET.get('tipo') or '').strip()

        if search:
            q_clean = search.lstrip('#').strip()
            if q_clean.isdigit():
                qs = qs.filter(
                    Q(id=int(q_clean)) |
                    Q(pergunta__icontains=search) |
                    Q(gabarito__icontains=search) |
                    Q(assunto__nome__icontains=search)
                )
            else:
                qs = qs.filter(
                    Q(pergunta__icontains=search) |
                    Q(gabarito__icontains=search) |
                    Q(assunto__nome__icontains=search)
                )
        if assunto_id.isdigit():
            qs = qs.filter(assunto_id=int(assunto_id))
        if tipo_id.isdigit():
            qs = qs.filter(tipoDePergunta_id=int(tipo_id))

        return qs
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Banco de Perguntas'
        context['total_perguntas'] = self.get_queryset().count()
        context['assuntos_filtro'] = Assunto.objects.all().order_by('nome')
        context['tipos_filtro'] = TiposDePergunta.objects.all().order_by('descricao')
        context['search_atual'] = (self.request.GET.get('search') or '').strip()
        context['assunto_atual'] = (self.request.GET.get('assunto') or '').strip()
        context['tipo_atual'] = (self.request.GET.get('tipo') or '').strip()
        context['escopo_atual'] = (self.request.GET.get('escopo') or 'todas').strip()
        return context