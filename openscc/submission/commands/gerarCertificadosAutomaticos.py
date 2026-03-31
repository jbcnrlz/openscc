from django.core.management.base import BaseCommand
from django.utils import timezone
from submission.models import ParticipanteAtividade, Certificado
from submission.views import gerarCertificadoAutomatico

class Command(BaseCommand):
    help = 'Gera certificados automaticamente para presenças registradas'
    
    def handle(self, *args, **kwargs):
        # Buscar todas as presenças registradas sem certificado
        presencas = ParticipanteAtividade.objects.filter(
            presenca=True,
            atividade__data__date__lte=timezone.now().date()
        ).select_related('atividade', 'user')
        
        for presenca in presencas:
            # Verificar se já existe certificado
            existe = Certificado.objects.filter(
                atividade=presenca.atividade,
                participante=presenca.user,
                tipo_certificado='participacao'
            ).exists()
            
            if not existe:
                try:
                    gerarCertificadoAutomatico(presenca.atividade, presenca.user, None)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Certificado gerado para {presenca.user.username} '
                            f'na atividade {presenca.atividade.nome}'
                        )
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Erro ao gerar certificado para {presenca.user.username}: {str(e)}'
                        )
                    )