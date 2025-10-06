from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from ..models import Pergunta

class PerguntasView(LoginRequiredMixin, ListView):
    model = Pergunta
    template_name = 'mimir/listarPerguntas.html'
    context_object_name = 'perguntas'
    paginate_by = 10
    
    def get_queryset(self):
        return Pergunta.objects.filter(
            assunto__user=self.request.user
        ).select_related('assunto', 'tipoDePergunta').order_by('-id')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Minhas Perguntas'
        context['total_perguntas'] = self.get_queryset().count()
        return context