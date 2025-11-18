# mimir/decorators.py
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect
from functools import wraps

def grupo_requerido(*nomes_grupos):
    """
    Decorator para verificar se o usuário pertence a um dos grupos especificados
    """
    def in_groups(u):
        if u.is_authenticated:
            if u.groups.filter(name__in=nomes_grupos).exists():
                return True
        return False
    
    return user_passes_test(in_groups, login_url='mimir:acessoNegado')

def acesso_mimir_requerido(view_func):
    """
    Decorator para verificar se o usuário tem acesso ao sistema Mimir
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if not request.user.isMembroAutorizado():
            return redirect('mimir:acessoNegado')
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view