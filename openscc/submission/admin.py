from django.contrib import admin
from .models import *

class ConferenciaAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug" : ["nome"]}

class AtividadeAdmin(admin.ModelAdmin):
    exclude = ["participantes"]

admin.site.register(Autores)
admin.site.register(Artigo)
admin.site.register(EnderecoInstituicao)
admin.site.register(Instituicoes)
admin.site.register(Conferencia,ConferenciaAdmin)
admin.site.register(Palestrante)
admin.site.register(TipoAtividade)
admin.site.register(Atividade,AtividadeAdmin)
# Register your models here.