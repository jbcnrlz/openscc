import base64
import datetime
import io
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone
from PIL import Image

META_START_MARKER = "<!-- MIMIR_UNIFICADA_META:"
META_END_MARKER = "-->"

DEFAULT_QUOTAS = {
    "cg_objetivas": 3,
    "cg_dissertativa": 1,
    "materia_objetivas": 3,  # por matéria (assunto) do módulo
    "dissertativa_tecnica": 1,
    "sensacao_aluno": 3,
}

DEFAULT_QUOTAS_SIMPLES = {
    "cg_objetivas": 0,
    "cg_dissertativa": 0,
    "materia_objetivas": 5,  # questões objetivas da matéria
    "dissertativa_tecnica": 2,  # questões dissertativas da matéria
    "sensacao_aluno": 0,
}

SECOES_UNIFICADA = {
    "cg_objetivas": {
        "codigo": "cg_objetivas",
        "titulo": "Parte I — Conhecimentos Gerais (Objetivas)",
        "titulo_curto": "Conhecimentos Gerais (Obj.)",
        "icone": "fas fa-globe-americas",
        "cor": "primary",
        "tipo_esperado": "objetiva",
        "peso_padrao": 1,
        "descricao": "Questões de múltipla escolha avaliando repertório geral, interpretação e raciocínio crítico.",
    },
    "cg_dissertativa": {
        "codigo": "cg_dissertativa",
        "titulo": "Parte II — Questão Dissertativa (Conhecimento Geral)",
        "titulo_curto": "Dissertativa Geral",
        "icone": "fas fa-pen-fancy",
        "cor": "info",
        "tipo_esperado": "dissertativa",
        "peso_padrao": 2,
        "descricao": "Questão aberta de argumentação, articulação de ideias e leitura de mundo.",
    },
    "materia_objetivas": {
        "codigo": "materia_objetivas",
        "titulo": "Parte III — Conhecimentos Específicos por Matéria do Módulo",
        "titulo_curto": "Matérias do Módulo (Obj.)",
        "icone": "fas fa-layer-group",
        "cor": "success",
        "tipo_esperado": "objetiva",
        "peso_padrao": 1,
        "descricao": "Questões objetivas distribuídas entre os assuntos (disciplinas) que compõem o módulo do aluno.",
    },
    "dissertativa_tecnica": {
        "codigo": "dissertativa_tecnica",
        "titulo": "Parte IV — Questão Dissertativa Técnica",
        "titulo_curto": "Dissertativa Técnica",
        "icone": "fas fa-microchip",
        "cor": "warning",
        "tipo_esperado": "dissertativa",
        "peso_padrao": 2,
        "descricao": "Estudo de caso ou problema técnico integrando os conhecimentos específicos do módulo.",
    },
    "sensacao_aluno": {
        "codigo": "sensacao_aluno",
        "titulo": "Parte V — Sensação do Aluno sobre a Avaliação",
        "titulo_curto": "Sensação do Aluno",
        "icone": "fas fa-smile",
        "cor": "secondary",
        "tipo_esperado": "sensacao",
        "peso_padrao": 0,
        "descricao": "Autoavaliação sobre sentimento, segurança no conteúdo, tempo de prova e percepção do módulo (peso 0 na nota).",
    },
}

ORDEM_SECOES = [
    "cg_objetivas",
    "cg_dissertativa",
    "materia_objetivas",
    "dissertativa_tecnica",
    "sensacao_aluno",
]

QUESTOES_SENSACAO_PADRAO = [
    {
        "tipo": "Múltipla Escolha",
        "enunciado": (
            "[Autoavaliação — Sensação do Aluno] Como você descreve a sua sensação geral de preparo "
            "e confiança ao responder as questões deste módulo?\n\n"
            "A) Muito confiante: dominei a maior parte dos assuntos cobrados no módulo.\n"
            "B) Confiante: compreendi bem os temas principais, com dúvidas pontuais.\n"
            "C) Moderadamente seguro: lembrei de parte dos conceitos, mas senti dificuldade em conectar alguns temas.\n"
            "D) Inseguro: tive dificuldade na maioria das questões técnicas do módulo.\n"
            "E) Muito inseguro / ansioso: não me senti preparado para a avaliação deste módulo."
        ),
        "gabarito": "A (Questão diagnóstica de percepção do aluno — qualquer alternativa marcada é válida, peso 0 na nota).",
    },
    {
        "tipo": "Múltipla Escolha",
        "enunciado": (
            "[Autoavaliação — Percepção da Prova] Em relação à clareza das questões, nível de complexidade "
            "e tempo disponível para realizar esta Avaliação Unificada, qual foi a sua percepção?\n\n"
            "A) O tempo foi folgado e o nível de exigência estava totalmente alinhado às aulas.\n"
            "B) O tempo foi suficiente e o nível de dificuldade foi adequado (justo).\n"
            "C) O nível estava adequado, porém senti que o tempo para as questões dissertativas foi curto.\n"
            "D) Achei a prova extensa e com nível de complexidade acima do trabalhado em sala.\n"
            "E) Tive muita dificuldade de interpretação dos enunciados e gestão do tempo."
        ),
        "gabarito": "B (Questão diagnóstica de percepção do aluno — qualquer alternativa marcada é válida, peso 0 na nota).",
    },
    {
        "tipo": "Múltipla Escolha",
        "enunciado": (
            "[Autoavaliação — Aproveitamento no Módulo] De modo geral, como você avalia a sua evolução prática "
            "e integração entre as matérias (disciplinas) deste módulo?\n\n"
            "A) Excelente: consegui conectar todas as disciplinas do módulo com facilidade.\n"
            "B) Muito boa: tive bom aproveitamento na maioria das disciplinas do módulo.\n"
            "C) Regular: compreendi as matérias isoladamente, mas tive dificuldade em integrá-las.\n"
            "D) Insuficiente: senti lacunas importantes de base em mais de uma matéria do módulo.\n"
            "E) Preciso de apoio pedagógico/tutoria urgente para recuperar os conteúdos deste módulo."
        ),
        "gabarito": "A (Questão diagnóstica de percepção do aluno — qualquer alternativa marcada é válida, peso 0 na nota).",
    },
]


def extrair_meta_unificada(descricao_raw: str) -> Tuple[str, Optional[dict]]:
    """
    Separa a descrição visível da prova e o dicionário JSON de metadados da prova
    (tanto para Avaliações Unificadas quanto para Provas Regulares/Simples).
    """
    if not descricao_raw:
        return "", None
    idx = descricao_raw.find(META_START_MARKER)
    if idx == -1:
        return descricao_raw.strip(), None

    texto_limpo = descricao_raw[:idx].strip()
    resto = descricao_raw[idx + len(META_START_MARKER) :]
    end_idx = resto.find(META_END_MARKER)
    json_str = resto[:end_idx].strip() if end_idx != -1 else resto.strip()
    try:
        meta = json.loads(json_str)
        if isinstance(meta, dict):
            return texto_limpo, meta
    except Exception:
        pass
    return texto_limpo, None


def empacotar_meta_unificada(descricao_limpa: str, meta: dict) -> str:
    """
    Empacota a descrição visível com o bloco oculto de metadados JSON da prova,
    preservando `is_unificada` (True para Unificada de Módulo, False para Prova Simples).
    """
    meta = dict(meta or {})
    meta["is_unificada"] = bool(meta.get("is_unificada", False))
    json_compact = json.dumps(meta, ensure_ascii=False)
    base = (descricao_limpa or "").strip()
    return f"{base}\n\n{META_START_MARKER}{json_compact}{META_END_MARKER}"


def _extrair_letra_gabarito(gabarito_texto: str) -> str:
    """
    Extrai a alternativa correta (A, B, C, D ou E) a partir do texto do gabarito de uma questão objetiva.
    """
    if not gabarito_texto:
        return ""
    txt = gabarito_texto.strip()
    if len(txt) == 1 and txt.upper() in "ABCDE":
        return txt.upper()
    padroes = [
        r"(?:gabarito|alternativa\s+correta|resposta\s+correta|letra|opção)\s*[:\-]?\s*\(?([A-Ea-e])\)?(?:\b|[\)\.\-\s])",
        r"^\s*\(?([A-Ea-e])[\)\.\-\s]",
        r"\b([A-E])\)",
    ]
    for p in padroes:
        m = re.search(p, txt, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    if txt[0].upper() in "ABCDE":
        return txt[0].upper()
    return ""


def tem_alternativas_no_texto(texto: str) -> bool:
    """
    Verifica se o texto da questão realmente contém alternativas de múltipla escolha
    (pelo menos as opções A e B em início de linha, fora de blocos de código ```).
    Evita falsos positivos com subitens dissertativos '(a) ... (b) ...' no meio de parágrafos.
    """
    if not texto:
        return False
    sem_codigo = re.sub(r"```[\s\S]*?```", "", texto)
    tem_a = bool(re.search(r"(?m)^\s*(?:A[\)\.\-:]|\(A\))\s+\S", sem_codigo))
    tem_b = bool(re.search(r"(?m)^\s*(?:B[\)\.\-:]|\(B\))\s+\S", sem_codigo))
    return tem_a and tem_b


def is_pergunta_objetiva(pergunta) -> bool:
    """
    Identifica com precisão se uma instância de Pergunta é Objetiva (Múltipla Escolha / V ou F)
    ou Dissertativa (Aberta):
      1. Se o enunciado possui alternativas explícitas A) e B) em linhas próprias -> Objetiva (True).
      2. Se o título/texto ou o Tipo de Pergunta indica 'Dissertativa'/'Discursiva'/'Aberta'
         e NÃO há alternativas A) e B) no texto -> Dissertativa (False).
      3. Se NÃO há alternativas A) e B) no texto da questão e o gabarito não é uma letra isolada (A-E),
         trata como Dissertativa (False) mesmo que o tipoDePergunta tenha ficado no default=1.
    """
    texto = (
        pergunta.get_texto_com_feedback()
        if hasattr(pergunta, "get_texto_com_feedback")
        else (getattr(pergunta, "pergunta", "") or "")
    )
    gabarito = (
        pergunta.get_gabarito_com_feedback()
        if hasattr(pergunta, "get_gabarito_com_feedback")
        else (getattr(pergunta, "gabarito", "") or "")
    ).strip()

    # 1. Se o texto contém claramente o bloco de alternativas A) e B) em início de linha, é objetiva
    if tem_alternativas_no_texto(texto):
        return True

    # 2. Se não tem alternativas A) e B) no enunciado, verifica marcadores dissertativos no texto ou tipo
    texto_low = texto.lower()
    if any(m in texto_low[:120] for m in ["[questão dissertativa", "questão dissertativa", "dissertativa técnica", "dissertativa de conhecimento"]):
        return False

    desc = ""
    if getattr(pergunta, "tipoDePergunta_id", None) and getattr(pergunta, "tipoDePergunta", None):
        desc = (pergunta.tipoDePergunta.descricao or "").lower()
        if any(k in desc for k in ["dissertativa", "discursiva", "aberta", "técnica", "tecnica", "redação", "redacao"]):
            return False

    # 3. Se o enunciado NÃO possui alternativas A) e B), só pode ser objetiva se o gabarito
    # for estritamente uma alternativa curta (ex: "A", "B", "Letra C")
    gabarito_eh_apenas_letra = bool(
        re.match(r"^\s*(?:letra|alternativa|opção|gabarito)?\s*[:\-]?\s*\(?[A-Ea-e]\)?\s*\.?\s*$", gabarito, re.IGNORECASE)
    )
    if not gabarito_eh_apenas_letra:
        return False

    if getattr(pergunta, "tipoDePergunta_id", None) and getattr(pergunta, "tipoDePergunta", None):
        if hasattr(pergunta.tipoDePergunta, "is_objetiva"):
            return bool(pergunta.tipoDePergunta.is_objetiva)

    if any(k in desc for k in ["múltipla", "multipla", "objetiva", "multiple", "verdadeiro", "alternativa", "asserção", "assercao", "afirmativa", "escolha"]):
        return True
    return False


def garantir_tipos_pergunta_unificada() -> dict:
    """
    Garante que existam os TiposDePergunta necessários para a Avaliação Unificada:
    - objetiva (Múltipla Escolha)
    - dissertativa (Dissertativa)
    - sensacao (Sensação do Aluno / Autoavaliação)
    """
    from .models import TiposDePergunta

    tipo_obj = (
        TiposDePergunta.objects.filter(descricao__icontains="Múltipla").first()
        or TiposDePergunta.objects.filter(descricao__icontains="Multipla").first()
        or TiposDePergunta.objects.filter(descricao__icontains="Objetiva").first()
    )
    if not tipo_obj:
        tipo_obj = TiposDePergunta.objects.create(
            descricao="Múltipla Escolha",
            textoParaLLM="Questão objetiva com 5 alternativas (A, B, C, D, E) e apenas uma correta.",
        )

    tipo_diss = (
        TiposDePergunta.objects.filter(descricao__icontains="Dissertativa").first()
        or TiposDePergunta.objects.filter(descricao__icontains="Discursiva").first()
    )
    if not tipo_diss:
        tipo_diss = TiposDePergunta.objects.create(
            descricao="Dissertativa",
            textoParaLLM="Questão aberta dissertativa exigindo argumentação conceitual e padrão de resposta estruturado.",
        )

    return {
        "objetiva": tipo_obj,
        "dissertativa": tipo_diss,
        "sensacao": tipo_obj,
    }


def garantir_tipos_pergunta_basicos():
    tipos = garantir_tipos_pergunta_unificada()
    return tipos["objetiva"], tipos["dissertativa"]


def garantir_assunto_auxiliar(user, nome_assunto: str):
    """
    Obtém ou cria um Assunto auxiliar para o professor (ex: 'Conhecimentos Gerais' ou 'Sensação do Aluno').
    """
    from .models import Assunto

    existente = Assunto.objects.filter(user=user, nome__iexact=nome_assunto).first()
    if existente:
        return existente
    return Assunto.objects.create(
        user=user,
        nome=nome_assunto,
        layoutGuiaTutor=f"Eixo estrutural da Avaliação Unificada: {nome_assunto}",
    )


def inferir_secao_pergunta(pergunta, meta: dict) -> Tuple[str, Optional[int]]:
    """
    Determina a qual seção da prova pertence uma pergunta,
    usando `question_map` (ou `mapa_questoes`) salvo nos metadados ou inferindo pelo assunto/texto/tipo.
    Corrige automaticamente caso uma questão dissertativa tenha sido mapeada por engano em seção objetiva.
    """
    q_map = (meta or {}).get("question_map") or (meta or {}).get("mapa_questoes") or {}
    pid_str = str(pergunta.id)
    texto_lower = (pergunta.pergunta or "").lower()
    assunto_nome_lower = (pergunta.assunto.nome or "").lower() if pergunta.assunto_id else ""
    objetiva = is_pergunta_objetiva(pergunta)
    is_unificada_flag = bool((meta or {}).get("is_unificada", False))
    is_cg = any(
        k in assunto_nome_lower or k in texto_lower[:90]
        for k in ["conhecimento geral", "conhecimentos gerais", "atualidades"]
    )

    if pid_str in q_map:
        info = q_map[pid_str]
        sec_salva = info.get("secao", "materia_objetivas")
        aid_salvo = info.get("assunto_id", pergunta.assunto_id)
        # Se a questão é claramente dissertativa (sem alternativas A-E) mas foi vinculada
        # pelo explorador geral com 'materia_objetivas' ou 'cg_objetivas', redireciona para a seção dissertativa!
        if not objetiva and sec_salva in ("materia_objetivas", "cg_objetivas"):
            if is_unificada_flag and (sec_salva == "cg_objetivas" or is_cg):
                return "cg_dissertativa", aid_salvo
            return "dissertativa_tecnica", aid_salvo
        return sec_salva, aid_salvo

    if (
        "sensação" in texto_lower
        or "percepção da prova" in texto_lower
        or "autoavaliação" in texto_lower
        or "sensação" in assunto_nome_lower
    ):
        return "sensacao_aluno", pergunta.assunto_id

    if not is_unificada_flag:
        if not objetiva:
            return "dissertativa_tecnica", pergunta.assunto_id
        return "materia_objetivas", pergunta.assunto_id

    if is_cg:
        return ("cg_objetivas" if objetiva else "cg_dissertativa"), pergunta.assunto_id

    if not objetiva:
        return "dissertativa_tecnica", pergunta.assunto_id

    return "materia_objetivas", pergunta.assunto_id


def construir_estrutura_unificada(prova) -> dict:
    """
    Constrói a estrutura completa da Avaliação (Unificada de Módulo ou Prova Regular/Simples)
    para gerenciamento, diagramação/impressão OMR/Foto e correção por foto.
    """
    from .models import Assunto

    descricao_limpa, meta = extrair_meta_unificada(prova.descricao)

    # Restaura automaticamente provas simples que tinham sido convertidas por engano ao abrir a tela
    if (
        isinstance(meta, dict)
        and meta.get("is_unificada") is True
        and not meta.get("confirmada_unificada")
        and prova.assunto_id
        and meta.get("modulo_nome") == f"Módulo - {prova.assunto.nome}"
    ):
        q_map_chk = meta.get("question_map") or {}
        tem_secao_exclusiva_unificada = any(
            isinstance(v, dict) and v.get("secao") in ("cg_objetivas", "cg_dissertativa", "sensacao_aluno")
            for v in q_map_chk.values()
        )
        if not tem_secao_exclusiva_unificada:
            meta["is_unificada"] = False
            meta["modulo_nome"] = prova.assunto.nome
            meta["quotas"] = dict(DEFAULT_QUOTAS_SIMPLES)
            prova.descricao = empacotar_meta_unificada(descricao_limpa, meta)
            prova.save(update_fields=["descricao"])

    if not meta:
        meta = {
            "is_unificada": False,
            "modulo_nome": prova.assunto.nome if prova.assunto_id else "Avaliação Regular",
            "assuntos_ids": [prova.assunto_id] if prova.assunto_id else [],
            "quotas": dict(DEFAULT_QUOTAS_SIMPLES),
            "question_map": {},
        }

    is_unificada_flag = bool(meta.get("is_unificada", False))
    base_quotas = DEFAULT_QUOTAS if is_unificada_flag else DEFAULT_QUOTAS_SIMPLES
    quotas = dict(base_quotas)
    quotas.update(meta.get("quotas") or meta.get("config_quantidades") or {})

    assuntos_ids = meta.get("assuntos_ids") or ([prova.assunto_id] if prova.assunto_id else [])
    assuntos_qs = list(Assunto.objects.filter(id__in=assuntos_ids))
    assuntos_map = {a.id: a for a in assuntos_qs}
    assuntos_ordenados = [assuntos_map[aid] for aid in assuntos_ids if aid in assuntos_map]
    if not assuntos_ordenados and prova.assunto_id:
        assuntos_ordenados = [prova.assunto]
        assuntos_ids = [prova.assunto_id]

    perguntas_all = list(
        prova.perguntas.all().select_related("assunto", "tipoDePergunta").prefetch_related("imagens")
    )

    agrupadas = {
        "cg_objetivas": [],
        "cg_dissertativa": [],
        "materia_objetivas": {a.id: [] for a in assuntos_ordenados},
        "dissertativa_tecnica": [],
        "sensacao_aluno": [],
    }

    q_map = meta.get("question_map") or meta.get("mapa_questoes") or {}

    for p in perguntas_all:
        secao, assunto_ref_id = inferir_secao_pergunta(p, meta)
        if secao == "materia_objetivas":
            target_aid = assunto_ref_id if assunto_ref_id in agrupadas["materia_objetivas"] else p.assunto_id
            if target_aid in agrupadas["materia_objetivas"]:
                agrupadas["materia_objetivas"][target_aid].append(p)
            elif assuntos_ordenados:
                agrupadas["materia_objetivas"][assuntos_ordenados[0].id].append(p)
            else:
                agrupadas["cg_objetivas"].append(p)
        elif secao in agrupadas:
            agrupadas[secao].append(p)
        else:
            agrupadas["cg_objetivas"].append(p)

    questoes_numeradas = []
    secoes_dict = {}
    contador_global = 1

    for cod in ORDEM_SECOES:
        sec_def = SECOES_UNIFICADA[cod]
        if cod != "materia_objetivas":
            lista_p = agrupadas[cod]
            meta_qtd = int(quotas.get(cod, DEFAULT_QUOTAS[cod]))
            itens_sec = []
            for p in lista_p:
                # Se a questão está em uma seção dissertativa (Parte II ou Parte IV),
                # ela é SEMPRE tratada como dissertativa (exceto se tiver alternativas A) e B) explícitas)
                if cod in ("cg_dissertativa", "dissertativa_tecnica"):
                    obj_flag = False
                else:
                    obj_flag = is_pergunta_objetiva(p)
                peso_sugerido = 0 if cod == "sensacao_aluno" else (2 if not obj_flag else 1)
                letra_gab = _extrair_letra_gabarito(p.get_gabarito_com_feedback()) if obj_flag else ""
                item = {
                    "numero": contador_global,
                    "numero_fmt": f"Q{contador_global:02d}",
                    "pergunta": p,
                    "secao": cod,
                    "secao_codigo": cod,
                    "secao_titulo": sec_def["titulo"],
                    "secao_titulo_curto": sec_def["titulo_curto"],
                    "assunto": p.assunto,
                    "assunto_id": p.assunto_id,
                    "assunto_nome": p.assunto.nome if p.assunto_id else "Geral",
                    "is_objetiva": obj_flag,
                    "is_dissertativa": not obj_flag,
                    "is_sensacao": cod == "sensacao_aluno",
                    "letra_gabarito": letra_gab,
                    "peso_sugerido": peso_sugerido,
                    "peso": peso_sugerido,
                }
                questoes_numeradas.append(item)
                itens_sec.append(item)
                contador_global += 1

            secoes_dict[cod] = {
                **sec_def,
                "atual": len(itens_sec),
                "meta": meta_qtd,
                "faltam": max(0, meta_qtd - len(itens_sec)),
                "completa": len(itens_sec) >= meta_qtd,
                "perguntas": itens_sec,
            }
        else:
            por_materia = []
            itens_sec_total = []
            quota_por_mat = int(quotas.get("materia_objetivas", DEFAULT_QUOTAS["materia_objetivas"]))
            meta_sec_total = quota_por_mat * len(assuntos_ordenados)

            for assunto_obj in assuntos_ordenados:
                lista_pa = agrupadas["materia_objetivas"].get(assunto_obj.id, [])
                itens_assunto = []
                for p in lista_pa:
                    obj_flag = is_pergunta_objetiva(p)
                    letra_gab = _extrair_letra_gabarito(p.get_gabarito_com_feedback()) if obj_flag else ""
                    item = {
                        "numero": contador_global,
                        "numero_fmt": f"Q{contador_global:02d}",
                        "pergunta": p,
                        "secao": cod,
                        "secao_codigo": cod,
                        "secao_titulo": f"Matéria: {assunto_obj.nome}",
                        "secao_titulo_curto": assunto_obj.nome,
                        "assunto": assunto_obj,
                        "assunto_id": assunto_obj.id,
                        "assunto_nome": assunto_obj.nome,
                        "is_objetiva": obj_flag,
                        "is_dissertativa": not obj_flag,
                        "is_sensacao": False,
                        "letra_gabarito": letra_gab,
                        "peso_sugerido": 1,
                        "peso": 1,
                    }
                    questoes_numeradas.append(item)
                    itens_assunto.append(item)
                    itens_sec_total.append(item)
                    contador_global += 1

                por_materia.append({
                    "assunto": assunto_obj,
                    "atual": len(itens_assunto),
                    "meta": quota_por_mat,
                    "faltam": max(0, quota_por_mat - len(itens_assunto)),
                    "completa": len(itens_assunto) >= quota_por_mat,
                    "perguntas": itens_assunto,
                })

            secoes_dict[cod] = {
                **sec_def,
                "atual": len(itens_sec_total),
                "meta": meta_sec_total,
                "faltam": max(0, meta_sec_total - len(itens_sec_total)),
                "completa": len(itens_sec_total) >= meta_sec_total,
                "perguntas": itens_sec_total,
                "por_materia": por_materia,
            }

    total_meta = sum(s["meta"] for s in secoes_dict.values())
    total_atual = len(questoes_numeradas)
    progresso_pct = round((min(total_atual, total_meta) / total_meta) * 100) if total_meta > 0 else 100

    return {
        "is_unificada": is_unificada_flag,
        "modulo_nome": meta.get("modulo_nome") or (prova.assunto.nome if prova.assunto_id else "Avaliação"),
        "descricao_limpa": descricao_limpa,
        "meta": meta,
        "quotas": quotas,
        "assuntos": assuntos_ordenados,
        "assuntos_modulo": assuntos_ordenados,
        "assuntos_ids": [a.id for a in assuntos_ordenados],
        "secoes": secoes_dict,
        "questoes_numeradas": questoes_numeradas,
        "total_meta": total_meta,
        "total_atual": total_atual,
        "total_faltam": max(0, total_meta - total_atual),
        "completa": total_atual >= total_meta and total_meta > 0,
        "progresso_pct": progresso_pct,
    }


def inserir_questoes_sensacao_padrao(prova, user) -> int:
    """
    Cria e vincula as questões diagnósticas sobre a Sensação do Aluno na Avaliação Unificada.
    """
    from .models import Pergunta

    tipos = garantir_tipos_pergunta_unificada()
    assunto_sens = garantir_assunto_auxiliar(user, "Sensação e Autoavaliação do Aluno")
    descricao_limpa, meta = extrair_meta_unificada(prova.descricao)
    if not meta:
        meta = {"is_unificada": True, "quotas": dict(DEFAULT_QUOTAS), "question_map": {}}

    q_map = dict(meta.get("question_map") or {})
    estrutura = construir_estrutura_unificada(prova)
    sec_sens = estrutura["secoes"].get("sensacao_aluno", {})
    faltam = sec_sens.get("faltam", 3)
    if faltam <= 0:
        return 0

    adicionadas = 0
    for q_padrao in QUESTOES_SENSACAO_PADRAO:
        if adicionadas >= faltam:
            break
        trecho = q_padrao["enunciado"][:55]
        if prova.perguntas.filter(pergunta__icontains=trecho).exists():
            continue

        nova_p = Pergunta.objects.create(
            assunto=assunto_sens,
            pergunta=q_padrao["enunciado"],
            gabarito=q_padrao["gabarito"],
            tipoDePergunta=tipos["sensacao"],
        )
        prova.perguntas.add(nova_p)
        q_map[str(nova_p.id)] = {
            "secao": "sensacao_aluno",
            "assunto_id": assunto_sens.id,
        }
        adicionadas += 1

    meta["question_map"] = q_map
    prova.descricao = empacotar_meta_unificada(descricao_limpa, meta)
    prova.save(update_fields=["descricao", "dataAtualizacao"])
    return adicionadas


def preencher_questoes_do_banco(prova) -> dict:
    """
    Busca perguntas já existentes no Banco de Questões do Mimir para os assuntos do módulo
    e preenche automaticamente as vagas restantes de cada seção da Avaliação Unificada.
    """
    from .models import Pergunta

    descricao_limpa, meta = extrair_meta_unificada(prova.descricao)
    if not meta:
        return {"total": 0}

    estrutura = construir_estrutura_unificada(prova)
    q_map = dict(meta.get("question_map") or {})
    ids_ja_na_prova = set(prova.perguntas.values_list("id", flat=True))
    adicionadas = 0

    from django.db.models import Q

    # 1. Parte III — Questões Objetivas por Matéria (Assunto) do Módulo
    sec_mat = estrutura["secoes"].get("materia_objetivas", {})
    for sub in sec_mat.get("por_materia", []):
        faltam = sub["faltam"]
        if faltam <= 0:
            continue
        assunto_obj = sub["assunto"]
        candidatas = Pergunta.objects.filter(
            Q(assunto=assunto_obj) | Q(assunto__nome__iexact=assunto_obj.nome)
        ).exclude(id__in=ids_ja_na_prova)
        for cand in candidatas:
            if faltam <= 0:
                break
            if is_pergunta_objetiva(cand):
                prova.perguntas.add(cand)
                ids_ja_na_prova.add(cand.id)
                q_map[str(cand.id)] = {
                    "secao": "materia_objetivas",
                    "assunto_id": assunto_obj.id,
                }
                faltam -= 1
                adicionadas += 1

    # 2. Parte IV — Dissertativa Técnica
    sec_dt = estrutura["secoes"].get("dissertativa_tecnica", {})
    faltam_dt = sec_dt.get("faltam", 0)
    if faltam_dt > 0:
        assuntos_ids = estrutura["assuntos_ids"]
        candidatas = Pergunta.objects.filter(assunto_id__in=assuntos_ids).exclude(id__in=ids_ja_na_prova)
        for cand in candidatas:
            if faltam_dt <= 0:
                break
            if not is_pergunta_objetiva(cand) and "sensação" not in (cand.pergunta or "").lower():
                prova.perguntas.add(cand)
                ids_ja_na_prova.add(cand.id)
                q_map[str(cand.id)] = {
                    "secao": "dissertativa_tecnica",
                    "assunto_id": cand.assunto_id,
                }
                faltam_dt -= 1
                adicionadas += 1

    # 3. Parte I e II — Conhecimentos Gerais
    for cod_cg, espera_obj in [("cg_objetivas", True), ("cg_dissertativa", False)]:
        sec_cg = estrutura["secoes"].get(cod_cg, {})
        faltam_cg = sec_cg.get("faltam", 0)
        if faltam_cg > 0:
            candidatas_cg = Pergunta.objects.filter(
                assunto__nome__icontains="geral"
            ).exclude(id__in=ids_ja_na_prova)
            for cand in candidatas_cg:
                if faltam_cg <= 0:
                    break
                if is_pergunta_objetiva(cand) == espera_obj:
                    prova.perguntas.add(cand)
                    ids_ja_na_prova.add(cand.id)
                    q_map[str(cand.id)] = {
                        "secao": cod_cg,
                        "assunto_id": cand.assunto_id,
                    }
                    faltam_cg -= 1
                    adicionadas += 1

    if adicionadas > 0:
        meta["question_map"] = q_map
        prova.descricao = empacotar_meta_unificada(descricao_limpa, meta)
        prova.save(update_fields=["descricao", "dataAtualizacao"])

    return {"total": adicionadas}


def gerar_questoes_faltantes_unificada(prova, user, secao_alvo: str = "todas") -> dict:
    """
    Gera automaticamente as questões faltantes da Avaliação Unificada (usando o LLM configurado
    no Mimir ou templates pedagógicos estruturados caso o LLM esteja indisponível/offline).
    """
    from .models import Pergunta
    from commons.services import chamarApiLLM, extrair_json_da_resposta

    tipos = garantir_tipos_pergunta_unificada()
    descricao_limpa, meta = extrair_meta_unificada(prova.descricao)
    if not meta:
        return {"criadas": 0}

    estrutura = construir_estrutura_unificada(prova)
    q_map = dict(meta.get("question_map") or {})
    modulo_nome = estrutura["modulo_nome"]
    nomes_materias = ", ".join(a.nome for a in estrutura["assuntos"]) or prova.assunto.nome
    geradas_total = 0

    def _criar_pergunta_ia_ou_fallback(assunto_obj, secao_cod, tipo_esperado, contexto_prompt, idx_item):
        nonlocal geradas_total
        is_obj = tipo_esperado == "objetiva"
        t_model = tipos["objetiva"] if is_obj else tipos["dissertativa"]

        enunciado_final = None
        gabarito_final = None

        try:
            formato_instrucao = (
                'Retorne APENAS um JSON válido com as chaves: "enunciado" (texto da questão contextualizada), '
                '"alternativas" (array com 5 strings iniciadas por "A) ", "B) ", "C) ", "D) ", "E) ") e '
                '"resposta" (apenas a letra correta, ex: "A").'
                if is_obj
                else 'Retorne APENAS um JSON válido com as chaves: "enunciado" (texto da questão dissertativa) e '
                     '"resposta" (padrão de resposta esperado / critérios de correção).'
            )
            prompt = (
                f"Você é um professor universitário elaborando uma Avaliação Unificada para o '{modulo_nome}'.\n"
                f"Matérias do módulo: {nomes_materias}.\n"
                f"Tarefa: Crie 1 questão {'OBJETIVA de Múltipla Escolha (A a E)' if is_obj else 'DISSERTATIVA'} "
                f"para a seção: {contexto_prompt}.\n"
                f"{formato_instrucao}\nNão inclua texto fora do JSON."
            )
            resp_str = chamarApiLLM(prompt, user=user, endpoint="gerar_questoes_faltantes_unificada")
            dados = extrair_json_da_resposta(resp_str)
            if isinstance(dados, dict) and dados.get("enunciado"):
                enunc = dados["enunciado"].strip()
                alts = dados.get("alternativas") or []
                if is_obj and isinstance(alts, list) and len(alts) >= 2:
                    enunciado_final = enunc + "\n\n" + "\n".join(str(a).strip() for a in alts)
                else:
                    enunciado_final = enunc
                gabarito_final = str(dados.get("resposta", "A" if is_obj else "Padrão de resposta esperado.")).strip()
        except Exception:
            enunciado_final = None

        if not enunciado_final:
            if secao_cod == "cg_objetivas":
                bancos_cg = [
                    (
                        f"[Conhecimentos Gerais — {modulo_nome}] A transformação digital e os desafios socioambientais "
                        "contemporâneos exigem que profissionais de todas as áreas articulem ética, sustentabilidade e "
                        "tomada de decisão baseada em evidências. Nesse cenário, assinale a alternativa CORRETA sobre "
                        "o papel da inovação responsável nas organizações:\n\n"
                        "A) A adoção tecnológica deve desconsiderar impactos sociais caso aumente a produtividade imediata.\n"
                        "B) A governança ética e a sustentabilidade orientam soluções técnicas resilientes e socialmente justas.\n"
                        "C) O pensamento crítico aplica-se apenas às ciências humanas, sendo dispensável em áreas tecnológicas.\n"
                        "D) A automação elimina a necessidade de comunicação interpessoal em equipes multidisciplinares.\n"
                        "E) Indicadores socioambientais são incompatíveis com metas de eficiência operacional.",
                        "B",
                    ),
                    (
                        f"[Conhecimentos Gerais — {modulo_nome}] Na análise de informações e resolução de problemas complexos "
                        "no ambiente acadêmico e profissional, a leitura crítica de dados e gráficos é indispensável para evitar "
                        "vieses de confirmação. Assinale a alternativa CORRETA:\n\n"
                        "A) Correlação estatística entre duas variáveis comprova automaticamente relação direta de causa e efeito.\n"
                        "B) Fontes primárias e revisadas por pares devem ser preteridas em favor de opiniões não verificadas.\n"
                        "C) A triangulação de fontes e a verificação metodológica fortalecem a confiabilidade das decisões.\n"
                        "D) Dados quantitativos dispensam contextualização qualitativa do cenário analisado.\n"
                        "E) Amostras não representativas garantem generalização universal sem margem de erro.",
                        "C",
                    ),
                    (
                        f"[Conhecimentos Gerais — {modulo_nome}] O trabalho colaborativo em projetos interdisciplinares "
                        "demanda competências socioemocionais, comunicação assertiva e gestão do tempo. Sobre a atuação "
                        "profissional em equipes multidisciplinares, é CORRETO afirmar que:\n\n"
                        "A) A integração de diferentes áreas do saber amplia a capacidade de diagnóstico e inovação.\n"
                        "B) Conflitos de ideias devem ser suprimidos sem debate técnico.\n"
                        "C) O compartilhamento de documentação técnica reduz a eficiência da equipe.\n"
                        "D) A responsabilidade pelos resultados restringe-se exclusivamente ao líder formal.\n"
                        "E) Metodologias ágeis impedem o acompanhamento de metas de qualidade.",
                        "A",
                    ),
                ]
                par = bancos_cg[(idx_item - 1) % len(bancos_cg)]
                enunciado_final, gabarito_final = par[0], par[1]
            elif secao_cod == "cg_dissertativa":
                enunciado_final = (
                    f"[Questão Dissertativa de Conhecimento Geral — {modulo_nome}] Discuta como a integração entre "
                    "ética profissional, pensamento crítico e responsabilidade socioambiental impacta a atuação na sua "
                    "área de formação. Apresente ao menos um exemplo prático relacionando os desafios contemporâneos "
                    "da sociedade com as competências desenvolvidas neste módulo."
                )
                gabarito_final = (
                    "Padrão de Resposta Esperado: O estudante deve articular (1) a importância da ética e responsabilidade "
                    "social na tomada de decisão; (2) a aplicação do pensamento crítico frente a problemas reais; e "
                    "(3) um exemplo concreto conectando sua área de formação aos impactos na sociedade."
                )
            elif secao_cod == "materia_objetivas":
                letras_gab = ["A", "B", "C", "D", "E"]
                letra_correta = letras_gab[(idx_item + assunto_obj.id) % 4]
                alternativas_txt = []
                for l in letras_gab:
                    if l == letra_correta:
                        alternativas_txt.append(
                            f"{l}) Aplica corretamente os fundamentos teóricos e práticos de {assunto_obj.nome}, "
                            "garantindo consistência técnica, validação metodológica e alinhamento aos objetivos do módulo."
                        )
                    else:
                        alternativas_txt.append(
                            f"{l}) Desconsidera as premissas essenciais de {assunto_obj.nome}, comprometendo a análise "
                            "sistêmica e a eficácia da solução proposta."
                        )
                enunciado_final = (
                    f"[{assunto_obj.nome} — Questão Objetiva {idx_item}] Considerando os conceitos estruturantes "
                    f"estudados na disciplina de {assunto_obj.nome} ao longo do {modulo_nome}, avalie as proposições "
                    "a seguir quanto à aplicação prática dos seus fundamentos e assinale a alternativa CORRETA:\n\n"
                    + "\n".join(alternativas_txt)
                )
                gabarito_final = letra_correta
            elif secao_cod == "dissertativa_tecnica":
                enunciado_final = (
                    f"[Questão Dissertativa Técnica Interdisciplinar — {modulo_nome}] Considere um cenário prático "
                    f"que exige a integração dos conhecimentos de {nomes_materias}. Elabore uma proposta técnica "
                    "estruturada contendo: (a) diagnóstico dos requisitos e variáveis críticas do problema; "
                    "(b) fundamentação técnica baseada nas disciplinas do módulo; e (c) plano de validação dos resultados."
                )
                gabarito_final = (
                    f"Padrão de Resposta Técnico ({nomes_materias}): (1) Identificação precisa dos requisitos técnicos (3,0 pts); "
                    "(2) Aplicação correta dos conceitos das matérias do módulo (4,0 pts); "
                    "(3) Proposta de solução viável e métricas de verificação (3,0 pts)."
                )

        if enunciado_final:
            nova_p = Pergunta.objects.create(
                assunto=assunto_obj,
                pergunta=enunciado_final,
                gabarito=gabarito_final or "A",
                tipoDePergunta=t_model,
            )
            prova.perguntas.add(nova_p)
            q_map[str(nova_p.id)] = {
                "secao": secao_cod,
                "assunto_id": assunto_obj.id,
            }
            geradas_total += 1

    assunto_cg = garantir_assunto_auxiliar(user, "Conhecimentos Gerais")

    for cod in ORDEM_SECOES:
        if secao_alvo != "todas" and secao_alvo != cod:
            continue
        sec = estrutura["secoes"].get(cod, {})

        if cod == "sensacao_aluno":
            if sec.get("faltam", 0) > 0:
                geradas_total += inserir_questoes_sensacao_padrao(prova, user)
                _, meta = extrair_meta_unificada(prova.descricao)
                q_map = dict(meta.get("question_map") or {})
            continue

        if cod == "materia_objetivas":
            for sub in sec.get("por_materia", []):
                for i in range(sub.get("faltam", 0)):
                    _criar_pergunta_ia_ou_fallback(
                        assunto_obj=sub["assunto"],
                        secao_cod="materia_objetivas",
                        tipo_esperado="objetiva",
                        contexto_prompt=f"Matéria específica '{sub['assunto'].nome}' do módulo",
                        idx_item=sub["atual"] + i + 1,
                    )
        elif cod == "cg_objetivas":
            for i in range(sec.get("faltam", 0)):
                _criar_pergunta_ia_ou_fallback(
                    assunto_obj=assunto_cg,
                    secao_cod="cg_objetivas",
                    tipo_esperado="objetiva",
                    contexto_prompt="Conhecimentos Gerais (Objetiva)",
                    idx_item=sec["atual"] + i + 1,
                )
        elif cod == "cg_dissertativa":
            for i in range(sec.get("faltam", 0)):
                _criar_pergunta_ia_ou_fallback(
                    assunto_obj=assunto_cg,
                    secao_cod="cg_dissertativa",
                    tipo_esperado="dissertativa",
                    contexto_prompt="Conhecimentos Gerais (Dissertativa)",
                    idx_item=sec["atual"] + i + 1,
                )
        elif cod == "dissertativa_tecnica":
            for i in range(sec.get("faltam", 0)):
                _criar_pergunta_ia_ou_fallback(
                    assunto_obj=prova.assunto,
                    secao_cod="dissertativa_tecnica",
                    tipo_esperado="dissertativa",
                    contexto_prompt=f"Questão Dissertativa Técnica integrando {nomes_materias}",
                    idx_item=sec["atual"] + i + 1,
                )

    meta["question_map"] = q_map
    prova.descricao = empacotar_meta_unificada(descricao_limpa, meta)
    prova.save(update_fields=["descricao", "dataAtualizacao"])
    return {"criadas": geradas_total}


def obter_ip_rede_local() -> str:
    """
    Detecta o endereço IP da máquina na rede local (LAN/Wi-Fi) para que o QR Code
    do Scanner Mobile possa ser aberto pelo celular quando o professor acessa via localhost.
    """
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip_cand = info[4][0]
            if ip_cand and not ip_cand.startswith("127."):
                return ip_cand
    except Exception:
        pass
    return "127.0.0.1"


def gerar_token_scanner_mobile(prova_id: int, user_id: int, sessao_id: str) -> str:
    """
    Gera um token criptograficamente assinado para permitir que o professor abra a câmera
    direto no celular via QR Code sem precisar digitar login/senha novamente.
    """
    from django.core import signing
    payload = {
        "p": int(prova_id),
        "u": int(user_id),
        "s": str(sessao_id),
    }
    return signing.dumps(payload, salt="mimir.scanner.mobile.v1")


def validar_token_scanner_mobile(token: str, max_age: int = 86400) -> dict | None:
    """
    Valida o token assinado do Scanner Mobile (válido por 24h por padrão).
    """
    from django.core import signing
    try:
        data = signing.loads(token, salt="mimir.scanner.mobile.v1", max_age=max_age)
        if isinstance(data, dict) and "p" in data and "u" in data and "s" in data:
            return data
    except Exception:
        return None
    return None


def gerar_qrcode_base64(texto_url: str) -> str:
    """
    Gera um QR Code em PNG Base64 100% local (sem depender de internet externa).
    """
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=7,
            border=2,
        )
        qr.add_data(texto_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def _caminho_sessao_scanner(sessao_id: str) -> str:
    import os
    safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "", str(sessao_id or "default"))[:64] or "default"
    pasta = "/tmp/mimir_scanner_sessions"
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, f"sessao_{safe_id}.json")


def salvar_estado_sessao_scanner(sessao_id: str, payload: dict) -> None:
    """
    Salva o resultado mais recente enviado pelo Scanner Mobile para que a tela do
    computador sincronize automaticamente em tempo real.
    """
    caminho = _caminho_sessao_scanner(sessao_id)
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao salvar sessão do scanner mobile: {e}")


def ler_estado_sessao_scanner(sessao_id: str) -> dict | None:
    """
    Lê o estado sincronizado da sessão do Scanner Mobile.
    """
    import os
    caminho = _caminho_sessao_scanner(sessao_id)
    if not os.path.exists(caminho):
        return None
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def analisar_foto_prova_unificada_ia(prova, arquivos_imagens: list, user=None) -> dict:
    """
    Realiza a leitura óptica e correção inteligente de 1 ou múltiplas páginas fotografadas
    da Folha de Respostas (Gabarito OMR) e/ou Caderno de Prova:
      - Corrige rotação EXIF de fotos tiradas pelo celular.
      - Consolida respostas distribuídas em múltiplas páginas (Página 1, Página 2, Página 3...).
      - Detecta as marcações nas questões objetivas (A, B, C, D, E) e cruza com o gabarito.
      - Transcreve (OCR manuscrito) as questões dissertativas e avalia nota (0-10) + feedback.
      - Marca `detectado=False` nas questões que não aparecem nas páginas enviadas (permitindo
        leitura página a página incremental sem sobrescrever páginas anteriores).
    """
    from PIL import ImageOps
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI
    from .models import LLMLog

    estrutura = construir_estrutura_unificada(prova)
    questoes = estrutura["questoes_numeradas"]
    total_paginas_enviadas = len(arquivos_imagens)

    especificacao_questoes = []
    for q in questoes:
        p = q["pergunta"]
        especificacao_questoes.append({
            "numero": q["numero"],
            "codigo": q["numero_fmt"],
            "pergunta_id": p.id,
            "secao": q["secao"],
            "assunto": q["assunto_nome"],
            "tipo": "dissertativa" if q["is_dissertativa"] else "objetiva",
            "is_sensacao": q["is_sensacao"],
            "letra_gabarito": q["letra_gabarito"],
            "gabarito_oficial": (p.get_gabarito_com_feedback() or "").strip()[:300],
        })

    prompt_sistema = f"""Você é um sistema especialista de Leitura Óptica (OMR) e Correção Acadêmica Multimodal de Provas e Gabaritos de Múltiplas Páginas.
Você está recebendo {total_paginas_enviadas} foto(s)/página(s) referente(s) à avaliação: "{prova.titulo}" ({estrutura['modulo_nome']}).

IMPORTANTE SOBRE GABARITOS DE MÚLTIPLAS PÁGINAS:
- O gabarito (Folha de Respostas OMR) ou a prova pode estar dividido em 2 ou mais páginas (por exemplo: Página 1 com o cabeçalho e questões objetivas, e Página 2 com as questões dissertativas, continuação das objetivas ou sensação do aluno).
- Além disso, o professor pode estar fotografando todas as páginas de uma vez OU apenas uma página específica agora para mesclar com as demais.

MAPA COMPLETO DE QUESTÕES DA PROVA:
{json.dumps(especificacao_questoes, ensure_ascii=False, indent=2)}

SUA TAREFA:
1. Identifique o nome do aluno escrito no cabeçalho de qualquer uma das páginas (se visível).
2. Analise TODAS as {total_paginas_enviadas} foto(s)/página(s) anexadas em conjunto.
3. Para cada questão do mapa acima (pelo campo "pergunta_id" e "numero"):
   - Verifique se a questão (sua linha de bolhas OMR ou sua caixa de resposta dissertativa) aparece em alguma das fotos enviadas e foi respondida.
   - Se a questão NÃO estiver visível em nenhuma das fotos enviadas (ex.: está em outra página ainda não fotografada) ou estiver totalmente em branco, defina `"detectado_na_foto": false` e `"resposta_lida": ""`. NUNCA invente ou chute uma letra ou texto para questões que não estão visíveis na foto!
   - Se a questão estiver visível e respondida (`"detectado_na_foto": true`):
     * Informe `"pagina_foto": N` (número da foto de 1 a {total_paginas_enviadas} onde a resposta foi lida).
     * Se for `"objetiva"`: identifique qual letra (`"A"`, `"B"`, `"C"`, `"D"` ou `"E"`) teve a bolha preenchida/marcada pelo aluno.
     * Se for `"dissertativa"`: transcreva fielmente o texto manuscrito pelo aluno em `"resposta_lida"`, avalie com base no `"gabarito_oficial"` atribuindo `"nota_sugerida"` de 0.0 a 10.0 e escreva um `"feedback"` pedagógico construtivo.
4. Caso as questões de Sensação do Aluno estejam visíveis, gere um `"resumo_sensacao"` sintetizando a percepção do aluno.

RETORNE EXCLUSIVAMENTE UM JSON VÁLIDO NO SEGUINTE FORMATO:
{{
  "aluno_identificado": "Nome do aluno lido na folha ou vazio",
  "paginas_identificadas": ["Página 1", "Página 2"],
  "resumo_sensacao": "Síntese da sensação/percepção do aluno (ou vazio se não aplicável)",
  "itens": [
    {{
      "numero": 1,
      "pergunta_id": 123,
      "detectado_na_foto": true,
      "pagina_foto": 1,
      "resposta_lida": "Letra A-E marcada ou transcrição do texto manuscrito",
      "nota_sugerida": 10.0,
      "feedback": "Justificativa ou comentário de correção"
    }}
  ]
}}"""

    conteudos = [HumanMessage(content=prompt_sistema)]
    paginas_preview_b64 = []

    for idx, arq in enumerate(arquivos_imagens):
        try:
            arq.seek(0)
            img = Image.open(arq)
            # Corrige orientação EXIF de fotos tiradas em pé/deitadas no celular
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Miniatura leve para exibição sincronizada PC <-> Celular
            thumb = img.copy()
            thumb.thumbnail((520, 720))
            buf_thumb = io.BytesIO()
            thumb.save(buf_thumb, format="JPEG", quality=75)
            paginas_preview_b64.append(
                f"data:image/jpeg;base64,{base64.b64encode(buf_thumb.getvalue()).decode('utf-8')}"
            )

            # Imagem de alta nitidez para leitura OMR + OCR manuscrito
            img.thumbnail((2200, 2200))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            conteudos.append(
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": f"FOTO / PÁGINA {idx + 1} DE {total_paginas_enviadas} DO GABARITO / PROVA:",
                        },
                        {"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"},
                    ]
                )
            )
        except Exception as e:
            print(f"Erro ao preparar imagem da página {idx + 1}: {e}")

    parsed_ia = None
    modo_utilizado = "Leitura Assistida Local"
    from .models import ConfiguracaoModeloLLM
    cfg_ativo = ConfiguracaoModeloLLM.get_modelo_ativo()
    api_key = (
        (cfg_ativo.api_key_override or "").strip() if cfg_ativo else ""
    ) or getattr(settings, "GEMINI_API_KEY", None)

    candidatos_modelos = []
    if cfg_ativo and cfg_ativo.model_id:
        candidatos_modelos.append((cfg_ativo.provedor, cfg_ativo.model_id.strip(), cfg_ativo.base_url))
    for fallback_m in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if not any(m[1] == fallback_m for m in candidatos_modelos):
            candidatos_modelos.append(("gemini", fallback_m, None))

    for provedor_cand, model_candidate, base_url_cand in candidatos_modelos:
        if provedor_cand == "gemini" and not api_key:
            continue
        try:
            if provedor_cand == "ollama":
                from langchain_ollama import ChatOllama
                ollama_kwargs = {"model": model_candidate, "temperature": 0.1}
                if base_url_cand and base_url_cand.strip():
                    ollama_kwargs["base_url"] = base_url_cand.strip()
                llm = ChatOllama(**ollama_kwargs)
            else:
                llm = ChatGoogleGenerativeAI(
                    model=model_candidate,
                    google_api_key=api_key,
                    temperature=0.1,
                )
            resp = llm.invoke(conteudos)
            raw_text = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(raw_text, list):
                raw_text = "\n".join(
                    b.get("text", "") if isinstance(b, dict) else str(b) for b in raw_text
                )
            LLMLog.objects.create(
                user=user,
                prompt=f"Correção por Foto #{prova.id} ({total_paginas_enviadas} página(s))",
                response=raw_text[:5000],
                model_used=model_candidate,
                status="success",
                endpoint="analisar_foto_prova_unificada_ia",
            )
            m = re.search(r"\{[\s\S]*\}", raw_text)
            if m:
                cand = json.loads(m.group(0))
                if isinstance(cand, dict) and "itens" in cand:
                    parsed_ia = cand
                    modo_utilizado = f"Visão Computacional IA ({model_candidate})"
                    break
        except Exception as e:
            LLMLog.objects.create(
                user=user,
                prompt=f"Erro Correção por Foto #{prova.id}",
                error_message=str(e),
                model_used=model_candidate,
                status="error",
                endpoint="analisar_foto_prova_unificada_ia",
            )
            continue

    mapa_ia_por_pid = {}
    mapa_ia_por_num = {}
    if parsed_ia:
        itens_raw = parsed_ia.get("itens")
        if isinstance(itens_raw, list):
            for it in itens_raw:
                if isinstance(it, dict):
                    if it.get("pergunta_id") is not None:
                        mapa_ia_por_pid[str(it["pergunta_id"])] = it
                    if it.get("numero") is not None:
                        try:
                            mapa_ia_por_num[int(it["numero"])] = it
                        except (ValueError, TypeError):
                            pass
        elif isinstance(itens_raw, dict):
            for k, it in itens_raw.items():
                if isinstance(it, dict):
                    mapa_ia_por_pid[str(k)] = it
                    if it.get("numero") is not None:
                        try:
                            mapa_ia_por_num[int(it["numero"])] = it
                        except (ValueError, TypeError):
                            pass

    itens_finais = []
    soma_ponderada = 0.0
    soma_pesos = 0
    qtd_detectadas = 0

    for q in questoes:
        p = q["pergunta"]
        info_ia = mapa_ia_por_pid.get(str(p.id)) or mapa_ia_por_num.get(q["numero"]) or {}
        letra_gab = q["letra_gabarito"] or "A"

        if parsed_ia is not None:
            resp_bruta = str(info_ia.get("resposta_lida") or info_ia.get("resposta_detectada") or "").strip()
            flag_detectado = info_ia.get("detectado_na_foto")
            if flag_detectado is False or not resp_bruta:
                # Questão não estava visível nesta(s) página(s) ou foi deixada em branco:
                # Não sobrescreve o que já foi lido de outras páginas!
                itens_finais.append({
                    "numero": q["numero"],
                    "pergunta_id": p.id,
                    "secao": q["secao"],
                    "detectado": False,
                    "pagina_foto": info_ia.get("pagina_foto"),
                    "resposta_lida": "",
                    "correta": None,
                    "nota_sugerida": None,
                    "feedback": "",
                })
                continue

        qtd_detectadas += 1
        pagina_foto = info_ia.get("pagina_foto") or 1

        if q["is_sensacao"]:
            resp_lida = str(info_ia.get("resposta_lida") or info_ia.get("resposta_detectada") or "B").strip()
            nota_sug = 10.0
            correta = True
            feedback = info_ia.get("feedback") or f"Percepção do aluno registrada ({resp_lida} • Pág. {pagina_foto}) — peso 0 na nota."
        elif q["is_objetiva"]:
            resp_raw = str(info_ia.get("resposta_lida") or info_ia.get("resposta_detectada") or letra_gab).strip()
            m_letra = re.search(r"\b([A-Ea-e])\b", resp_raw)
            letra_lida = m_letra.group(1).upper() if m_letra else (resp_raw[0].upper() if resp_raw and resp_raw[0].upper() in "ABCDE" else letra_gab)
            resp_lida = letra_lida
            correta = (letra_lida == letra_gab) if letra_gab else True
            nota_sug = 10.0 if correta else 0.0
            feedback = (
                f"Alternativa correta ({letra_lida}) [Lida na Pág. {pagina_foto}]."
                if correta
                else f"Marcou {letra_lida}; gabarito oficial é {letra_gab} [Lida na Pág. {pagina_foto}]."
            )
            soma_ponderada += nota_sug * q["peso_sugerido"]
            soma_pesos += q["peso_sugerido"]
        else:
            resp_lida = str(
                info_ia.get("resposta_lida")
                or info_ia.get("resposta_detectada")
                or "[Resposta manuscrita identificada na folha — revise e confirme a pontuação]"
            ).strip()
            try:
                nota_sug = float(info_ia.get("nota_sugerida", info_ia.get("nota", 8.5)))
            except (ValueError, TypeError):
                nota_sug = 8.5
            nota_sug = max(0.0, min(10.0, nota_sug))
            correta = None
            feedback = (info_ia.get("feedback") or "Avaliação da questão dissertativa baseada nos critérios do gabarito.") + f" [Pág. {pagina_foto}]"
            soma_ponderada += nota_sug * q["peso_sugerido"]
            soma_pesos += q["peso_sugerido"]

        itens_finais.append({
            "numero": q["numero"],
            "pergunta_id": p.id,
            "secao": q["secao"],
            "detectado": True,
            "pagina_foto": pagina_foto,
            "resposta_lida": resp_lida,
            "correta": correta,
            "nota_sugerida": round(nota_sug, 1),
            "feedback": feedback,
        })

    nota_academica_sugerida = round(soma_ponderada / soma_pesos, 2) if soma_pesos > 0 else 0.0

    return {
        "success": True,
        "modo": modo_utilizado,
        "total_paginas_processadas": total_paginas_enviadas,
        "questoes_detectadas": qtd_detectadas,
        "total_questoes_prova": len(questoes),
        "paginas_preview": paginas_preview_b64,
        "aluno_identificado": (parsed_ia or {}).get("aluno_identificado") or (parsed_ia or {}).get("aluno_detectado") or "",
        "resumo_sensacao": (parsed_ia or {}).get("resumo_sensacao") or "",
        "nota_academica_sugerida": nota_academica_sugerida,
        "itens": itens_finais,
    }


def calcular_diagnostico_prova_aluno_unificada(prova_aluno) -> dict:
    """
    Calcula o boletim diagnóstico detalhado de um aluno em uma Avaliação Unificada:
      - Nota acadêmica ponderada (0 a 10), excluindo questões de Sensação do Aluno (peso 0)
      - Desempenho por Seção e por Matéria (Assunto) do Módulo
      - Resumo das respostas de Sensação do Aluno
    """
    from .models import RespostaAluno

    prova = prova_aluno.aplicacao_prova.prova
    estrutura = construir_estrutura_unificada(prova)
    respostas_qs = RespostaAluno.objects.filter(prova_aluno=prova_aluno)
    respostas_map = {r.pergunta_id: r for r in respostas_qs}

    por_secao = {}
    por_materia = {}
    sensacao_respostas = []

    soma_notas_ponderadas = 0.0
    soma_pesos = 0
    acertos_objetivas = 0
    total_objetivas_academicas = 0

    for q in estrutura["questoes_numeradas"]:
        p = q["pergunta"]
        resp = respostas_map.get(p.id)
        nota_val = float(resp.nota) if (resp and resp.nota is not None) else 0.0
        resp_txt = (resp.resposta_texto or "").strip() if resp else ""

        if q["secao"] == "sensacao_aluno":
            sensacao_respostas.append({
                "numero": q["numero"],
                "numero_fmt": q["numero_fmt"],
                "resposta": resp_txt or "--",
                "comentario": (resp.feedback_professor or "") if resp else "",
            })
            continue

        peso = int(resp.peso) if (resp and resp.peso is not None and resp.peso > 0) else max(1, int(q["peso_sugerido"] or 1))
        soma_notas_ponderadas += nota_val * peso
        soma_pesos += peso

        if q["is_objetiva"]:
            total_objetivas_academicas += 1
            if nota_val >= 6.0:
                acertos_objetivas += 1

        sec_cod = q["secao"]
        if sec_cod not in por_secao:
            por_secao[sec_cod] = {
                "titulo": q["secao_titulo_curto"],
                "soma_notas": 0.0,
                "qtd": 0,
            }
        por_secao[sec_cod]["soma_notas"] += nota_val
        por_secao[sec_cod]["qtd"] += 1

        if sec_cod == "materia_objetivas":
            mat_nome = q["assunto_nome"]
            if mat_nome not in por_materia:
                por_materia[mat_nome] = {
                    "soma_notas": 0.0,
                    "qtd": 0,
                    "acertos": 0,
                }
            por_materia[mat_nome]["soma_notas"] += nota_val
            por_materia[mat_nome]["qtd"] += 1
            if nota_val >= 6.0:
                por_materia[mat_nome]["acertos"] += 1

    for sec_info in por_secao.values():
        sec_info["media"] = round(sec_info["soma_notas"] / sec_info["qtd"], 1) if sec_info["qtd"] > 0 else 0.0
        sec_info["percentual"] = round((sec_info["media"] / 10.0) * 100)

    for m_info in por_materia.values():
        m_info["media"] = round(m_info["soma_notas"] / m_info["qtd"], 1) if m_info["qtd"] > 0 else 0.0
        m_info["percentual"] = round((m_info["media"] / 10.0) * 100)

    nota_academica_final = round(soma_notas_ponderadas / soma_pesos, 2) if soma_pesos > 0 else 0.0

    return {
        "nota_academica_final": nota_academica_final,
        "acertos_objetivas": acertos_objetivas,
        "total_objetivas_academicas": total_objetivas_academicas,
        "por_secao": por_secao,
        "por_materia": por_materia,
        "sensacao_respostas": sensacao_respostas,
    }


# ==============================================================================
# FECHAMENTO PSICOMÉTRICO E NOTA FINAL DA AVALIAÇÃO UNIFICADA (MODELO ENADE)
# ==============================================================================

PONTO_CORTE_RPB_ENADE = 0.19


def _avaliar_acerto_questao_objetiva(item_questao: dict, resp_obj) -> Tuple[bool, str]:
    """
    Determina se o aluno acertou uma questão objetiva e qual alternativa marcou.
    Considera tanto a letra registrada em `resposta_texto` comparada com `letra_gabarito`
    quanto a nota atribuída na questão (`nota >= 6.0`).
    """
    letra_gab = (item_questao.get("letra_gabarito") or "").strip().upper()
    resp_txt = ((resp_obj.resposta_texto or "") if resp_obj else "").strip()
    letra_aluno = ""
    if resp_txt:
        m = re.match(r"^\s*\(?([A-Ha-h])\b", resp_txt)
        if m:
            letra_aluno = m.group(1).upper()
        elif len(resp_txt) == 1 and resp_txt.upper() in "ABCDEFGH":
            letra_aluno = resp_txt.upper()

    nota_val = None
    if resp_obj and getattr(resp_obj, "nota", None) is not None:
        try:
            nota_val = float(resp_obj.nota)
        except (ValueError, TypeError):
            nota_val = None

    if letra_aluno and letra_gab:
        if nota_val is not None:
            acertou = (nota_val >= 6.0) or (letra_aluno == letra_gab and nota_val > 0.0)
        else:
            acertou = (letra_aluno == letra_gab)
    elif nota_val is not None:
        acertou = (nota_val >= 6.0)
    else:
        acertou = False

    exibicao_resp = letra_aluno or (resp_txt[:15] if resp_txt else "--")
    return acertou, exibicao_resp


def _calcular_bloco_psicometrico_ponto_bisserial(
    codigo_bloco: str,
    titulo_bloco: str,
    questoes_bloco: List[dict],
    provas_alunos: List[Any],
    respostas_por_pa: Dict[int, Dict[int, Any]],
    overrides_validade: Optional[Dict[str, str]] = None,
) -> dict:
    """
    Executa a Análise Psicométrica das Objetivas (Correlação Ponto-Bisserial r_pb)
    separadamente para um componente (FG ou CE):
      1. Calcula o escore bruto preliminar (X) de cada aluno presente no componente
         (soma de acertos nas questões não anuladas preliminarmente daquele bloco).
      2. Para cada questão i, extrai:
         - X1_barra: média dos escores brutos apenas dos alunos que acertaram a questão i.
         - X_barra: média dos escores brutos de todos os alunos presentes.
         - S_X: desvio-padrão populacional dos escores brutos de todos os alunos presentes.
         - p: proporção de acerto da questão (total de acertos / total de presentes).
         - q = 1 - p: proporção de erro.
      3. Calcula o índice de discriminação:
         r_pb = ((X1_barra - X_barra) / S_X) * sqrt(p / q)
      4. Aplica o ponto de corte:
         - Se r_pb > 0.19: mantém a questão como válida.
         - Se r_pb <= 0.19 (ou se p = 0 / p = 1 / S_X = 0, onde não há variância):
           desconsidera a questão por baixo poder de discriminação.
    """
    import math

    overrides = overrides_validade or {}
    n_presentes = len(provas_alunos)

    # Identifica questões anuladas preliminarmente no gabarito (se o professor marcou 'anulada_gabarito')
    pids_anuladas_preliminar = {
        q["pergunta"].id
        for q in questoes_bloco
        if overrides.get(str(q["pergunta"].id)) == "anulada_gabarito"
    }

    # Matriz de acertos [pa_id][pergunta_id] -> {'acertou': bool, 'resposta': str}
    matriz_acertos: Dict[int, Dict[int, dict]] = {}
    escores_brutos: Dict[int, int] = {}

    for pa in provas_alunos:
        mapa_resp = respostas_por_pa.get(pa.id, {})
        matriz_acertos[pa.id] = {}
        soma_acertos_prelim = 0
        for q in questoes_bloco:
            pid = q["pergunta"].id
            resp_obj = mapa_resp.get(pid)
            acertou, resp_exib = _avaliar_acerto_questao_objetiva(q, resp_obj)
            matriz_acertos[pa.id][pid] = {
                "acertou": acertou,
                "resposta": resp_exib,
            }
            if pid not in pids_anuladas_preliminar and acertou:
                soma_acertos_prelim += 1
        escores_brutos[pa.id] = soma_acertos_prelim

    # Estatísticas populacionais dos escores brutos preliminares (X_barra e S_X)
    if n_presentes > 0:
        lista_x = [float(escores_brutos[pa.id]) for pa in provas_alunos]
        x_barra = sum(lista_x) / float(n_presentes)
        variancia_pop = sum((x - x_barra) ** 2 for x in lista_x) / float(n_presentes)
        s_x = math.sqrt(variancia_pop)
    else:
        x_barra = 0.0
        s_x = 0.0

    questoes_analisadas = []
    total_validas = 0
    total_desconsideradas = 0

    for q in questoes_bloco:
        p_obj = q["pergunta"]
        pid = p_obj.id
        modo_override = overrides.get(str(pid), "auto")

        escores_acertadores = [
            float(escores_brutos[pa.id])
            for pa in provas_alunos
            if matriz_acertos[pa.id][pid]["acertou"]
        ]
        n_acertos = len(escores_acertadores)
        n_erros = max(0, n_presentes - n_acertos)

        p_prop = (float(n_acertos) / float(n_presentes)) if n_presentes > 0 else 0.0
        q_prop = 1.0 - p_prop
        x1_barra = (sum(escores_acertadores) / float(n_acertos)) if n_acertos > 0 else 0.0

        sem_variancia = False
        r_pb = None
        valida_auto = False

        if pid in pids_anuladas_preliminar:
            sem_variancia = True
            valida_auto = False
            motivo_auto = "Anulada preliminarmente no gabarito (excluída do escore bruto)"
        elif n_presentes == 0:
            sem_variancia = True
            valida_auto = False
            motivo_auto = "Nenhuma prova corrigida até o momento"
        elif p_prop <= 1e-9:
            sem_variancia = True
            valida_auto = False
            motivo_auto = "Desconsiderada: p = 0,0000 (nenhum aluno acertou — sem variância)"
        elif p_prop >= 1.0 - 1e-9 or q_prop <= 1e-9:
            sem_variancia = True
            valida_auto = False
            motivo_auto = "Desconsiderada: p = 1,0000 (100% dos presentes acertaram — sem variância)"
        elif s_x <= 1e-9:
            sem_variancia = True
            valida_auto = False
            motivo_auto = "Desconsiderada: Sx = 0,0000 (todos os alunos obtiveram o mesmo escore bruto — sem variância)"
        else:
            r_pb = ((x1_barra - x_barra) / s_x) * math.sqrt(p_prop / q_prop)
            valida_auto = bool(r_pb > PONTO_CORTE_RPB_ENADE)
            if valida_auto:
                motivo_auto = f"Mantida como válida (r_pb = {r_pb:.4f} > 0,19)"
            else:
                motivo_auto = f"Desconsiderada por baixo poder de discriminação (r_pb = {r_pb:.4f} ≤ 0,19)"

        if modo_override == "manter":
            valida = True
            motivo_final = f"Mantida manualmente pelo professor • [Cálculo r_pb: {motivo_auto}]"
        elif modo_override in ("desconsiderar", "anulada_gabarito"):
            valida = False
            if modo_override == "anulada_gabarito":
                motivo_final = "Anulada preliminarmente no gabarito pelo professor"
            else:
                motivo_final = f"Desconsiderada manualmente pelo professor • [Cálculo r_pb: {motivo_auto}]"
        else:
            modo_override = "auto"
            valida = valida_auto
            motivo_final = motivo_auto

        if valida:
            total_validas += 1
        else:
            total_desconsideradas += 1

        for pa in provas_alunos:
            matriz_acertos[pa.id][pid]["valida"] = valida

        texto_limpo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p_obj.get_texto_com_feedback() or "")).strip()
        resumo_enunciado = texto_limpo[:140] + ("..." if len(texto_limpo) > 140 else "")

        questoes_analisadas.append({
            "numero": q["numero"],
            "numero_fmt": q["numero_fmt"],
            "pergunta_id": pid,
            "assunto_nome": q["assunto_nome"],
            "secao": q["secao"],
            "secao_titulo": q["secao_titulo_curto"],
            "letra_gabarito": q.get("letra_gabarito") or "--",
            "resumo_enunciado": resumo_enunciado,
            "total_presentes": n_presentes,
            "total_acertos": n_acertos,
            "total_erros": n_erros,
            "x1_barra": round(x1_barra, 4),
            "x_barra": round(x_barra, 4),
            "s_x": round(s_x, 4),
            "p": round(p_prop, 4),
            "p_pct": round(p_prop * 100.0, 1),
            "q": round(q_prop, 4),
            "q_pct": round(q_prop * 100.0, 1),
            "r_pb": round(r_pb, 4) if r_pb is not None else None,
            "sem_variancia": sem_variancia,
            "valida_auto": valida_auto,
            "valida": valida,
            "modo_override": modo_override,
            "motivo": motivo_final,
        })

    return {
        "codigo": codigo_bloco,
        "titulo": titulo_bloco,
        "ponto_corte_rpb": PONTO_CORTE_RPB_ENADE,
        "total_presentes": n_presentes,
        "total_questoes": len(questoes_bloco),
        "total_questoes_nao_anuladas_prelim": len(questoes_bloco) - len(pids_anuladas_preliminar),
        "total_validas": total_validas,
        "total_desconsideradas": total_desconsideradas,
        "x_barra": round(x_barra, 4),
        "s_x": round(s_x, 4),
        "escores_brutos": escores_brutos,
        "matriz_acertos": matriz_acertos,
        "questoes": questoes_analisadas,
    }


def calcular_fechamento_psicometrico_unificada(
    prova,
    aplicar_notas: bool = False,
    escala_nota_final: Optional[str] = None,
    overrides_validade: Optional[Dict[str, str]] = None,
    provas_alunos_override: Optional[List[Any]] = None,
    estrutura_override: Optional[dict] = None,
) -> dict:
    """
    Executa todo o processo de Correção Final da Avaliação Unificada (Modelo ENADE):
      1. Lista todas as provas corrigidas (ProvaAluno).
      2. Executa a Análise Psicométrica das Objetivas (Correlação Ponto-Bisserial r_pb > 0,19)
         separadamente para:
           - Objetivas de Formação Geral (FG: `cg_objetivas`)
           - Objetivas de Componente Específico (CE: `materia_objetivas`)
      3. Executa a Etapa 5 — Cálculo das Notas por Componente e Nota Final (Escala 0 a 1):
           - NO_FG = (Acertos válidos em FG) / V_FG
           - NT_FG = (0,65 * NO_FG) + (0,35 * ND_FG)
           - NO_CE = (Acertos válidos em CE) / V_CE
           - NT_CE = (0,90 * NO_CE) + (0,10 * ND_CE)
           - NT_Ger = (0,25 * NT_FG) + (0,75 * NT_CE)
         Com detalhamento das 4 parcelas de peso direto na composição final de 1,0000 ponto:
           - Objetivas FG: 25% * 65% = 0,1625
           - Discursiva FG: 25% * 35% = 0,0875
           - Objetivas CE: 75% * 90% = 0,6750
           - Discursiva CE: 75% * 10% = 0,0750
      4. Se `aplicar_notas=True`, consolida as notas finais em `ProvaAluno.nota_final`
         e salva o snapshot da memória de cálculo nos metadados da `Prova`.
    """
    from django.utils import timezone

    estrutura = estrutura_override or construir_estrutura_unificada(prova)
    descricao_humana, meta = extrair_meta_unificada(getattr(prova, "descricao", "") or "")
    meta = meta or {}
    fechamento_meta = meta.get("fechamento_psicometrico") if isinstance(meta.get("fechamento_psicometrico"), dict) else {}

    if overrides_validade is None:
        overrides_validade = (
            fechamento_meta.get("overrides_validade")
            if isinstance(fechamento_meta.get("overrides_validade"), dict)
            else {}
        )
    if not escala_nota_final:
        escala_nota_final = fechamento_meta.get("escala_nota_final") or "0_1"

    # Carrega provas corrigidas/concluídas dos alunos
    if provas_alunos_override is not None:
        provas_alunos = list(provas_alunos_override)
    else:
        from .models import ProvaAluno
        qs_pa = (
            ProvaAluno.objects.filter(aplicacao_prova__prova=prova)
            .select_related("aluno", "aplicacao_prova")
            .prefetch_related("respostas")
            .order_by("aluno__first_name", "aluno__last_name", "aluno__username", "-id")
        )
        provas_alunos = [
            pa for pa in qs_pa
            if pa.status in ("corrigida", "concluida") or pa.respostas.exists()
        ]

    respostas_por_pa: Dict[int, Dict[int, Any]] = {}
    for pa in provas_alunos:
        try:
            resps = list(pa.respostas.all())
        except Exception:
            resps = getattr(pa, "respostas_list", [])
        respostas_por_pa[pa.id] = {r.pergunta_id: r for r in resps}

    # Separa as questões da estrutura nos 4 blocos acadêmicos (FG Obj, FG Diss, CE Obj, CE Diss)
    questoes_fg_obj = []
    questoes_fg_diss = []
    questoes_ce_obj = []
    questoes_ce_diss = []

    for q in estrutura.get("questoes_numeradas", []):
        sec = q.get("secao")
        if sec == "sensacao_aluno":
            continue
        is_obj = bool(q.get("is_objetiva"))
        if sec == "cg_objetivas" or (sec == "cg_dissertativa" and is_obj):
            questoes_fg_obj.append(q)
        elif sec == "cg_dissertativa":
            questoes_fg_diss.append(q)
        elif sec == "materia_objetivas" or (sec == "dissertativa_tecnica" and is_obj):
            questoes_ce_obj.append(q)
        elif sec == "dissertativa_tecnica":
            questoes_ce_diss.append(q)
        else:
            if is_obj:
                questoes_ce_obj.append(q)
            else:
                questoes_ce_diss.append(q)

    # Passo 1: Análise Psicométrica das Objetivas (Correlação Ponto-Bisserial) separada para FG e CE
    bloco_fg = _calcular_bloco_psicometrico_ponto_bisserial(
        codigo_bloco="FG",
        titulo_bloco="Objetivas de Formação Geral (FG)",
        questoes_bloco=questoes_fg_obj,
        provas_alunos=provas_alunos,
        respostas_por_pa=respostas_por_pa,
        overrides_validade=overrides_validade,
    )
    bloco_ce = _calcular_bloco_psicometrico_ponto_bisserial(
        codigo_bloco="CE",
        titulo_bloco="Objetivas de Componente Específico (CE)",
        questoes_bloco=questoes_ce_obj,
        provas_alunos=provas_alunos,
        respostas_por_pa=respostas_por_pa,
        overrides_validade=overrides_validade,
    )

    v_fg = bloco_fg["total_validas"]
    v_ce = bloco_ce["total_validas"]
    tem_bloco_fg = (len(questoes_fg_obj) + len(questoes_fg_diss)) > 0

    mapa_psico_fg = {q["pergunta_id"]: q for q in bloco_fg["questoes"]}
    mapa_psico_ce = {q["pergunta_id"]: q for q in bloco_ce["questoes"]}

    # Passo 2 (Etapa 5): Cálculo das Notas por Componente e Nota Final (Escala 0 a 1) por estudante
    resultados_alunos = []
    resultados_por_pa_id = {}

    for pa in provas_alunos:
        mapa_resp = respostas_por_pa.get(pa.id, {})
        mat_fg_aluno = bloco_fg["matriz_acertos"].get(pa.id, {})
        mat_ce_aluno = bloco_ce["matriz_acertos"].get(pa.id, {})

        # 1. Nota Objetiva de FG (NO_FG in [0, 1])
        escore_bruto_fg = bloco_fg["escores_brutos"].get(pa.id, 0)
        acertos_validos_fg = sum(
            1 for q in questoes_fg_obj
            if mat_fg_aluno.get(q["pergunta"].id, {}).get("valida")
            and mat_fg_aluno.get(q["pergunta"].id, {}).get("acertou")
        )
        no_fg = (float(acertos_validos_fg) / float(v_fg)) if v_fg > 0 else 0.0

        # 2. Nota Discursiva de FG (ND_FG in [0, 1])
        detalhes_diss_fg = []
        notas_diss_fg_01 = []
        for q in questoes_fg_diss:
            pid = q["pergunta"].id
            r_obj = mapa_resp.get(pid)
            nota_10 = 0.0
            if r_obj and getattr(r_obj, "nota", None) is not None:
                try:
                    nota_10 = max(0.0, min(10.0, float(r_obj.nota)))
                except (ValueError, TypeError):
                    nota_10 = 0.0
            # Se a nota foi salva diretamente em [0, 1] ou em [0, 10], normalizamos dividindo por 10
            nota_01 = nota_10 / 10.0
            notas_diss_fg_01.append(nota_01)
            detalhes_diss_fg.append({
                "numero": q["numero"],
                "numero_fmt": q["numero_fmt"],
                "pergunta_id": pid,
                "assunto_nome": q["assunto_nome"],
                "nota_0_10": round(nota_10, 2),
                "nota_0_1": round(nota_01, 4),
                "feedback": (r_obj.feedback_professor or "") if r_obj else "",
                "respondida": bool(r_obj and ((r_obj.resposta_texto or "").strip() or getattr(r_obj, "arquivo_resposta", None))),
            })
        nd_fg = (sum(notas_diss_fg_01) / float(len(notas_diss_fg_01))) if notas_diss_fg_01 else 0.0
        nd_fg_10 = nd_fg * 10.0

        # 3. Nota Total de Formação Geral: NT_FG = (0,65 * NO_FG) + (0,35 * ND_FG)
        nt_fg_parcela_obj = 0.65 * no_fg
        nt_fg_parcela_diss = 0.35 * nd_fg
        nt_fg = nt_fg_parcela_obj + nt_fg_parcela_diss

        # 4. Nota Objetiva de CE (NO_CE in [0, 1])
        escore_bruto_ce = bloco_ce["escores_brutos"].get(pa.id, 0)
        acertos_validos_ce = sum(
            1 for q in questoes_ce_obj
            if mat_ce_aluno.get(q["pergunta"].id, {}).get("valida")
            and mat_ce_aluno.get(q["pergunta"].id, {}).get("acertou")
        )
        no_ce = (float(acertos_validos_ce) / float(v_ce)) if v_ce > 0 else 0.0

        # 5. Nota Discursiva de CE (ND_CE in [0, 1])
        detalhes_diss_ce = []
        notas_diss_ce_01 = []
        for q in questoes_ce_diss:
            pid = q["pergunta"].id
            r_obj = mapa_resp.get(pid)
            nota_10 = 0.0
            if r_obj and getattr(r_obj, "nota", None) is not None:
                try:
                    nota_10 = max(0.0, min(10.0, float(r_obj.nota)))
                except (ValueError, TypeError):
                    nota_10 = 0.0
            nota_01 = nota_10 / 10.0
            notas_diss_ce_01.append(nota_01)
            detalhes_diss_ce.append({
                "numero": q["numero"],
                "numero_fmt": q["numero_fmt"],
                "pergunta_id": pid,
                "assunto_nome": q["assunto_nome"],
                "nota_0_10": round(nota_10, 2),
                "nota_0_1": round(nota_01, 4),
                "feedback": (r_obj.feedback_professor or "") if r_obj else "",
                "respondida": bool(r_obj and ((r_obj.resposta_texto or "").strip() or getattr(r_obj, "arquivo_resposta", None))),
            })
        nd_ce = (sum(notas_diss_ce_01) / float(len(notas_diss_ce_01))) if notas_diss_ce_01 else 0.0
        nd_ce_10 = nd_ce * 10.0

        # 6. Nota Total de Componente Específico: NT_CE = (0,90 * NO_CE) + (0,10 * ND_CE)
        nt_ce_parcela_obj = 0.90 * no_ce
        nt_ce_parcela_diss = 0.10 * nd_ce
        nt_ce = nt_ce_parcela_obj + nt_ce_parcela_diss

        # 7. Nota Geral do Estudante: NT_Ger = (0,25 * NT_FG) + (0,75 * NT_CE)
        parcela_ger_fg = 0.25 * nt_fg
        parcela_ger_ce = 0.75 * nt_ce
        nt_ger = parcela_ger_fg + parcela_ger_ce
        nt_ger_10 = nt_ger * 10.0

        # Contribuições diretas das 4 parcelas na Nota Final (soma máxima = 1,0000)
        contrib_fg_obj = 0.1625 * no_fg   # 25% * 65% = 0,1625
        contrib_fg_diss = 0.0875 * nd_fg  # 25% * 35% = 0,0875
        contrib_ce_obj = 0.6750 * no_ce   # 75% * 90% = 0,6750
        contrib_ce_diss = 0.0750 * nd_ce  # 75% * 10% = 0,0750

        # Detalhamento questão a questão das objetivas para o aluno entender cada item
        questoes_fg_detalhe_aluno = []
        for q in questoes_fg_obj:
            pid = q["pergunta"].id
            info_q = mapa_psico_fg.get(pid, {})
            info_a = mat_fg_aluno.get(pid, {})
            acertou_bruto = bool(info_a.get("acertou"))
            valida_q = bool(info_q.get("valida"))
            questoes_fg_detalhe_aluno.append({
                **info_q,
                "resposta_aluno": info_a.get("resposta", "--"),
                "acertou_preliminar": acertou_bruto,
                "contou_acerto_valido": bool(acertou_bruto and valida_q),
            })

        questoes_ce_detalhe_aluno = []
        for q in questoes_ce_obj:
            pid = q["pergunta"].id
            info_q = mapa_psico_ce.get(pid, {})
            info_a = mat_ce_aluno.get(pid, {})
            acertou_bruto = bool(info_a.get("acertou"))
            valida_q = bool(info_q.get("valida"))
            questoes_ce_detalhe_aluno.append({
                **info_q,
                "resposta_aluno": info_a.get("resposta", "--"),
                "acertou_preliminar": acertou_bruto,
                "contou_acerto_valido": bool(acertou_bruto and valida_q),
            })

        aluno_user = pa.aluno
        aluno_nome = (
            (aluno_user.get_full_name() or aluno_user.username)
            if hasattr(aluno_user, "get_full_name")
            else getattr(aluno_user, "username", f"Aluno #{pa.id}")
        )

        dados_aluno = {
            "prova_aluno_id": pa.id,
            "prova_aluno": pa,
            "aluno_id": getattr(aluno_user, "id", None),
            "aluno_nome": aluno_nome,
            "aluno_username": getattr(aluno_user, "username", ""),
            "status": getattr(pa, "status", "corrigida"),
            "data_conclusao": getattr(pa, "data_conclusao", None),
            "nota_salva_atual": float(pa.nota_final) if getattr(pa, "nota_final", None) is not None else None,
            # Bloco FG
            "total_fg_obj": len(questoes_fg_obj),
            "v_fg": v_fg,
            "escore_bruto_fg": escore_bruto_fg,
            "acertos_validos_fg": acertos_validos_fg,
            "no_fg": round(no_fg, 4),
            "no_fg_pct": round(no_fg * 100.0, 2),
            "nd_fg": round(nd_fg, 4),
            "nd_fg_10": round(nd_fg_10, 2),
            "nd_fg_pct": round(nd_fg * 100.0, 2),
            "nt_fg_parcela_obj": round(nt_fg_parcela_obj, 4),
            "nt_fg_parcela_diss": round(nt_fg_parcela_diss, 4),
            "nt_fg": round(nt_fg, 4),
            "nt_fg_10": round(nt_fg * 10.0, 2),
            "nt_fg_pct": round(nt_fg * 100.0, 2),
            # Bloco CE
            "total_ce_obj": len(questoes_ce_obj),
            "v_ce": v_ce,
            "escore_bruto_ce": escore_bruto_ce,
            "acertos_validos_ce": acertos_validos_ce,
            "no_ce": round(no_ce, 4),
            "no_ce_pct": round(no_ce * 100.0, 2),
            "nd_ce": round(nd_ce, 4),
            "nd_ce_10": round(nd_ce_10, 2),
            "nd_ce_pct": round(nd_ce * 100.0, 2),
            "nt_ce_parcela_obj": round(nt_ce_parcela_obj, 4),
            "nt_ce_parcela_diss": round(nt_ce_parcela_diss, 4),
            "nt_ce": round(nt_ce, 4),
            "nt_ce_10": round(nt_ce * 10.0, 2),
            "nt_ce_pct": round(nt_ce * 100.0, 2),
            # Nota Geral e Parcelas Diretas (0 a 1)
            "parcela_ger_fg": round(parcela_ger_fg, 4),
            "parcela_ger_ce": round(parcela_ger_ce, 4),
            "contrib_fg_obj": round(contrib_fg_obj, 4),
            "contrib_fg_diss": round(contrib_fg_diss, 4),
            "contrib_ce_obj": round(contrib_ce_obj, 4),
            "contrib_ce_diss": round(contrib_ce_diss, 4),
            "nt_ger": round(nt_ger, 4),
            "nt_ger_10": round(nt_ger_10, 2),
            "nt_ger_pct": round(nt_ger * 100.0, 2),
            # Listas detalhadas para a Memória de Cálculo Individual
            "questoes_fg_detalhe": questoes_fg_detalhe_aluno,
            "questoes_ce_detalhe": questoes_ce_detalhe_aluno,
            "dissertativas_fg_detalhe": detalhes_diss_fg,
            "dissertativas_ce_detalhe": detalhes_diss_ce,
        }
        resultados_alunos.append(dados_aluno)
        resultados_por_pa_id[pa.id] = dados_aluno

    # Médias gerais da turma na Etapa 5
    n_alunos = len(resultados_alunos)
    if n_alunos > 0:
        media_turma_nt_fg = round(sum(r["nt_fg"] for r in resultados_alunos) / n_alunos, 4)
        media_turma_nt_ce = round(sum(r["nt_ce"] for r in resultados_alunos) / n_alunos, 4)
        media_turma_nt_ger = round(sum(r["nt_ger"] for r in resultados_alunos) / n_alunos, 4)
        media_turma_nt_ger_10 = round(media_turma_nt_ger * 10.0, 2)
    else:
        media_turma_nt_fg = 0.0
        media_turma_nt_ce = 0.0
        media_turma_nt_ger = 0.0
        media_turma_nt_ger_10 = 0.0

    # Se solicitado, aplica e salva as notas finais consolidadas no banco de dados
    consolidado_em = fechamento_meta.get("consolidado_em")
    if aplicar_notas and hasattr(prova, "save"):
        agora_iso = timezone.now().isoformat()
        consolidado_em = agora_iso
        notas_snapshot = {}
        for r in resultados_alunos:
            pa_obj = r["prova_aluno"]
            if escala_nota_final == "0_10":
                pa_obj.nota_final = round(r["nt_ger_10"], 2)
            else:
                pa_obj.nota_final = round(r["nt_ger"], 2)
            pa_obj.status = "corrigida"
            if not getattr(pa_obj, "data_conclusao", None):
                pa_obj.data_conclusao = timezone.now()
            pa_obj.save()
            r["nota_salva_atual"] = float(pa_obj.nota_final)
            notas_snapshot[str(pa_obj.id)] = {
                "no_fg": r["no_fg"],
                "nd_fg": r["nd_fg"],
                "nt_fg": r["nt_fg"],
                "no_ce": r["no_ce"],
                "nd_ce": r["nd_ce"],
                "nt_ce": r["nt_ce"],
                "nt_ger": r["nt_ger"],
                "nt_ger_10": r["nt_ger_10"],
                "contrib_fg_obj": r["contrib_fg_obj"],
                "contrib_fg_diss": r["contrib_fg_diss"],
                "contrib_ce_obj": r["contrib_ce_obj"],
                "contrib_ce_diss": r["contrib_ce_diss"],
            }

        meta["fechamento_psicometrico"] = {
            "consolidado": True,
            "consolidado_em": agora_iso,
            "escala_nota_final": escala_nota_final,
            "overrides_validade": overrides_validade,
            "v_fg": v_fg,
            "v_ce": v_ce,
            "total_presentes": n_alunos,
            "notas_por_prova_aluno": notas_snapshot,
        }
        prova.descricao = empacotar_meta_unificada(descricao_humana, meta)
        prova.save(update_fields=["descricao"])

    pesos_efetivos_tabela = [
        {
            "parcela": "Objetivas de Formação Geral (NO_FG)",
            "formula_peso": "25% × 65%",
            "peso_percentual": "16,25%",
            "contribuicao_maxima": 0.1625,
            "codigo": "fg_obj",
        },
        {
            "parcela": "Discursiva de Formação Geral (ND_FG)",
            "formula_peso": "25% × 35%",
            "peso_percentual": "8,75%",
            "contribuicao_maxima": 0.0875,
            "codigo": "fg_diss",
        },
        {
            "parcela": "Objetivas de Componente Específico (NO_CE)",
            "formula_peso": "75% × 90%",
            "peso_percentual": "67,50%",
            "contribuicao_maxima": 0.6750,
            "codigo": "ce_obj",
        },
        {
            "parcela": "Discursiva de Componente Específico (ND_CE)",
            "formula_peso": "75% × 10%",
            "peso_percentual": "7,50%",
            "contribuicao_maxima": 0.0750,
            "codigo": "ce_diss",
        },
    ]

    return {
        "prova_id": getattr(prova, "id", None),
        "is_unificada": bool(estrutura.get("is_unificada", False)),
        "tem_bloco_fg": tem_bloco_fg,
        "consolidado": bool(fechamento_meta.get("consolidado") or aplicar_notas),
        "consolidado_em": consolidado_em,
        "escala_nota_final": escala_nota_final,
        "ponto_corte_rpb": PONTO_CORTE_RPB_ENADE,
        "total_presentes": n_alunos,
        "bloco_fg": bloco_fg,
        "bloco_ce": bloco_ce,
        "v_fg": v_fg,
        "v_ce": v_ce,
        "total_fg_obj": len(questoes_fg_obj),
        "total_fg_diss": len(questoes_fg_diss),
        "total_ce_obj": len(questoes_ce_obj),
        "total_ce_diss": len(questoes_ce_diss),
        "media_turma_nt_fg": media_turma_nt_fg,
        "media_turma_nt_ce": media_turma_nt_ce,
        "media_turma_nt_ger": media_turma_nt_ger,
        "media_turma_nt_ger_10": media_turma_nt_ger_10,
        "pesos_efetivos_tabela": pesos_efetivos_tabela,
        "resultados_alunos": resultados_alunos,
        "resultados_por_pa_id": resultados_por_pa_id,
        "overrides_validade": overrides_validade,
    }


def obter_explicacao_nota_unificada_aluno(prova_aluno) -> Optional[dict]:
    """
    Retorna o dicionário completo de explicação passo a passo da nota final (Modelo ENADE)
    para exibição ao aluno em `verResultadoProva` e no PDF `exportarCorrecaoPDF`.
    """
    if not prova_aluno or not getattr(prova_aluno, "aplicacao_prova", None):
        return None
    prova = prova_aluno.aplicacao_prova.prova
    fechamento = calcular_fechamento_psicometrico_unificada(prova, aplicar_notas=False)
    dados_aluno = fechamento["resultados_por_pa_id"].get(prova_aluno.id)
    if not dados_aluno:
        return None
    return {
        "fechamento": fechamento,
        "aluno": dados_aluno,
    }


def _estimar_peso_altura_bloco(bloco: dict, em_duas_colunas: bool = False) -> float:
    """
    Estima a fração de altura útil de uma folha A4 (podendo passar de 1.0 em questões
    muito grandes que ocupam até 2 páginas) para paginação inicial automática no servidor.
    """
    tipo = bloco.get("tipo")
    if tipo == "section_banner":
        return 0.06
    if tipo == "subject_subbanner":
        return 0.05

    texto_limpo = bloco.get("texto_plano") or ""
    chars_por_linha = 46 if em_duas_colunas else 90
    linhas_texto = max(2, (len(texto_limpo) // chars_por_linha) + texto_limpo.count("\n"))
    peso = 0.06 + (linhas_texto * 0.020)

    if bloco.get("tem_codigo"):
        peso += 0.14
    if bloco.get("tem_imagem"):
        peso += 0.18
    if bloco.get("is_dissertativa"):
        qtd_linhas = int(bloco.get("linhas_default") or 12)
        peso += 0.05 + (qtd_linhas * 0.024)

    return round(min(2.2, peso), 3)


def construir_diagramacao_unificada(prova, estrutura: Optional[dict] = None) -> dict:
    """
    Constrói o catálogo de blocos diagramáveis da Avaliação Unificada e reconcilia
    com o layout visual salvo em `meta['layout_diagramacao']` (páginas, 1 ou 2 colunas,
    blocos em largura total vs coluna esquerda/direita, número de linhas dissertativas,
    tamanho de imagens e colunas de alternativas).
    """
    if estrutura is None:
        estrutura = construir_estrutura_unificada(prova)

    secoes = estrutura.get("secoes") or {}
    blocos_ordenados = []
    blocos_map = {}

    def _add_bloco(b: dict):
        blocos_ordenados.append(b)
        blocos_map[b["id"]] = b

    # 1. PARTE I: CG Objetivas
    sec_cg_obj = secoes.get("cg_objetivas") or {}
    if sec_cg_obj.get("perguntas"):
        _add_bloco({
            "id": "banner:cg_objetivas",
            "tipo": "section_banner",
            "secao": "cg_objetivas",
            "titulo_esq": "PARTE I — CONHECIMENTOS GERAIS (QUESTÕES OBJETIVAS)",
            "titulo_dir": f"{sec_cg_obj.get('atual', 0)} QUESTÃO(ÕES)",
            "bg_color": "#111827",
            "default_zone_2col": "full",
        })
        for item in sec_cg_obj["perguntas"]:
            p = item["pergunta"]
            raw_txt = p.get_texto_com_feedback() or ""
            _add_bloco({
                "id": f"q:{p.id}",
                "tipo": "question",
                "secao": "cg_objetivas",
                "pergunta_id": p.id,
                "numero": item["numero"],
                "numero_fmt": f"{item['numero']:02d}",
                "header_esq": f"QUESTÃO {item['numero']:02d} • CONHECIMENTOS GERAIS",
                "header_dir": "MÚLTIPLA ESCOLHA",
                "html_corpo": str(p.texto_com_imagens_e_syntax_highlight),
                "texto_plano": re.sub(r"<[^>]+>", " ", raw_txt),
                "is_objetiva": True,
                "is_dissertativa": False,
                "is_sensacao": False,
                "tem_imagem": len(list(p.imagens.all())) > 0,
                "tem_codigo": "```" in raw_txt,
                "essay_header_esq": "",
                "essay_header_dir": "",
                "linhas_default": 0,
                "default_zone_2col": "col",
            })

    # 2. PARTE II: CG Dissertativa
    sec_cg_diss = secoes.get("cg_dissertativa") or {}
    if sec_cg_diss.get("perguntas"):
        _add_bloco({
            "id": "banner:cg_dissertativa",
            "tipo": "section_banner",
            "secao": "cg_dissertativa",
            "titulo_esq": "PARTE II — QUESTÃO DISSERTATIVA (CONHECIMENTO GERAL)",
            "titulo_dir": f"{sec_cg_diss.get('atual', 0)} QUESTÃO(ÕES)",
            "bg_color": "#111827",
            "default_zone_2col": "full",
        })
        for item in sec_cg_diss["perguntas"]:
            p = item["pergunta"]
            raw_txt = p.get_texto_com_feedback() or ""
            is_diss = bool(item.get("is_dissertativa", True))
            _add_bloco({
                "id": f"q:{p.id}",
                "tipo": "question",
                "secao": "cg_dissertativa",
                "pergunta_id": p.id,
                "numero": item["numero"],
                "numero_fmt": f"{item['numero']:02d}",
                "header_esq": f"QUESTÃO {item['numero']:02d} • DISSERTATIVA DE CONHECIMENTO GERAL",
                "header_dir": "RESPOSTA ARGUMENTATIVA" if is_diss else "MÚLTIPLA ESCOLHA",
                "html_corpo": str(p.texto_com_imagens_e_syntax_highlight),
                "texto_plano": re.sub(r"<[^>]+>", " ", raw_txt),
                "is_objetiva": not is_diss,
                "is_dissertativa": is_diss,
                "is_sensacao": False,
                "tem_imagem": len(list(p.imagens.all())) > 0,
                "tem_codigo": "```" in raw_txt,
                "essay_header_esq": f"ESPAÇO PARA RESPOSTA DA QUESTÃO {item['numero']:02d}",
                "essay_header_dir": f"[DISSERTATIVA Q{item['numero']:02d}]",
                "linhas_default": 12 if is_diss else 0,
                "default_zone_2col": "full" if is_diss else "col",
            })

    # 3. PARTE III: Conhecimentos Específicos por Matéria do Módulo (ou Questões Objetivas da Prova Simples)
    is_unif_doc = bool(estrutura.get("is_unificada", False))
    qtd_assuntos_doc = len(estrutura.get("assuntos") or [])
    sec_mat = secoes.get("materia_objetivas") or {}
    if sec_mat.get("perguntas"):
        _add_bloco({
            "id": "banner:materia_objetivas",
            "tipo": "section_banner",
            "secao": "materia_objetivas",
            "titulo_esq": (
                "PARTE III — CONHECIMENTOS ESPECÍFICOS POR MATÉRIA DO MÓDULO"
                if is_unif_doc
                else "QUESTÕES OBJETIVAS (MÚLTIPLA ESCOLHA)"
            ),
            "titulo_dir": f"{sec_mat.get('atual', 0)} QUESTÃO(ÕES)",
            "bg_color": "#111827",
            "default_zone_2col": "full",
        })
        for mat in sec_mat.get("por_materia") or []:
            if mat.get("perguntas"):
                assunto_obj = mat["assunto"]
                if is_unif_doc or qtd_assuntos_doc > 1:
                    _add_bloco({
                        "id": f"subbanner:materia:{assunto_obj.id}",
                        "tipo": "subject_subbanner",
                        "secao": "materia_objetivas",
                        "assunto_id": assunto_obj.id,
                        "titulo": f"DISCIPLINA / ASSUNTO: {assunto_obj.nome.upper()} ({mat.get('atual', 0)} questão(ões))",
                        "default_zone_2col": "col",
                    })
                for item in mat["perguntas"]:
                    p = item["pergunta"]
                    raw_txt = p.get_texto_com_feedback() or ""
                    _add_bloco({
                        "id": f"q:{p.id}",
                        "tipo": "question",
                        "secao": "materia_objetivas",
                        "pergunta_id": p.id,
                        "numero": item["numero"],
                        "numero_fmt": f"{item['numero']:02d}",
                        "header_esq": f"QUESTÃO {item['numero']:02d} • {assunto_obj.nome.upper()}",
                        "header_dir": "MÚLTIPLA ESCOLHA" if item.get("is_objetiva", True) else "DISSERTATIVA",
                        "html_corpo": str(p.texto_com_imagens_e_syntax_highlight),
                        "texto_plano": re.sub(r"<[^>]+>", " ", raw_txt),
                        "is_objetiva": bool(item.get("is_objetiva", True)),
                        "is_dissertativa": bool(item.get("is_dissertativa", False)),
                        "is_sensacao": False,
                        "tem_imagem": len(list(p.imagens.all())) > 0,
                        "tem_codigo": "```" in raw_txt,
                        "essay_header_esq": f"ESPAÇO PARA RESPOSTA DA QUESTÃO {item['numero']:02d}",
                        "essay_header_dir": f"[DISSERTATIVA Q{item['numero']:02d}]",
                        "linhas_default": 10 if item.get("is_dissertativa") else 0,
                        "default_zone_2col": "col",
                    })

    # 4. PARTE IV: Dissertativa Técnica (ou Questões Dissertativas da Prova Simples)
    sec_diss_tec = secoes.get("dissertativa_tecnica") or {}
    if sec_diss_tec.get("perguntas"):
        _add_bloco({
            "id": "banner:dissertativa_tecnica",
            "tipo": "section_banner",
            "secao": "dissertativa_tecnica",
            "titulo_esq": (
                "PARTE IV — QUESTÃO DISSERTATIVA TÉCNICA DO MÓDULO"
                if is_unif_doc
                else "QUESTÕES DISSERTATIVAS"
            ),
            "titulo_dir": f"{sec_diss_tec.get('atual', 0)} QUESTÃO(ÕES)",
            "bg_color": "#111827",
            "default_zone_2col": "full",
        })
        for item in sec_diss_tec["perguntas"]:
            p = item["pergunta"]
            raw_txt = p.get_texto_com_feedback() or ""
            is_diss = bool(item.get("is_dissertativa", True))
            _add_bloco({
                "id": f"q:{p.id}",
                "tipo": "question",
                "secao": "dissertativa_tecnica",
                "pergunta_id": p.id,
                "numero": item["numero"],
                "numero_fmt": f"{item['numero']:02d}",
                "header_esq": (
                    f"QUESTÃO {item['numero']:02d} • DISSERTATIVA TÉCNICA ({item['assunto_nome'].upper()})"
                    if is_unif_doc
                    else f"QUESTÃO {item['numero']:02d} • {item['assunto_nome'].upper()}"
                ),
                "header_dir": "RESPOSTA TÉCNICA" if (is_diss and is_unif_doc) else ("QUESTÃO DISSERTATIVA" if is_diss else "MÚLTIPLA ESCOLHA"),
                "html_corpo": str(p.texto_com_imagens_e_syntax_highlight),
                "texto_plano": re.sub(r"<[^>]+>", " ", raw_txt),
                "is_objetiva": not is_diss,
                "is_dissertativa": is_diss,
                "is_sensacao": False,
                "tem_imagem": len(list(p.imagens.all())) > 0,
                "tem_codigo": "```" in raw_txt,
                "essay_header_esq": f"ESPAÇO PARA RESPOSTA DA QUESTÃO {item['numero']:02d}",
                "essay_header_dir": f"[DISSERTATIVA Q{item['numero']:02d}]",
                "linhas_default": 12 if is_diss else 0,
                "default_zone_2col": "full" if is_diss else "col",
            })

    # 5. PARTE V: Sensação do Aluno
    sec_sens = secoes.get("sensacao_aluno") or {}
    if sec_sens.get("perguntas"):
        _add_bloco({
            "id": "banner:sensacao_aluno",
            "tipo": "section_banner",
            "secao": "sensacao_aluno",
            "titulo_esq": "PARTE V — SENSAÇÃO DO ALUNO SOBRE A PROVA (AUTOAVALIAÇÃO • PESO ZERO)",
            "titulo_dir": f"{sec_sens.get('atual', 0)} ITEM(NS)",
            "bg_color": "#374151",
            "default_zone_2col": "full",
        })
        for item in sec_sens["perguntas"]:
            p = item["pergunta"]
            raw_txt = p.get_texto_com_feedback() or ""
            _add_bloco({
                "id": f"q:{p.id}",
                "tipo": "question",
                "secao": "sensacao_aluno",
                "pergunta_id": p.id,
                "numero": item["numero"],
                "numero_fmt": f"{item['numero']:02d}",
                "header_esq": f"ITEM {item['numero']:02d} • PERCEPÇÃO E AUTOAVALIAÇÃO DO ESTUDANTE",
                "header_dir": "NÃO PENALIZA A NOTA",
                "html_corpo": str(p.texto_com_imagens_e_syntax_highlight),
                "texto_plano": re.sub(r"<[^>]+>", " ", raw_txt),
                "is_objetiva": True,
                "is_dissertativa": False,
                "is_sensacao": True,
                "tem_imagem": len(list(p.imagens.all())) > 0,
                "tem_codigo": "```" in raw_txt,
                "essay_header_esq": "",
                "essay_header_dir": "",
                "linhas_default": 0,
                "default_zone_2col": "col",
            })

    default_config = {
        "font_size": "10pt",
        "margin_mm": 12,
        "question_gap": 10,
        "column_rule": True,
        "card_style": "bordered",
        "repeat_mini_header": True,
        "default_alt_cols": 1,
        "omr_cols": 1,
        "omr_pages": 1,
        "omr_essay_lines": 12,
        "omr_page_map": {},
    }

    meta = estrutura.get("meta") or {}
    saved_layout = meta.get("layout_diagramacao") or {}

    config = dict(default_config)
    if isinstance(saved_layout.get("config"), dict):
        config.update(saved_layout["config"])
    if not isinstance(config.get("omr_page_map"), dict):
        config["omr_page_map"] = {}

    saved_block_opts = saved_layout.get("block_opts") if isinstance(saved_layout.get("block_opts"), dict) else {}
    block_opts = {}
    for b in blocos_ordenados:
        bid = b["id"]
        opt_saved = saved_block_opts.get(bid) if isinstance(saved_block_opts.get(bid), dict) else {}
        peso_est = _estimar_peso_altura_bloco(b, em_duas_colunas=False)
        b["peso_estimado"] = peso_est
        default_allow_break = bool(peso_est >= 0.55 or b.get("is_dissertativa") or b.get("tem_codigo"))
        block_opts[bid] = {
            "alt_cols": int(opt_saved.get("alt_cols", config.get("default_alt_cols", 1)) or 1),
            "img_size": opt_saved.get("img_size", "md") if opt_saved.get("img_size") in ("sm", "md", "lg", "full") else "md",
            "essay_lines": int(opt_saved.get("essay_lines", b.get("linhas_default", 12)) if b.get("is_dissertativa") else 0),
            "allow_page_break": bool(opt_saved.get("allow_page_break", default_allow_break)),
        }

    # Reconcilia páginas salvas ou gera paginação inicial inteligente
    saved_pages = saved_layout.get("pages") if isinstance(saved_layout.get("pages"), list) else []
    pages_reconciled = []
    seen_ids = set()

    if saved_pages:
        for idx_p, pg in enumerate(saved_pages, 1):
            if not isinstance(pg, dict):
                continue
            cols = 2 if int(pg.get("cols", 1) or 1) == 2 else 1
            span_pages = 2 if int(pg.get("span_pages", 1) or 1) >= 2 else 1
            raw_items = pg.get("items") if isinstance(pg.get("items"), list) else []
            valid_items = []
            for it in raw_items:
                if not isinstance(it, dict):
                    continue
                bid = it.get("id")
                if bid in blocos_map and bid not in seen_ids:
                    seen_ids.add(bid)
                    zone = it.get("zone", "full")
                    if cols == 1:
                        zone = "full"
                    elif zone not in ("full", "col1", "col2"):
                        zone = "full" if blocos_map[bid].get("default_zone_2col") == "full" else "col1"
                    valid_items.append({"id": bid, "zone": zone})
            pages_reconciled.append({
                "id": pg.get("id") or f"page_{idx_p}",
                "cols": cols,
                "span_pages": span_pages,
                "items": valid_items,
            })

        # Se existirem blocos novos na prova que ainda não estavam salvos no layout, insere na página adequada
        if not pages_reconciled:
            pages_reconciled.append({"id": "page_1", "cols": 1, "span_pages": 1, "items": []})

        for idx_b, b in enumerate(blocos_ordenados):
            bid = b["id"]
            if bid in seen_ids:
                continue
            inserted = False
            if idx_b > 0:
                prev_id = blocos_ordenados[idx_b - 1]["id"]
                for pg in pages_reconciled:
                    for pos, it in enumerate(pg["items"]):
                        if it["id"] == prev_id:
                            zone_new = "full" if pg["cols"] == 1 else (
                                "full" if b.get("default_zone_2col") == "full" else it.get("zone", "col1")
                            )
                            pg["items"].insert(pos + 1, {"id": bid, "zone": zone_new})
                            inserted = True
                            break
                    if inserted:
                        break
            if not inserted:
                last_pg = pages_reconciled[-1]
                zone_new = "full" if last_pg["cols"] == 1 else (
                    "full" if b.get("default_zone_2col") == "full" else "col1"
                )
                last_pg["items"].append({"id": bid, "zone": zone_new})
            seen_ids.add(bid)

        # Remove páginas vazias para nunca gerar folha em branco na impressão
        pages_reconciled = [pg for pg in pages_reconciled if pg["items"]] or [{"id": "page_1", "cols": 1, "span_pages": 1, "items": []}]
    else:
        # Gera paginação padrão inicial (1 coluna balanceada com margem de segurança contra folhas em branco)
        cur_items = []
        cur_weight = 0.32  # Reserva topo para o cabeçalho institucional + instruções da Página 1
        page_idx = 1

        for b in blocos_ordenados:
            w = b.get("peso_estimado") or _estimar_peso_altura_bloco(b, em_duas_colunas=False)
            if cur_items and (cur_weight + w > 0.78):
                trailing_banners = []
                while cur_items and blocos_map[cur_items[-1]["id"]]["tipo"] in ("section_banner", "subject_subbanner"):
                    trailing_banners.insert(0, cur_items.pop())

                if cur_items:
                    est_span = 2 if cur_weight > 1.05 else 1
                    pages_reconciled.append({
                        "id": f"page_{page_idx}",
                        "cols": 1,
                        "span_pages": est_span,
                        "items": cur_items,
                    })
                    page_idx += 1
                    cur_items = list(trailing_banners)
                    cur_weight = 0.08 + sum(_estimar_peso_altura_bloco(blocos_map[x["id"]]) for x in cur_items)
                else:
                    cur_items = list(trailing_banners)

            cur_items.append({"id": b["id"], "zone": "full"})
            cur_weight += w

        if cur_items or not pages_reconciled:
            est_span = 2 if cur_weight > 1.05 else 1
            pages_reconciled.append({
                "id": f"page_{page_idx}",
                "cols": 1,
                "span_pages": est_span,
                "items": cur_items,
            })

    # Constrói a árvore renderizável de cada página com segmentos (full vs two_cols) para o WeasyPrint e Template
    paginas_render = []
    for idx_p, pg in enumerate(pages_reconciled, 1):
        cols = pg["cols"]
        span_pages = 2 if int(pg.get("span_pages", 1) or 1) >= 2 else 1
        segments = []
        for it in pg["items"]:
            bid = it["id"]
            if bid not in blocos_map:
                continue
            bloco_obj = dict(blocos_map[bid])
            opts = block_opts.get(bid, {})
            bloco_obj["opts"] = opts
            bloco_obj["linhas_range"] = range(1, max(0, int(opts.get("essay_lines", 12))) + 1)
            zone = "full" if cols == 1 else it.get("zone", "full")
            bloco_obj["zone"] = zone

            if zone == "full":
                segments.append({
                    "type": "full",
                    "item": bloco_obj,
                })
            else:
                if not segments or segments[-1]["type"] != "two_cols":
                    segments.append({
                        "type": "two_cols",
                        "col1": [],
                        "col2": [],
                    })
                if zone == "col2":
                    segments[-1]["col2"].append(bloco_obj)
                else:
                    segments[-1]["col1"].append(bloco_obj)

        paginas_render.append({
            "numero": idx_p,
            "id": pg["id"],
            "cols": cols,
            "span_pages": span_pages,
            "segments": segments,
            "total_itens": len(pg["items"]),
        })

    layout_state = {
        "config": config,
        "block_opts": block_opts,
        "pages": pages_reconciled,
    }

    return {
        "config": config,
        "block_opts": block_opts,
        "pages_state": pages_reconciled,
        "paginas_render": paginas_render,
        "blocos_ordenados": blocos_ordenados,
        "blocos_map": blocos_map,
        "layout_state": layout_state,
    }

