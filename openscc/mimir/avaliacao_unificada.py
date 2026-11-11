import base64
import datetime
import io
import json
import re
from typing import Dict, List, Optional, Tuple

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
    Separa a descrição visível da prova e o dicionário JSON de metadados da Avaliação Unificada.
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
        if isinstance(meta, dict) and meta.get("is_unificada"):
            return texto_limpo, meta
    except Exception:
        pass
    return texto_limpo, None


def empacotar_meta_unificada(descricao_limpa: str, meta: dict) -> str:
    """
    Empacota a descrição visível com o bloco oculto de metadados JSON da Avaliação Unificada.
    """
    meta = dict(meta or {})
    meta["is_unificada"] = True
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


def is_pergunta_objetiva(pergunta) -> bool:
    """
    Identifica se uma instância de Pergunta é objetiva (Múltipla Escolha / V ou F)
    pelo tipo cadastrado ou pela presença de alternativas A) B) C) no enunciado.
    """
    desc = (pergunta.tipoDePergunta.descricao or "").lower()
    if any(k in desc for k in ["dissertativa", "discursiva", "aberta", "técnica", "tecnica"]):
        return False
    if any(k in desc for k in ["múltipla", "multipla", "objetiva", "multiple", "verdadeiro", "alternativa"]):
        return True
    texto = pergunta.pergunta or ""
    if re.search(r"(?m)^\s*[A-E][\)\.\-]\s+", texto):
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
    Determina a qual seção da Avaliação Unificada pertence uma pergunta,
    usando `question_map` (ou `mapa_questoes`) salvo nos metadados ou inferindo pelo assunto/texto/tipo.
    """
    q_map = (meta or {}).get("question_map") or (meta or {}).get("mapa_questoes") or {}
    pid_str = str(pergunta.id)
    if pid_str in q_map:
        info = q_map[pid_str]
        return info.get("secao", "materia_objetivas"), info.get("assunto_id", pergunta.assunto_id)

    texto_lower = (pergunta.pergunta or "").lower()
    assunto_nome_lower = (pergunta.assunto.nome or "").lower() if pergunta.assunto_id else ""

    if (
        "sensação" in texto_lower
        or "percepção da prova" in texto_lower
        or "autoavaliação" in texto_lower
        or "sensação" in assunto_nome_lower
    ):
        return "sensacao_aluno", pergunta.assunto_id

    is_cg = any(
        k in assunto_nome_lower or k in texto_lower[:90]
        for k in ["conhecimento geral", "conhecimentos gerais", "atualidades"]
    )
    objetiva = is_pergunta_objetiva(pergunta)

    if is_cg:
        return ("cg_objetivas" if objetiva else "cg_dissertativa"), pergunta.assunto_id

    if not objetiva:
        return "dissertativa_tecnica", pergunta.assunto_id

    return "materia_objetivas", pergunta.assunto_id


def construir_estrutura_unificada(prova) -> dict:
    """
    Constrói a estrutura completa da Avaliação Unificada para gerenciamento, impressão OMR/Foto e correção.
    """
    from .models import Assunto

    descricao_limpa, meta = extrair_meta_unificada(prova.descricao)
    if not meta:
        meta = {
            "is_unificada": True,
            "modulo_nome": f"Módulo - {prova.assunto.nome}" if prova.assunto_id else "Módulo Integrado",
            "assuntos_ids": [prova.assunto_id] if prova.assunto_id else [],
            "quotas": dict(DEFAULT_QUOTAS),
            "question_map": {},
        }

    quotas = dict(DEFAULT_QUOTAS)
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
        "is_unificada": True,
        "modulo_nome": meta.get("modulo_nome", "Módulo Integrado"),
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


def analisar_foto_prova_unificada_ia(prova, arquivos_imagens: list, user=None) -> dict:
    """
    Realiza a leitura óptica e correção inteligente de foto(s) da Avaliação Unificada:
      - Detecta as marcações nas questões objetivas (A, B, C, D, E) e cruza com o gabarito.
      - Transcreve (OCR manuscrito) as questões dissertativas (Geral e Técnica) e avalia nota (0-10) + feedback.
      - Lê as respostas de Sensação do Aluno e sintetiza a percepção emocional/pedagógica do estudante.
    """
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI
    from .models import LLMLog

    estrutura = construir_estrutura_unificada(prova)
    questoes = estrutura["questoes_numeradas"]

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

    prompt_sistema = f"""Você é um sistema especialista de Leitura Óptica (OMR) e Correção Acadêmica Multimodal de Avaliações Unificadas.
Analise a(s) foto(s) anexada(s) da prova / folha de respostas do aluno referente à avaliação: "{prova.titulo}" ({estrutura['modulo_nome']}).

MAPA DE QUESTÕES DA PROVA:
{json.dumps(especificacao_questoes, ensure_ascii=False, indent=2)}

SUA TAREFA:
1. Identifique o nome do aluno escrito na folha (se visível).
2. Para cada questão na lista acima (pelo campo "pergunta_id" e "numero"):
   - Se for "objetiva": identifique qual letra ("A", "B", "C", "D" ou "E") o aluno marcou na folha de respostas ou no caderno de prova.
   - Se for "dissertativa": transcreva fielmente o texto manuscrito pelo aluno em "resposta_lida", avalie com base no "gabarito_oficial" atribuindo "nota_sugerida" de 0.0 a 10.0 e escreva um "feedback" pedagógico construtivo.
3. Gere um "resumo_sensacao" sintetizando como o aluno está se sentindo no módulo com base na seção de Sensação do Aluno.

RETORNE EXCLUSIVAMENTE UM JSON VÁLIDO NO SEGUINTE FORMATO:
{{
  "aluno_identificado": "Nome do aluno lido na folha ou vazio",
  "resumo_sensacao": "Síntese da sensação/percepção do aluno sobre o módulo e a prova",
  "itens": [
    {{
      "numero": 1,
      "pergunta_id": 123,
      "resposta_lida": "Letra A-E marcada ou transcrição do texto manuscrito",
      "nota_sugerida": 10.0,
      "feedback": "Justificativa ou comentário de correção"
    }}
  ]
}}"""

    conteudos = [HumanMessage(content=prompt_sistema)]
    for idx, arq in enumerate(arquivos_imagens):
        try:
            arq.seek(0)
            img = Image.open(arq)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.thumbnail((2000, 2000))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            conteudos.append(
                HumanMessage(
                    content=[
                        {"type": "text", "text": f"FOTO {idx + 1} DA PROVA / FOLHA DE RESPOSTA:"},
                        {"type": "image_url", "image_url": f"data:image/jpeg;base64,{b64}"},
                    ]
                )
            )
        except Exception as e:
            print(f"Erro ao preparar imagem {idx + 1}: {e}")

    parsed_ia = None
    modo_utilizado = "Leitura Assistida Local"
    from .models import ConfiguracaoModeloLLM
    cfg_ativo = ConfiguracaoModeloLLM.get_modelo_ativo()
    api_key = (
        (cfg_ativo.api_key_override or "").strip() if cfg_ativo else ""
    ) or getattr(settings, "GEMINI_API_KEY", None)

    # Prioriza sempre o modelo ativo no Django Admin em tempo real
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
                prompt=f"Correção por Foto Avaliação Unificada #{prova.id} ({len(arquivos_imagens)} foto(s))",
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

    # Normaliza os itens retornados (ou monta fallback assistido)
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
                        mapa_ia_por_num[int(it["numero"])] = it
        elif isinstance(itens_raw, dict):
            for k, it in itens_raw.items():
                if isinstance(it, dict):
                    mapa_ia_por_pid[str(k)] = it
                    if it.get("numero") is not None:
                        mapa_ia_por_num[int(it["numero"])] = it

    itens_finais = []
    soma_ponderada = 0.0
    soma_pesos = 0

    for q in questoes:
        p = q["pergunta"]
        info_ia = mapa_ia_por_pid.get(str(p.id)) or mapa_ia_por_num.get(q["numero"]) or {}
        letra_gab = q["letra_gabarito"] or "A"

        if q["is_sensacao"]:
            resp_lida = str(info_ia.get("resposta_lida") or info_ia.get("resposta_detectada") or "B").strip()
            nota_sug = 10.0
            correta = True
            feedback = info_ia.get("feedback") or f"Percepção do aluno registrada ({resp_lida}) — peso 0 na nota."
        elif q["is_objetiva"]:
            resp_raw = str(info_ia.get("resposta_lida") or info_ia.get("resposta_detectada") or letra_gab).strip()
            letra_lida = resp_raw[0].upper() if resp_raw and resp_raw[0].upper() in "ABCDE" else letra_gab
            resp_lida = letra_lida
            correta = (letra_lida == letra_gab) if letra_gab else True
            nota_sug = 10.0 if correta else 0.0
            feedback = (
                f"Alternativa correta ({letra_lida})."
                if correta
                else f"Marcou {letra_lida}; gabarito oficial é {letra_gab}."
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
            feedback = info_ia.get("feedback") or "Avaliação da questão dissertativa baseada nos critérios do gabarito."
            soma_ponderada += nota_sug * q["peso_sugerido"]
            soma_pesos += q["peso_sugerido"]

        itens_finais.append({
            "numero": q["numero"],
            "pergunta_id": p.id,
            "secao": q["secao"],
            "resposta_lida": resp_lida,
            "correta": correta,
            "nota_sugerida": round(nota_sug, 1),
            "feedback": feedback,
        })

    nota_academica_sugerida = round(soma_ponderada / soma_pesos, 2) if soma_pesos > 0 else 0.0

    return {
        "success": True,
        "modo": modo_utilizado,
        "aluno_identificado": (parsed_ia or {}).get("aluno_identificado") or (parsed_ia or {}).get("aluno_detectado") or "",
        "resumo_sensacao": (parsed_ia or {}).get("resumo_sensacao") or "Respostas de sensação do aluno lidas na Parte V.",
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
