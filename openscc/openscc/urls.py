from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.conf import settings
from django.views.generic.base import RedirectView
from django.contrib.auth import views as auth_views # <-- Adicione este import

admin.site.site_title = "OpenSCC - Sistema Aberto de Controle de Conferência"
admin.site.site_header = "Administração do Sistema"

urlpatterns = [
    path("admin/", admin.site.urls),
    path('login', RedirectView.as_view(url='login/', permanent=True)),
    
    # <-- ADICIONE ESTA LINHA AQUI (Antes do include do auth.urls) -->
    path('accounts/login/', auth_views.LoginView.as_view(template_name='submission/login.html'), name='login'),
    
    path("accounts/", include("django.contrib.auth.urls")),
    path("mimir/", include("mimir.urls")),
    path('odin/', include('odin.urls')),
    path("", include("submission.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)