from django.db.models import Q
from django.core.paginator import Paginator
from django.views.generic import ListView
from ..models import Tema

class TemaListView(ListView):
    model = Tema
    template_name = 'mimir/temaList.html'
    context_object_name = 'temas'
    paginate_by = 10
    
    def get_queryset(self):
        # Filtra apenas os temas do usuário logado
        queryset = Tema.objects.filter(usuario=self.request.user)
        # Filtro por busca
        search_query = self.request.GET.get('search', '')
        if search_query:
            queryset = queryset.filter(nome__icontains=search_query)
        
        # Ordenação
        order_by = self.request.GET.get('order_by', 'nome')
        if order_by in ['nome', '-nome', 'id', '-id']:
            queryset = queryset.order_by(order_by)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Atualiza as contagens para refletir apenas os temas do usuário logado
        user_temas_count = Tema.objects.filter(usuario=self.request.user).count()
        filtered_temas_count = self.get_queryset().count()
        
        context.update({
            'search_query': self.request.GET.get('search', ''),
            'order_by': self.request.GET.get('order_by', 'nome'),
            'total_temas': user_temas_count,  # Total de temas do usuário
            'temas_count': filtered_temas_count,  # Total após filtros
        })
        return context