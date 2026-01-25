import os
# dotenv é útil localmente, mas no Streamlit Cloud pode não estar instalado
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass  # se não existir, seguimos (no cloud usamos st.secrets ou variáveis de ambiente)

# prioriza Streamlit secrets, depois env var
API_KEY = None
try:
    API_KEY = st.secrets.get("GEMINI_API_KEY")
except Exception:
    API_KEY = None

if not API_KEY:
    API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    st.error("API Key do Gemini não encontrada. Configure GEMINI_API_KEY em Secrets (Streamlit) ou como variável de ambiente.")
    st.stop()

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

def responder_como_paciente(pergunta):
    """
    Responde como paciente de OSCE.
    - Respostas factuais (idade/nome/sexo) são retornadas a partir do caso (determinístico).
    - Perguntas narrativas são encaminhadas ao LLM, com 'truth' no prompt para evitar contradições.
    """
    # pega dados do caso (se houver)
    case = {}
    if st.session_state.selected_syndrome and st.session_state.selected_case:
        case = cases.get(st.session_state.selected_syndrome, {}).get(st.session_state.selected_case, {})
    truth = case.get("clinical_truth", {})

    q = pergunta.lower().strip()

    # Respostas determinísticas para fatos
    if any(k in q for k in ["nome", "como se chama", "seu nome", "chama-se"]):
        # se quiser nomes fixos, adicione "nome" em clinical_truth dos casos
        nome = truth.get("nome")
        if nome:
            return f"Meu nome é {nome}."
        return "Meu nome não foi informado."

    if "idade" in q or "quantos anos" in q:
        idade = truth.get("idade")
        if idade:
            return f"Tenho {idade} anos."
        return "Idade não informada."

    if any(k in q for k in ["sexo", "masculino", "feminino", "gênero"]):
        sexo = truth.get("sexo")
        if sexo:
            return f"Sou {sexo}."
        return "Sexo não informado."

    # Respostas sobre sintomas — use truth para manter coerência (se disponível)
    if any(k in q for k in ["dor", "queima", "queimar", "sente", "febre", "náusea", "vomito", "vômito", "urina"]):
        # passamos a truth ao modelo para mantê-lo coerente
        prompt = f"""
Você é um paciente em simulação clínica de OSCE. Responda de forma leiga e curta.
MANTENHA COERÊNCIA: os sintomas fixos do caso são: {truth}

Pergunta do aluno:
"{pergunta}"
Responda apenas como paciente (linguagem leiga), sem antecipar diagnóstico.
"""
        resp = model.generate_content(prompt)
        return resp.text.strip()

    # fallback: se não for fato nem sintoma, deixe o LLM responder com contexto (sem mudar facts)
    prompt = f"""
Você é um paciente em simulação clínica de OSCE. Informações padronizadas do caso: {truth}
Pergunta do aluno:
"{pergunta}"
Responda de forma leiga e NÃO altere fatos como idade, sexo ou sintomas.
"""
    resposta = model.generate_content(prompt)
    return resposta.text.strip()

def fornecer_resultado_exame(exame):
    """
    Gera um laudo template, consistente e determinístico, baseado no caso.
    Não usa a API para evitar saídas imprevisíveis.
    """
    case = cases[st.session_state.selected_syndrome][st.session_state.selected_case]
    truth = case["clinical_truth"]
    indications = case["exam_indications"]

    # se exame não indicado
    if exame not in indications:
        return "Exame não aplicável a este caso clínico."

    indication = indications[exame]

    # inaceitável / inadequado
    if indication == "inadequado":
        resultado = f"O exame solicitado ({exame}) não é indicado para este quadro clínico e não contribui para o diagnóstico."
    else:
        # Templates por exame
        if exame == "EAS":
            if indication in ["alterado", "hematúria"]:
                # EAS simplificado
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
                # Exemplo realista: E. coli sensível a XX
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

            # se exam_indications contém string específica, use-a como guia
            ind_text = str(indication).lower() if indication else ""

            # prioridade: indicação descritiva direta (ex: "cálculo ureteral")
            if "cálculo" in ind_text or "ureteral" in ind_text:
                achados.append(
                    "Imagem hiperdensa em topografia de ureter, compatível com cálculo ureteral, "
                    "associada a discreta dilatação pielocalicial a montante."
                )

            # sinais associados por truth
            if truth.get("hematúria") and truth.get("dor_lombar"):
                # só acrescenta se não duplicar info do caso
                if not any("cálculo" in a.lower() for a in achados):
                    achados.append(
                        "Sinais compatíveis com litíase: foco hiperdenso em ureter e hidronefrose discreta a montante."
                    )

            if truth.get("febre") and truth.get("calafrios"):
                achados.append(
                    "Rim com aumento discreto de volume e estriações do parênquima, sugestivas de processo inflamatório (compatible com pielonefrite)."
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
                resultado = (
                    "Exame: TC de abdome/pelve\n"
                    "Achados:\n- " + "\n- ".join(achados) + "\n"
                )

        else:
            # fallback
            resultado = f"Exame: {exame}\nResultado: {indication}"

    # Persistir resultado em session_state para não sumir ao navegar
    if "exam_results" not in st.session_state:
        st.session_state.exam_results = {}
    st.session_state.exam_results[exame] = resultado

    # também adiciona ao histórico de chat como mensagem de sistema/exame (permanece)
    st.session_state.chat_history.append(("exame", f"[Laudo - {exame}]\n{resultado}"))

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

def gerar_pdf(nome, sind, caso, epa, dx, tx):
    if FPDF is None:
        return None

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.multi_cell(0, 10, "Relatório Final - V-OSCE Urologia", align="C")
    pdf.ln(5)
    pdf.multi_cell(0, 8, f"Aluno: {nome}")
    pdf.multi_cell(0, 8, f"Síndrome: {sind}")
    pdf.multi_cell(0, 8, f"Caso: {caso}")
    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.multi_cell(0, 8, "Avaliação da Anamnese:")
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 7, epa)
    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.multi_cell(0, 8, "Avaliação do Diagnóstico:")
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 7, dx)
    pdf.ln(5)

    pdf.set_font("Arial", "B", 12)
    pdf.multi_cell(0, 8, "Avaliação do Tratamento:")
    pdf.set_font("Arial", size=12)
    pdf.multi_cell(0, 7, tx)

    path = "relatorio_vosce.pdf"
    pdf.output(path)
    return path

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

        # Mostrar resultados de exames solicitados (persistentes)
    if st.session_state.get("exam_results"):
        st.markdown("**Resultados de exames solicitados:**")
        for ex, laudo in st.session_state.exam_results.items():
            # converte quebras de linha em <br> para exibição vertical
            laudo_html = str(laudo).replace("\n", "<br>")
            st.markdown(
                f"<div class='chat-bubble-ai'><b>Laudo ({ex}):</b><br>{laudo_html}</div>",
                unsafe_allow_html=True
            )

    # depois renderizar o chat_history como já faz
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
        else:  # "exame" ou "sistema"
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
        if pergunta.strip() != "":
            # salva pergunta do aluno
            st.session_state.chat_history.append(("aluno", pergunta))

            # gera resposta do paciente OSCE
            resposta = responder_como_paciente(pergunta)

            # salva resposta do paciente
            st.session_state.chat_history.append(("paciente", resposta))

            st.rerun()

    # =========================
    # NAVEGAÇÃO
    # =========================
    col1, col2, col3 = st.columns([1,1,1])
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

    case = cases[
        st.session_state.selected_syndrome
    ][
        st.session_state.selected_case
    ]

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
        st.session_state.physical_exam_feedback = eval_res["feedback_text"]

        # registra no histórico
        st.session_state.chat_history.append(
            ("aluno", f"[Exame físico] {exame_fisico}")
        )
        st.session_state.chat_history.append(
            ("sistema", f"[Feedback exame físico]\n{st.session_state.physical_exam_feedback}")
        )

        st.success("Exame físico enviado com sucesso.")
        st.info(st.session_state.physical_exam_feedback)

    st.markdown("---")

    if st.button("Prosseguir para solicitação de exames"):
        st.session_state.screen = "exams"
        st.rerun()

# ============================
# TELA 8 — TRATAMENTO
# ============================
elif st.session_state.screen == "treatment":

    st.info(st.session_state.diagnosis_feedback)

    tx = st.text_area("Tratamento:")

    if st.button("Enviar"):
        prompt = f"""
        Avalie o tratamento proposto.
        Tratamento: {tx}
        Síndrome: {st.session_state.selected_syndrome}
        Caso: {st.session_state.selected_case}

        Avaliar:
        - Adequação
        - Dose
        - Duração
        - Pontos fortes
        - Pontos fracos
        - Nota 0 a 10
        - Tratamento ideal
        """
        gen = model.generate_content(prompt)

        st.session_state.treatment_feedback = gen.text.strip()
        st.session_state.screen = "final_report"
        st.rerun()


# ============================
# TELA 9 — RELATÓRIO FINAL
# ============================
elif st.session_state.screen == "final_report":

    st.markdown("<h1>Relatório Final</h1>", unsafe_allow_html=True)

    st.write("### Avaliação da anamnese")
    st.info(st.session_state.anamnesis_feedback)

    st.write("### Avaliação do exame físico")
    st.info(st.session_state.physical_exam_feedback)

    st.write("### Avaliação do diagnóstico")
    st.info(st.session_state.diagnosis_feedback)

    st.write("### Avaliação do tratamento")
    st.info(st.session_state.treatment_feedback)

    # PDF (apenas se FPDF disponível)
    if FPDF is None:
        st.warning("Biblioteca FPDF não instalada. PDF indisponível.")
    else:
        file = gerar_pdf(
            st.session_state.student_name,
            st.session_state.selected_syndrome,
            st.session_state.selected_case,
            st.session_state.anamnesis_feedback,
            st.session_state.diagnosis_feedback,
            st.session_state.treatment_feedback
        )

        if file:
            with open(file, "rb") as f:
                st.download_button(
                    "Baixar PDF",
                    f,
                    file_name="relatorio_vosce.pdf"
                )

    # navegação final
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Voltar para anamnese"):
            st.session_state.screen = "anamnesis"
            st.rerun()
    with col2:
        if st.button("Voltar para tratamento"):
            st.session_state.screen = "treatment"
            st.rerun()

    if st.button("Finalizar"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

