from django.views.generic import ListView
from django.db.models import Sum, Avg, Count, Q
from ..models import LLMLog
from django.contrib.auth.mixins import LoginRequiredMixin

class LLMLogListView(LoginRequiredMixin, ListView):
    model = LLMLog
    template_name = 'mimir/listarLogsLLM.html'
    context_object_name = 'logs'
    paginate_by = 20  # Exibe 20 logs por página para não pesar o navegador

    def get_queryset(self):
        # Se for superusuário vê tudo, senão vê apenas os próprios logs
        if self.request.user.is_superuser:
            return LLMLog.objects.all().order_by('-created_at')
        return LLMLog.objects.filter(user=self.request.user).order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Base de cálculo (filtrada por usuário se não for admin)
        qs = self.get_queryset()
        
        # Estatísticas básicas para os cards superiores
        stats = qs.aggregate(
            total=Count('id'),
            sucesso=Count('id', filter=Q(status='success')),
            erros=Count('id', filter=Q(status='error')),
            tempo_medio=Avg('duration_ms'),
            tokens_in=Sum('tokens_input'),
            tokens_out=Sum('tokens_output')
        )
        
        # Tratamento de nulos
        stats['tempo_medio'] = round(stats['tempo_medio'] or 0, 0)
        stats['tokens_total'] = (stats['tokens_in'] or 0) + (stats['tokens_out'] or 0)
        
        # Taxa de sucesso
        if stats['total'] > 0:
            stats['taxa_sucesso'] = round((stats['sucesso'] / stats['total']) * 100, 1)
        else:
            stats['taxa_sucesso'] = 0
            
        context['stats'] = stats
        return context