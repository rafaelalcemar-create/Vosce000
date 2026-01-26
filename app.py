import os
import streamlit as st
import google.generativeai as genai

# dotenv é útil localmente, mas no Streamlit Cloud pode não estar instalado
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

def get_gemini_key() -> str | None:
    # 1) Streamlit secrets
    try:
        key = st.secrets.get("GEMINI_API_KEY", None)
        if key:
            return str(key).strip()
    except Exception:
        pass

    # 2) Env var
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return str(key).strip()

    return None

API_KEY = get_gemini_key()
if not API_KEY:
    st.error("API Key do Gemini não encontrada. Configure GEMINI_API_KEY em Secrets (Streamlit) ou como variável de ambiente.")
    st.stop()

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")
# ============================
# AVALIAÇÃO DE COMUNICAÇÃO/POSTURA (regras objetivas + flags)
# ============================

COMM_BAD_PATTERNS = [
    ("linguagem_hostil", ["burro", "idiota", "cala a boca", "ridículo", "ridicula", "foda-se", "se vira"]),
    ("culpabilizacao", ["a culpa é sua", "isso é porque você", "você fez errado", "você provocou"]),
    ("desrespeito", ["não me interessa", "tanto faz", "você não sabe nada"]),
]

COMM_GOOD_PATTERNS = [
    ("empatia", ["entendo", "imagino", "deve ser", "sinto muito", "vamos com calma"]),
    ("consentimento", ["tudo bem se eu", "posso te perguntar", "com sua permissão", "você autoriza"]),
    ("privacidade", ["pergunta pessoal", "vou perguntar algo íntimo", "se sentir desconfortável"]),
    ("explicacao", ["vou explicar", "o objetivo é", "isso serve para", "para entender melhor"]),
]

def evaluate_communication_turn(student_text: str):
    init_osce_scoring()
    t = (student_text or "").lower()

    # flags ruins
    for tag, patterns in COMM_BAD_PATTERNS:
        if any(p in t for p in patterns):
            st.session_state.osce["flags"].append({
                "type": tag,
                "text": student_text.strip()
            })
            add_checklist("communication", f"Evitar: {tag}", False, weight=2)

    # sinais bons
    for tag, patterns in COMM_GOOD_PATTERNS:
        if any(p in t for p in patterns):
            add_checklist("communication", f"Demonstrou: {tag}", True, weight=1)

    # sempre tem item base
    add_checklist("communication", "Manteve linguagem respeitosa", True, weight=2)

    # recalcula score de comunicação
    st.session_state.osce["scores"]["communication"] = score_from_checklist("communication")

def communication_summary_text():
    init_osce_scoring()
    flags = st.session_state.osce["flags"]
    score = st.session_state.osce["scores"]["communication"]
    if not flags:
        return f"Comunicação/postura: {score}/10. Sem flags de desrespeito."
    lines = [f"Comunicação/postura: {score}/10.", "Flags identificadas:"]
    for f in flags[:5]:
        lines.append(f"- {f['type']}: “{f['text']}”")
    if len(flags) > 5:
        lines.append(f"- (+{len(flags)-5} outras)")
    return "\n".join(lines)
def responder_como_paciente(pergunta: str) -> str:
    """
    Paciente OSCE com controle de vazamento de informação:
    - Responde apenas ao que foi perguntado (1–2 frases).
    - Não lista sintomas adicionais.
    - Mantém coerência usando clinical_truth.
    """

    # pega dados do caso (se houver)
    case = {}
    if st.session_state.selected_syndrome and st.session_state.selected_case:
        case = cases.get(st.session_state.selected_syndrome, {}).get(st.session_state.selected_case, {})
    truth = case.get("clinical_truth", {})

    q = (pergunta or "").lower().strip()

    # --------- Respostas determinísticas (fatos) ----------
    if any(k in q for k in ["nome", "como se chama", "seu nome", "chama-se"]):
        nome = truth.get("nome")
        return f"Meu nome é {nome}." if nome else "Meu nome não foi informado."

    if "idade" in q or "quantos anos" in q:
        idade = truth.get("idade")
        return f"Tenho {idade} anos." if idade else "Idade não informada."

    if any(k in q for k in ["sexo", "gênero", "genero", "masculino", "feminino"]):
        sexo = truth.get("sexo")
        return f"Sou {sexo}." if sexo else "Sexo não informado."

    # --------- Router: identifica o FOCO da pergunta ----------
    # (você pode expandir esse dicionário com mais temas)
    topics = {
        "febre": ["febre", "temperatura", "calafrio", "calafrios"],
        "dor_lombar": ["dor nas costas", "dor lombar", "costa", "flanco", "giordano"],
        "disuria": ["ardor", "ardência", "ardencia", "queimação", "queimacao", "dor ao urinar", "disúria", "disuria"],
        "frequencia": ["toda hora", "muitas vezes", "frequente", "frequência", "frequencia", "polaqui", "poliúria", "poliuria"],
        "urgencia": ["urgência", "urgencia", "segurar", "corre pro banheiro", "vontade súbita"],
        "hematúria": ["sangue na urina", "urina vermelha", "hematúria", "hematuria"],
        "nausea": ["náusea", "nausea", "vômito", "vomito"],
        "historia": ["começou", "há quanto tempo", "desde quando", "início", "inicio", "evolução", "evolucao"],
    }

    focus = None
    for topic, keys in topics.items():
        if any(k in q for k in keys):
            focus = topic
            break

    # Se não achou foco, responde curto e pede próxima pergunta
    # (isso reduz muito o "monólogo" inicial)
    if focus is None:
        prompt = f"""
Você é um paciente em simulação clínica de OSCE.

REGRAS OBRIGATÓRIAS (muito importante):
- Responda APENAS ao que foi perguntado.
- NÃO ofereça sintomas extras nem faça resumo do caso.
- Resposta curta: no máximo 1–2 frases.
- Linguagem leiga.
- Se a pergunta for ampla/vaga, peça que o aluno especifique ("O que exatamente você quer saber?").

Fatos do caso (NÃO altere): {truth}

Pergunta do aluno:
"{pergunta}"
"""
        resp = model.generate_content(prompt)
        return resp.text.strip()

    # --------- Resposta guiada por foco (anti-vazamento) ----------
    prompt = f"""
Você é um paciente em simulação clínica de OSCE.

FATOS DO CASO (verdade fixa; não invente nem altere): {truth}

O aluno perguntou algo sobre o seguinte FOCO: {focus}

REGRAS OBRIGATÓRIAS:
- Responda SOMENTE sobre o FOCO ({focus}).
- NÃO cite outros sintomas (mesmo que existam no caso) se não forem do FOCO.
- Resposta curta: 1 frase (no máximo 2).
- Linguagem leiga.
- Não mencione diagnóstico, exames ou tratamento.
- Se o foco não existir no caso, responda negativamente ("não", "não tenho isso").

Pergunta do aluno:
"{pergunta}"

Responda agora como paciente:
"""
    resp = model.generate_content(prompt)
    return resp.text.strip()
def fornecer_resultado_exame(exame: str) -> str:
    """
    Laudo determinístico + avaliação de pertinência.
    Mantém log e pontuação em st.session_state.osce
    """
    init_osce_scoring()

    case = cases[st.session_state.selected_syndrome][st.session_state.selected_case]
    truth = case["clinical_truth"]
    indications = case["exam_indications"]

    # garantir log
    if "exam_log" not in st.session_state.osce:
        st.session_state.osce["exam_log"] = []

    # se exame não aplicável
    if exame not in indications:
        st.session_state.osce["exam_log"].append({"exam": exame, "pertinence": "não aplicável"})
        add_checklist("exams", f"{exame}: escolha pertinente", False, weight=2)
        st.session_state.osce["scores"]["exams"] = score_from_checklist("exams")
        return "Exame não aplicável a este caso clínico."

    indication = indications[exame]

    # pertinência
    if indication == "inadequado":
        pertinence = "inadequado"
        add_checklist("exams", f"{exame}: evitar exame desnecessário", False, weight=3)
    else:
        pertinence = "adequado"
        add_checklist("exams", f"{exame}: exame indicado", True, weight=2)

    # -------- Laudos determinísticos --------
    if indication == "inadequado":
        resultado = f"O exame solicitado ({exame}) não é indicado para este quadro clínico e não contribui para o diagnóstico."

    elif exame == "EAS":
        if indication in ["alterado", "hematúria"]:
            leucocitos = "1-5 /campo"
            nitrito = "Negativo"
            sangue = "Negativo"

            hemat = truth.get("hematúria")
            if hemat == "microscópica":
                sangue = "Traços (hematúria microscópica)"
            elif hemat == "macroscópica":
                sangue = "Positivo (hematúria macroscópica)"

            if truth.get("disuria") or truth.get("urgencia") or truth.get("polaciuria"):
                leucocitos = "5-30 /campo"
                nitrito = "Positivo"

            resultado = (
                "Exame: EAS (Urina tipo I)\n"
                "Aparência: Ligeiramente turva\n"
                "pH: 6.0\n"
                f"Leucócitos (microscopia): {leucocitos}\n"
                f"Nitrito: {nitrito}\n"
                f"Sangue: {sangue}\n"
                "Sedimentoscopia: bactérias presentes, hemácias conforme descrito acima.\n"
            )
        else:
            resultado = (
                "Exame: EAS (Urina tipo I)\n"
                "Resultado: Normal\n"
                "Nenhuma alteração significante ao exame de urina tipo I."
            )

    elif exame == "Urinocultura":
        if indication == "positiva":
            resultado = (
                "Exame: Urinocultura\n"
                "Crescimento: >10^5 UFC/mL\n"
                "Agente isolado: Escherichia coli\n"
                "Antibiograma (exemplo):\n"
                " - Nitrofurantoína: Sensível\n"
                " - Trimetoprim-sulfametoxazol: Sensível\n"
                " - Ciprofloxacino: Sensível\n"
            )
        else:
            resultado = (
                "Exame: Urinocultura\n"
                "Resultado: Sem crescimento bacteriano relevante.\n"
                "Interpretação: Sem bacteriúria significativa para cultura."
            )

    elif exame == "Ultrassom":
        if indication == "normal":
            resultado = (
                "Exame: Ultrassonografia de vias urinárias\n"
                "Achados: Rins com dimensões e morfologia preservadas. "
                "Sem dilatação do sistema coletor. Bexiga sem alterações focais relevantes.\n"
            )
        else:
            resultado = (
                "Exame: Ultrassonografia de vias urinárias\n"
                f"Achados: {indication}\n"
            )

    elif exame == "TC abdome":
        achados = []
        ind_text = str(indication).lower() if indication else ""

        if "cálculo" in ind_text or "ureteral" in ind_text:
            achados.append(
                "Imagem hiperdensa em topografia de ureter, compatível com cálculo ureteral, "
                "associada a discreta dilatação pielocalicial a montante."
            )

        if truth.get("hematúria") and truth.get("dor_lombar"):
            if not any("cálculo" in a.lower() for a in achados):
                achados.append(
                    "Sinais compatíveis com litíase: foco hiperdenso em ureter e hidronefrose discreta a montante."
                )

        if truth.get("febre") and truth.get("calafrios"):
            achados.append(
                "Rim com aumento discreto de volume e estriações do parênquima, sugestivas de processo inflamatório (compatível com pielonefrite)."
            )

        if truth.get("tabagismo") and truth.get("hematúria") == "macroscópica":
            achados.append(
                "Espessamento parietal irregular da bexiga, sugestivo de lesão expansiva (avaliação urológica recomendada)."
            )

        if not achados:
            resultado = (
                "Exame: TC de abdome/pelve\n"
                "Achados: Ausência de alterações tomográficas significativas."
            )
        else:
            resultado = "Exame: TC de abdome/pelve\nAchados:\n- " + "\n- ".join(achados) + "\n"

    else:
        resultado = f"Exame: {exame}\nResultado: {indication}"

       # Persistir resultado
    if "exam_results" not in st.session_state:
        st.session_state.exam_results = {}
    st.session_state.exam_results[exame] = resultado

    # log + score
    st.session_state.osce["exam_log"].append({"exam": exame, "pertinence": pertinence})
    st.session_state.osce["scores"]["exams"] = score_from_checklist("exams")

    # NÃO adicionar laudo no chat_history para não duplicar na anamnese.
    return resultado
    
# ----------------------------
# Funções: esperado e avaliação do exame físico
# ----------------------------
def build_expected_physical(case):
    """
    Gera lista de itens esperados para exame físico a partir de case["clinical_truth"].
    Retorna dict com chaves: 'required' (lista), 'suggested' (lista), 'not_relevant' (lista)
    """
    truth = case.get("clinical_truth", {})
    required = []
    suggested = []
    not_relevant = []

    # sinais gerais sempre relevantes
    required.append("aferir temperatura (°C)")
    required.append("avaliar sinais vitais (PA/FC)")

    # ITU / pielonefrite
    if truth.get("disuria") or truth.get("urgencia") or truth.get("polaciuria"):
        suggested.append("inspeção e palpação abdominal inferior")
        # se febre ou dor lombar -> checar Giordano
    if truth.get("dor_lombar") or truth.get("febre"):
        required.append("punho-percussão lombar (sinal de Giordano/CVA)")

    # hematúria / cólica renal
    if truth.get("hematúria") == "macroscópica" or truth.get("hematúria") == "microscópica":
        suggested.append("avaliar presença de dor à palpação renal")
        # se dor intensa -> avaliar sinais de cólica
    if truth.get("dor_lombar") and truth.get("irradia"):
        required.append("inspeção e palpação abdominal e avaliação de irradiação")

    # retenção urinária
    if truth.get("jato_fraco") or truth.get("esforco_miccional"):
        required.append("palpar bexiga / verificar distensão suprapúbica")
        suggested.append("avaliar residuo pós-miccional por US (se disponível)")

    # sinais gerais que costumam não ser necessários
    not_relevant.append("exame neurológico extenso (salvo sinais prévios)")
    not_relevant.append("exame ginecológico de rotina (não indicado salvo suspeita específica)")

    # dedupe
    return {
        "required": list(dict.fromkeys(required)),
        "suggested": list(dict.fromkeys(suggested)),
        "not_relevant": list(dict.fromkeys(not_relevant)),
    }

def evaluate_physical_exam(text, expected):
    """
    Avalia a descrição do aluno comparando palavras-chave.
    Retorna dict com: matched_required, missing_required, matched_suggested, extras, score, feedback_text.
    """
    t = (text or "").lower()

    # mapeamento heurístico de palavras-chave para cada item esperado
    keywords_map = {
        "aferir temperatura (°c)": ["temperatura", "febre", "°c", "aferir temperatura", "medir temperatura"],
        "avaliar sinais vitais (pa/fc)": ["pressão", "pa", "pressao", "fc", "frequência cardíaca", "frequencia cardiaca", "sinais vitais"],
        "punho-percussão lombar (sinal de giordano/cva)": ["giordano", "cva", "punho-percussão", "percussão lombar", "sinal de giordano"],
        "inspeção e palpação abdominal inferior": ["palpa", "palpação abdominal", "palpacao abdominal", "inspeção abdominal", "inspecionar abdome"],
        "palpar bexiga / verificar distensão suprapúbica": ["palpar bexiga", "distensão suprapúbica", "suprapúbica", "suprapubica", "bexiga distensa"],
        "avaliar residuo pós-miccional por us (se disponível)": ["residuo pós", "residuo pos", "resíduo pós-miccional", "residuo pós-miccional", "ultrassom", "us bexiga"],
        "avaliar presença de dor à palpação renal": ["palpação renal", "palpacao renal", "dor à palpação renal", "dor a palpacao renal"],
        "inspeção e palpação abdominal e avaliação de irradiação": ["irradia", "irradiação", "irradia para", "virilha", "palpação", "palpacao"],
    }

    # normalizar keys do expected para usar no mapeamento
    matched_required = []
    missing_required = []
    matched_suggested = []
    extras = []

    # verifica required
    for item in expected.get("required", []):
        key = item.lower()
        # heurística: match any keyword
        kws = keywords_map.get(key, [key.split()[0]])
        if any(k in t for k in kws):
            matched_required.append(item)
        else:
            missing_required.append(item)

    # verifica suggested
    for item in expected.get("suggested", []):
        key = item.lower()
        kws = keywords_map.get(key, [key.split()[0]])
        if any(k in t for k in kws):
            matched_suggested.append(item)

    # detecta termos possivelmente irrelevantes/extras (bate com 'not_relevant' ou palavras raras)
    for nr in expected.get("not_relevant", []):
        if nr.split()[0] and nr.split()[0].lower() in t:
            extras.append(nr)

    # pontuação simples: cada required vale 2 pontos, cada suggested 1; normalize to 0-10
    score_raw = 2 * len(matched_required) + 1 * len(matched_suggested)
    max_raw = 2 * max(1, len(expected.get("required", []))) + 1 * max(1, len(expected.get("suggested", [])))
    score = round((score_raw / max_raw) * 10, 1)

    feedback_lines = []
    feedback_lines.append(f"Pontos essenciais realizados: {len(matched_required)} / {len(expected.get('required', []))}.")
    if missing_required:
        feedback_lines.append("Faltou (essencial): " + "; ".join(missing_required) + ".")
    if matched_suggested:
        feedback_lines.append("Itens sugeridos realizados: " + "; ".join(matched_suggested) + ".")
    if extras:
        feedback_lines.append("Itens potencialmente desnecessários mencionados: " + "; ".join(extras) + ".")
    feedback_lines.append(f"Pontuação estimada: {score} / 10")

    return {
        "matched_required": matched_required,
        "missing_required": missing_required,
        "matched_suggested": matched_suggested,
        "extras": extras,
        "score": score,
        "feedback_text": "\n".join(feedback_lines)
    }
# ============================
# VALIDADOR DETERMINÍSTICO DE TRATAMENTO (regras básicas)
# ============================

TREATMENT_RULES = {
    "Cistite aguda não complicada": {
        "must_include_any": ["nitrofuranto", "fosfomic", "trimetoprim", "sulfametoxazol", "cefalo", "beta-lact"],
        "avoid_any": ["tc", "tomografia", "ciproflox", "quinolona"],
        "notes": "Opções usuais: nitrofurantoína 5 dias ou fosfomicina dose única (varia por protocolo local)."
    },
    "Pielonefrite aguda": {
        "must_include_any": ["antib", "cef", "ciproflox", "fluoroquin", "ampicil", "aminoglico"],
        "avoid_any": ["fosfomic", "dose única"],
        "notes": "Avaliar gravidade, necessidade de internação, cultura e reavaliação 48–72h."
    },
    "Cálculo ureteral distal <5 mm": {
        "must_include_any": ["analges", "aind", "anti-inflam", "hidrata", "tamsulos", "alfa-bloq"],
        "avoid_any": ["antibiótico", "antibiotico"],
        "notes": "Conservador se estável; orientar retorno e sinais de alarme."
    },
    "Cálculo ureteral >10 mm": {
        "must_include_any": ["urolog", "proced", "litotrips", "ureterosc", "cirurg"],
        "avoid_any": [],
        "notes": "Alta chance de não eliminação espontânea; discutir intervenção."
    },
    "Cólica renal com infecção associada": {
        "must_include_any": ["antib", "dren", "deriv", "nefrost", "duplo j", "urgên", "urgenc"],
        "avoid_any": ["alta", "casa", "ambulator"],
        "notes": "Obstrução + infecção = urgência urológica (drenagem + antibiótico)."
    },
    "Neoplasia de bexiga até prova em contrário": {
        "must_include_any": ["cistosc", "urolog", "investig", "encamin"],
        "avoid_any": ["tratar como infecção", "antibiótico por 7", "antibiotico por 7"],
        "notes": "Hematúria macroscópica indolor em tabagista: investigação urológica prioritária."
    },
    "Hematúria glomerular": {
        "must_include_any": ["nefro", "protein", "creatin", "pressão", "pa", "investig"],
        "avoid_any": ["cirurg", "cistoscopia imediata"],
        "notes": "Sinais nefríticos → linha nefrológica."
    },
    "Retenção urinária por HPB": {
        "must_include_any": ["sonda", "cateter", "alfa-bloq", "tamsulos", "finaster"],
        "avoid_any": [],
        "notes": "Desobstrução + terapia farmacológica e seguimento."
    }
}

def deterministic_treatment_score(correct_dx: str, student_tx: str):
    init_osce_scoring()
    tx = (student_tx or "").lower()

    rules = TREATMENT_RULES.get(correct_dx)
    if not rules:
        return 5.0, "Sem regra determinística cadastrada para este diagnóstico. Avaliação seguirá mais pela IA."

    must = rules.get("must_include_any", [])
    avoid = rules.get("avoid_any", [])
    notes = rules.get("notes", "")

    must_ok = any(m in tx for m in must) if must else True
    avoid_bad = any(a in tx for a in avoid) if avoid else False

    add_checklist("treatment", f"Incluiu elementos essenciais ({correct_dx})", must_ok, weight=3)
    add_checklist("treatment", f"Evitou condutas inadequadas ({correct_dx})", not avoid_bad, weight=3)

    score = score_from_checklist("treatment")

    feedback = []
    feedback.append(f"Score determinístico (tratamento): {score}/10")
    if not must_ok:
        feedback.append("Faltaram elementos essenciais para este diagnóstico.")
    if avoid_bad:
        feedback.append("Foram detectadas condutas potencialmente inadequadas para este diagnóstico.")
    if notes:
        feedback.append(f"Nota educacional: {notes}")

    return score, "\n".join(feedback)

if "selected_syndrome" not in st.session_state:
    st.session_state.selected_syndrome = None

if "selected_case" not in st.session_state:
    st.session_state.selected_case = None

if "exam_results" not in st.session_state:
    st.session_state.exam_results = {}

if "student_diagnosis" not in st.session_state:
    st.session_state.student_diagnosis = ""


# ========================
# CSS — TEMA HOSPITALAR
# ========================
st.markdown("""
<style>
    body, .stApp {
        background-color: #f1f5f9 !important;
        color: #1e293b !important;
        font-size: 18px !important;
    }
    .block-container {
        max-width: 900px;
        margin: auto !important;
        margin-top: 5vh !important;
        background-color: #ffffff !important;
        border-radius: 14px;
        padding: 30px 40px;
        box-shadow: 0 0 25px rgba(0,0,0,0.06);
    }
    h1, h2, h3 {
        color: #0ea5e9 !important;
        font-weight: 800 !important;
        text-align: center !important;
    }
    .stTextInput > div > div > input,
    .stSelectbox div[data-baseweb="select"] > div {
        background-color: #ffffff !important;
        color: #1e293b !important;
        border: 2px solid #38bdf8 !important;
        border-radius: 10px !important;
        font-size: 18px !important;
    }
    .stButton>button {
        background-color: #0ea5e9 !important;
        color: white !important;
        font-size: 20px !important;
        font-weight: 600 !important;
        border-radius: 12px !important;
        padding: 12px;
        width: 100%;
    }
    .chat-bubble-user {
        background-color: #bae6fd !important;
        border-left: 4px solid #0ea5e9 !important;
        padding: 12px !important;
        border-radius: 6px !important;
        margin-bottom: 10px;
        font-size: 18px !important;
    }
    .chat-bubble-ai {
        background-color: #e2e8f0 !important;
        border-left: 4px solid #38bdf8 !important;
        padding: 12px !important;
        border-radius: 6px !important;
        margin-bottom: 10px;
        font-size: 18px !important;
    }
</style>
""", unsafe_allow_html=True)

# ============================
# ESTADO GLOBAL
# ============================
if "screen" not in st.session_state:
    st.session_state.screen = "home"
# Inicialização segura de variáveis de sessão (evita AttributeError)
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "selected_syndrome" not in st.session_state:
    st.session_state.selected_syndrome = None

if "selected_case" not in st.session_state:
    st.session_state.selected_case = None

if "exam_results" not in st.session_state:
    st.session_state.exam_results = {}

if "student_diagnosis" not in st.session_state:
    st.session_state.student_diagnosis = ""

# feedbacks e textos usados nas telas — inicializar para evitar AttributeError
if "anamnesis_feedback" not in st.session_state:
    st.session_state.anamnesis_feedback = ""

if "diagnosis_feedback" not in st.session_state:
    st.session_state.diagnosis_feedback = ""

if "treatment_feedback" not in st.session_state:
    st.session_state.treatment_feedback = ""
if "student_physical_exam" not in st.session_state:
    st.session_state.student_physical_exam = ""

if "physical_exam_feedback" not in st.session_state:
    st.session_state.physical_exam_feedback = ""


if "initial_speech" not in st.session_state:
    st.session_state.initial_speech = ""

# ============================
# BANCO DE CASOS 
cases = {
# ============================
# ============================
# ITU
# ============================
"Infecção do trato urinário (ITU)": {

    "Caso 1": {
        "diagnosis": "Cistite aguda não complicada",
        "clinical_truth": {
"nome": "Maria Silva",
            "idade": 26,
            "sexo": "feminino",
            "disuria": True,
            "polaciuria": True,
            "urgencia": True,
            "febre": False,
            "dor_lombar": False,
            "hematúria": "microscópica"
        },
        "exam_indications": {
            "EAS": "alterado",
            "Urinocultura": "positiva",
            "Ultrassom": "normal",
            "TC abdome": "inadequado"
        },
        "red_flags": [],
        "teaching_point": "ITU baixa não complicada dispensa exames de imagem."
    },

    "Caso 2": {
        "diagnosis": "Pielonefrite aguda",
        "clinical_truth": {
"nome": "Ana Silva",
            "idade": 34,
            "sexo": "feminino",
            "disuria": True,
            "febre": True,
            "dor_lombar": True,
            "calafrios": True,
            "náuseas": True
        },
        "exam_indications": {
            "EAS": "alterado",
            "Urinocultura": "positiva",
            "Ultrassom": "normal",
            "TC abdome": "inadequado"
        },
        "red_flags": ["febre alta", "dor lombar", "toxemia"],
        "teaching_point": "Pielonefrite é diagnóstico clínico."
    },

    "Caso 3": {
        "diagnosis": "ITU recorrente por reinfecção",
        "clinical_truth": {
"nome": "Joana Souza",
            "idade": 41,
            "sexo": "feminino",
            "disuria": True,
            "episodios_ano": 4,
            "relacao_sexual": "associada"
        },
        "exam_indications": {
            "Urinocultura": "positiva",
            "Ultrassom": "normal",
            "TC abdome": "inadequado"
        },
        "red_flags": [],
        "teaching_point": "Reinfecção ≠ recidiva."
    }
},

# ============================
# CÓLICA RENAL
# ============================
"Cólica renal": {

    "Caso 1": {
        "diagnosis": "Cálculo ureteral distal <5 mm",
        "clinical_truth": {
"nome": "João Augusto",
            "idade": 37,
            "sexo": "masculino",
            "dor_lombar": True,
            "irradia": "virilha",
            "hematúria": "macroscópica",
            "febre": False
        },
        "exam_indications": {
            "TC abdome": "alterado",
            "Ultrassom": "hidronefrose leve",
            "EAS": "hematúria"
        },
        "red_flags": [],
        "teaching_point": "Cálculo pequeno tem alta chance de eliminação."
    },

    "Caso 2": {
        "diagnosis": "Cálculo ureteral >10 mm",
        "clinical_truth": {
"nome": "Cesar Lima",
            "idade": 55,
            "sexo": "masculino",
            "dor_intensa": True,
            "hematúria": "macroscópica",
            "febre": False
        },
        "exam_indications": {
            "TC abdome": "alterado",
            "Ultrassom": "hidronefrose moderada"
        },
        "red_flags": ["obstrução persistente"],
        "teaching_point": "Cálculos grandes dificilmente eliminam espontaneamente."
    },

    "Caso 3": {
        "diagnosis": "Cólica renal com infecção associada",
        "clinical_truth": {
"nome": "Gabriela Santana",
            "idade": 48,
            "sexo": "feminino",
            "dor_lombar": True,
            "febre": True,
            "calafrios": True
        },
        "exam_indications": {
            "TC abdome": "alterado",
            "EAS": "alterado",
            "Urinocultura": "positiva"
        },
        "red_flags": ["sepse urinária"],
        "teaching_point": "Obstrução + infecção = urgência."
    }
},

# ============================
# HEMATÚRIA
# ============================
"Hematúria": {

    "Caso 1": {
        "diagnosis": "Neoplasia de bexiga até prova em contrário",
        "clinical_truth": {
"nome": "Carlos Silva",
            "idade": 67,
            "sexo": "masculino",
            "hematúria": "macroscópica",
            "dor": False,
            "tabagismo": True
        },
        "exam_indications": {
            "Ultrassom": "massa vesical",
            "TC abdome": "alterado"
        },
        "red_flags": ["hematúria indolor"],
        "teaching_point": "Hematúria indolor é câncer até prova em contrário."
    },

    "Caso 2": {
        "diagnosis": "Hematúria por litíase",
        "clinical_truth": {
"nome": "Joaquim fernando",
            "idade": 42,
            "sexo": "masculino",
            "dor": True,
            "hematúria": "macroscópica"
        },
        "exam_indications": {
            "TC abdome": "cálculo ureteral"
        },
        "red_flags": [],
        "teaching_point": "Dor + hematúria sugere litíase."
    },

    "Caso 3": {
        "diagnosis": "Hematúria glomerular",
        "clinical_truth": {
"nome": "Nina Jesus",
            "idade": 39,
            "sexo": "feminino",
            "hematúria": "microscópica",
            "edema": True,
            "hipertensao": True
        },
        "exam_indications": {
            "EAS": "cilindros hemáticos",
            "Ultrassom": "normal"
        },
        "red_flags": ["síndrome nefrítica"],
        "teaching_point": "Hematúria glomerular não é cirúrgica."
    }
},

# ============================
# RETENÇÃO URINÁRIA
# ============================
"Retenção urinária": {

    "Caso 1": {
        "diagnosis": "Retenção urinária por HPB",
        "clinical_truth": {
"nome": "Jorge Silva",
            "idade": 72,
            "sexo": "masculino",
            "jato_fraco": True,
            "esforco_miccional": True,
            "nicturia": True
        },
        "exam_indications": {
            "Ultrassom": "resíduo pós-miccional elevado"
        },
        "red_flags": ["retenção aguda"],
        "teaching_point": "HPB é a principal causa de retenção no idoso."
    },

    "Caso 2": {
        "diagnosis": "Retenção urinária neurogênica",
        "clinical_truth": {
"nome": "Rute Melo",
            "idade": 58,
            "sexo": "feminino",
            "historia_AVC": True,
            "incontinencia": True
        },
        "exam_indications": {
            "Ultrassom": "bexiga distendida"
        },
        "red_flags": [],
        "teaching_point": "Causa neurológica deve ser lembrada."
    },

    "Caso 3": {
        "diagnosis": "Retenção urinária medicamentosa",
        "clinical_truth": {
"nome": "Gabriel Marques",
            "idade": 46,
            "sexo": "masculino",
            "uso_anticolinergico": True
        },
        "exam_indications": {
            "Ultrassom": "bexiga distendida"
        },
        "red_flags": [],
        "teaching_point": "Medicamentos podem causar retenção."
      }
    }
}
# ============================
# RUBRICA OSCE (CHECKLIST + GLOBAL RATING)
# ============================

OSCE_WEIGHTS = {
    "anamnesis": 0.25,
    "physical_exam": 0.15,
    "exams": 0.15,
    "diagnosis": 0.20,
    "treatment": 0.20,
    "communication": 0.05,
}

def init_osce_scoring():
    if "osce" not in st.session_state:
        st.session_state.osce = {
            "scores": {
                "anamnesis": 0.0,
                "physical_exam": 0.0,
                "exams": 0.0,
                "diagnosis": 0.0,
                "treatment": 0.0,
                "communication": 10.0,
            },
            "checklists": {
                "anamnesis": [],
                "physical_exam": [],
                "exams": [],
                "diagnosis": [],
                "treatment": [],
                "communication": [],
            },
            "flags": [],
        }

def weighted_total_score():
    init_osce_scoring()
    total = 0.0
    for k, w in OSCE_WEIGHTS.items():
        total += float(st.session_state.osce["scores"].get(k, 0.0)) * w
    return round(total, 2)

def add_checklist(domain: str, item: str, done: bool, weight: int = 1):
    init_osce_scoring()
    st.session_state.osce["checklists"][domain].append({
        "item": item,
        "done": bool(done),
        "weight": int(weight)
    })

def score_from_checklist(domain: str) -> float:
    init_osce_scoring()
    items = st.session_state.osce["checklists"].get(domain, [])
    if not items:
        return 0.0
    num = sum(i["weight"] for i in items if i["done"])
    den = sum(i["weight"] for i in items) or 1
    # normaliza 0-10
    return round((num / den) * 10.0, 1)
# ============================
# TELA 1 — HOME
# ============================
if st.session_state.screen == "home":

    st.markdown("<h1>V-OSCE Urologia</h1>", unsafe_allow_html=True)
    st.markdown("<p>Simulador clínico para treinamento prático.</p>", unsafe_allow_html=True)

    nome = st.text_input("Nome do aluno:")
    if st.button("Entrar"):
        if not nome.strip():
            st.error("Preencha seu nome.")
        else:
            st.session_state.student_name = nome
            st.session_state.screen = "select_syndrome"
            st.rerun()

# ============================
# TELA 2 — SELEÇÃO DA SÍNDROME
# ============================
elif st.session_state.screen == "select_syndrome":

    st.markdown("<h1>Selecione a síndrome</h1>", unsafe_allow_html=True)
    for syndrome in cases.keys():
        if st.button(syndrome, use_container_width=True):
            st.session_state.selected_syndrome = syndrome
            st.session_state.screen = "select_case"
            st.rerun()

    if st.button("Voltar"):
        st.session_state.screen = "home"
        st.rerun()

# ============================
# TELA 3 — SELEÇÃO DE CASO
# ============================
elif st.session_state.screen == "select_case":

    st.markdown(f"<h1>{st.session_state.selected_syndrome}</h1>", unsafe_allow_html=True)

    for c in cases[st.session_state.selected_syndrome].keys():
        if st.button(c, use_container_width=True):
            st.session_state.selected_case = c
            st.session_state.screen = "case_intro"
            st.rerun()

    if st.button("Voltar"):
        st.session_state.screen = "select_syndrome"
        st.rerun()

# ============================
# TELA 4 — INTRO
# ============================
elif st.session_state.screen == "case_intro":

    # Gera introdução padronizada baseada nos dados do caso (sem usar o modelo para evitar frases incoerentes)
    case = cases[st.session_state.selected_syndrome][st.session_state.selected_case]
    truth = case["clinical_truth"]

    idade = truth.get("idade", "idade não informada")
    sexo = truth.get("sexo", "")

    # Monta uma introdução curta e clara para o aluno ler
    intro_lines = []
    intro_lines.append(f"Paciente {idade} anos, {sexo}.")
    # se tivermos uma queixa principal explícita no caso, preferir; senão, montar a partir dos sinais
    queixas = []
    if truth.get("disuria"):
        queixas.append("disúria")
    if truth.get("polaciuria"):
        queixas.append("polaquiúria/poliúria")
    if truth.get("urgencia"):
        queixas.append("urgência miccional")
    if truth.get("dor_lombar"):
        queixas.append("dor lombar")
    if truth.get("hematúria"):
        queixas.append("hematúria")
    if queixas:
        intro_lines.append("Queixa principal: " + ", ".join(queixas) + ".")
    else:
        intro_lines.append("Queixa principal: sintomas urinários.")

    st.session_state.initial_speech = " ".join(intro_lines)

    st.success(st.session_state.initial_speech)

    if st.button("Iniciar anamnese"):
        st.session_state.chat_history = [("paciente", st.session_state.initial_speech)]
        # inicializa diagnóstico/progressão
        st.session_state.student_diagnosis = ""
        st.session_state.screen = "anamnesis"
        st.rerun()

# ============================
# TELA 5 — ANAMNESE
# ============================
elif st.session_state.screen == "anamnesis":

    # =========================
    # HISTÓRICO DA CONVERSA
    # =========================
    if st.session_state.get("exam_results"):
        st.markdown("**Resultados de exames solicitados:**")
        for ex, laudo in st.session_state.exam_results.items():
            laudo_html = str(laudo).replace("\n", "<br>")
            st.markdown(
                f"<div class='chat-bubble-ai'><b>Laudo ({ex}):</b><br>{laudo_html}</div>",
                unsafe_allow_html=True
            )

    for sender, msg in st.session_state.chat_history:
        if sender == "aluno":
            st.markdown(
                f"<div class='chat-bubble-user'><b>Você:</b> {msg}</div>",
                unsafe_allow_html=True
            )
        elif sender == "paciente":
            st.markdown(
                f"<div class='chat-bubble-ai'><b>Paciente:</b> {msg}</div>",
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"<div class='chat-bubble-ai'><b>Sistema:</b><pre style='white-space:pre-wrap'>{msg}</pre></div>",
                unsafe_allow_html=True
            )

    # =========================
    # INPUT DA PERGUNTA
    # =========================
    pergunta = st.text_input("Pergunta:", key="pergunta_atual")

    # =========================
    # ENVIAR PERGUNTA
    # =========================
    if st.button("Enviar"):
        if pergunta.strip():
            st.session_state.chat_history.append(("aluno", pergunta))

            # avalia postura/comunicação
            evaluate_communication_turn(pergunta)

            resposta = responder_como_paciente(pergunta)
            st.session_state.chat_history.append(("paciente", resposta))

            st.rerun()

    # =========================
    # NAVEGAÇÃO
    # =========================
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("Ir para exame físico"):
            st.session_state.screen = "physical_exam"
            st.rerun()
    with col2:
        if st.button("Solicitar exame"):
            st.session_state.screen = "exams"
            st.rerun()
    with col3:
        if st.button("Ir para diagnóstico"):
            st.session_state.screen = "diagnosis"
            st.rerun()

# ============================
# TELA 6 — EXAMES
# ============================
elif st.session_state.screen == "exams":

    st.markdown("<h1>Solicitação de exames</h1>", unsafe_allow_html=True)
    init_osce_scoring()

    case = cases[st.session_state.selected_syndrome][st.session_state.selected_case]

    exame = st.selectbox(
        "Selecione o exame:",
        list(case["exam_indications"].keys())
    )

    if st.button("Solicitar exame"):
        resultado = fornecer_resultado_exame(exame)
        st.info(resultado)

    st.markdown("---")

    if st.button("Voltar para anamnese"):
        st.session_state.screen = "anamnesis"
        st.rerun()

    if st.button("Ir para diagnóstico"):
        st.session_state.screen = "diagnosis"
        st.rerun()
# ============================
# TELA 7 — DIAGNÓSTICO + EPA
# ============================
# ============================
# TELA 7 — DIAGNÓSTICO + EPA
# ============================
elif st.session_state.screen == "diagnosis":

    prompt = f"""
Você é um avaliador clínico. Responda em português técnico, objetivo e estruturado.
Não utilize expressões informais.

Contexto (histórico da anamnese realizada pelo aluno):
{st.session_state.chat_history}

Forneça:
1) Resumo clínico objetivo (máx. 2 frases).
2) Nota de 0 a 10 para a anamnese.
3) Avaliação da coleta da queixa principal.
4) Pontos relevantes não explorados.
5) Avaliação da comunicação clínica.
6) Recomendações objetivas de melhoria (até 3 itens).

Utilize subtítulos claros.
"""

    gen = model.generate_content(prompt)
    st.session_state.anamnesis_feedback = gen.text.strip()

    st.info(st.session_state.anamnesis_feedback)

    dx = st.text_area("Seu diagnóstico:")

    if st.button("Enviar diagnóstico"):
        correct = cases[
            st.session_state.selected_syndrome
        ][
            st.session_state.selected_case
        ]["diagnosis"]

        st.session_state.student_diagnosis = dx

        prompt = f"""
Diagnóstico correto: {correct}
Diagnóstico do aluno: {dx}

Avalie:
- Correção diagnóstica
- Nota (0–10)
- Pontos fortes
- Pontos fracos
- Formulação diagnóstica ideal
"""
        gen = model.generate_content(prompt)
        st.session_state.diagnosis_feedback = gen.text.strip()
        st.session_state.screen = "treatment"
        st.rerun()
# ============================
# TELA X — EXAME FÍSICO
# ============================
elif st.session_state.screen == "physical_exam":

    st.markdown("<h1>Exame físico</h1>", unsafe_allow_html=True)

    st.markdown(
        "Descreva de forma objetiva **quais manobras você realizaria** e **o que avaliaria** no exame físico para este caso clínico. "
        "Liste apenas o que você considera pertinente para confirmar ou afastar hipóteses diagnósticas."
    )

    case = cases[st.session_state.selected_syndrome][st.session_state.selected_case]
    expected = build_expected_physical(case)

    exame_fisico = st.text_area(
        "Descreva o exame físico que faria (detalhe manobras):",
        height=200,
        key="input_physical"
    )

    if st.button("Enviar exame físico"):
        st.session_state.student_physical_exam = exame_fisico

        eval_res = evaluate_physical_exam(exame_fisico, expected)
        det_fb = eval_res["feedback_text"]

        # score determinístico no domínio "physical_exam"
        init_osce_scoring()
        st.session_state.osce["scores"]["physical_exam"] = float(eval_res["score"])

        # Complemento por IA: feedback clínico objetivo + o que faltou
        correct = cases[st.session_state.selected_syndrome][st.session_state.selected_case]["diagnosis"]
        prompt = f"""
Você é um preceptor avaliador de OSCE. Responda em português técnico, objetivo e prático.

Diagnóstico mais provável do caso (gabarito): {correct}

Exame físico descrito pelo aluno:
{exame_fisico}

Checklist do caso:
- Itens essenciais esperados: {expected.get("required", [])}
- Itens sugeridos: {expected.get("suggested", [])}
- Itens não relevantes: {expected.get("not_relevant", [])}

Com base nisso, forneça:
1) O que foi bom (máx 3 bullets)
2) O que faltou e por que importa (máx 3 bullets)
3) Um exemplo de exame físico ideal (máx 6 linhas)
Não use linguagem informal.
"""
        gen = model.generate_content(prompt)
        ai_fb = (getattr(gen, "text", "") or "").strip()

        st.session_state.physical_exam_feedback = det_fb + ("\n\n" + ai_fb if ai_fb else "")

        # registra no histórico (uma vez)
        st.session_state.chat_history.append(("aluno", f"[Exame físico] {exame_fisico}"))
        st.session_state.chat_history.append(("sistema", f"[Feedback exame físico]\n{st.session_state.physical_exam_feedback}"))

        st.success("Exame físico enviado com sucesso.")
        st.info(st.session_state.physical_exam_feedback)

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Voltar para anamnese"):
            st.session_state.screen = "anamnesis"
            st.rerun()
    with col2:
        if st.button("Prosseguir para solicitação de exames"):
            st.session_state.screen = "exams"
            st.rerun()
# ============================
# TELA 8 — TRATAMENTO
# ============================
elif st.session_state.screen == "treatment":

    st.markdown("<h1>Tratamento</h1>", unsafe_allow_html=True)
    st.caption("Agora proponha a conduta/terapêutica. (Ex.: antibiótico, analgesia, orientações e retorno.)")

    if st.session_state.get("diagnosis_feedback"):
        st.info(st.session_state.diagnosis_feedback)

    tx = st.text_area("Tratamento:", height=160, key="tx_input")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Voltar para diagnóstico"):
            st.session_state.screen = "diagnosis"
            st.rerun()

    with col2:
        if st.button("Enviar tratamento"):
            correct = cases[st.session_state.selected_syndrome][st.session_state.selected_case]["diagnosis"]

            # 1) score determinístico
            det_score, det_feedback = deterministic_treatment_score(correct, tx)
            init_osce_scoring()
            st.session_state.osce["scores"]["treatment"] = float(det_score)

            # 2) IA complementa (comentário técnico)
            prompt = f"""
Você é avaliador clínico. Responda em português técnico e objetivo.
Diagnóstico correto: {correct}
Tratamento proposto pelo aluno:
{tx}

Forneça:
- Adequação (conduta)
- Doses/duração (se mencionadas)
- Pontos fortes
- Pontos fracos
- Sugestão de tratamento ideal (resumo)
Sem linguagem informal.
"""
            gen = model.generate_content(prompt)
            ai_tx = (getattr(gen, "text", "") or "").strip()

            st.session_state.treatment_feedback = det_feedback + ("\n\n" + ai_tx if ai_tx else "")
            st.session_state.screen = "final_report"
            st.rerun()
# ============================
# TELA 9 — RELATÓRIO FINAL
# ============================
elif st.session_state.screen == "final_report":

    st.markdown("<h1>Relatório Final</h1>", unsafe_allow_html=True)
    init_osce_scoring()

    st.subheader("Score OSCE (ponderado)")
    st.write(f"**Total:** {weighted_total_score()} / 10")
    st.write("**Domínios:**", st.session_state.osce["scores"])
    st.info(communication_summary_text())

    st.markdown("---")

    st.write("### Avaliação da anamnese")
    st.info(st.session_state.get("anamnesis_feedback", ""))

    st.write("### Avaliação do exame físico")
    st.info(st.session_state.get("physical_exam_feedback", ""))

    st.write("### Avaliação do diagnóstico")
    st.info(st.session_state.get("diagnosis_feedback", ""))

    st.write("### Avaliação do tratamento")
    st.info(st.session_state.get("treatment_feedback", ""))

    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Voltar para anamnese"):
            st.session_state.screen = "anamnesis"
            st.rerun()

    with col2:
        if st.button("Voltar para tratamento"):
            st.session_state.screen = "treatment"
            st.rerun()

    with col3:
        if st.button("Escolher outro caso"):
            st.session_state.selected_case = None
            st.session_state.exam_results = {}
            st.session_state.chat_history = []
            st.session_state.anamnesis_feedback = ""
            st.session_state.diagnosis_feedback = ""
            st.session_state.treatment_feedback = ""
            st.session_state.physical_exam_feedback = ""
            st.session_state.student_diagnosis = ""
            st.session_state.student_physical_exam = ""
            st.session_state.screen = "select_case"
            st.rerun()

    if st.button("Voltar ao menu de síndromes"):
        st.session_state.selected_syndrome = None
        st.session_state.selected_case = None
        st.session_state.exam_results = {}
        st.session_state.chat_history = []
        st.session_state.anamnesis_feedback = ""
        st.session_state.diagnosis_feedback = ""
        st.session_state.treatment_feedback = ""
        st.session_state.physical_exam_feedback = ""
        st.session_state.student_diagnosis = ""
        st.session_state.student_physical_exam = ""
        st.session_state.screen = "select_syndrome"
        st.rerun()

    if st.button("Finalizar (reset geral)"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()














