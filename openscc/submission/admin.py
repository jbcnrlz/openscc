from django.http import HttpResponseRedirect
from django.contrib import admin
from .models import *

@admin.action(description="Visualizar lista de inscritos")
def visualizeSubscription(modeladmin,request,queryset):
    selected = queryset.values_list("pk",flat=True)
    return HttpResponseRedirect("/inscritos/?ids=%s" % (",".join(str(pk) for pk in selected)))

class ConferenciaAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug" : ["nome"]}

class AtividadeAdmin(admin.ModelAdmin):
    exclude = ["participantes"]
    actions = [visualizeSubscription]

admin.site.register(Autores)
admin.site.register(Artigo)
admin.site.register(EnderecoInstituicao)
admin.site.register(Instituicoes)
admin.site.register(Conferencia,ConferenciaAdmin)
admin.site.register(Palestrante)
admin.site.register(TipoAtividade)
admin.site.register(Atividade,AtividadeAdmin)
# Register your models here.