import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_DIR = ROOT / "sim-stable" / "Equipamentos"
if str(DYNAMIC_DIR) not in sys.path:
    sys.path.insert(0, str(DYNAMIC_DIR))

import Classes as ClassesDinamicas  # noqa: E402
import Var_globais as GlobaisDinamicas  # noqa: E402


def test_arquivo_falhas_sim_descreve_perda_transitoria_de_strings():
    caminho = ROOT / "sim-stable" / "Arquivos_Temp_Json" / "Falhas_sim.json"
    eventos = json.loads(caminho.read_text(encoding="utf-8"))

    assert len(eventos) == 1
    assert eventos[0]["Tipo_Falha"] == "Perda_String_FV"
    assert eventos[0]["T_falha"] == [0.5]
    assert eventos[0]["duracao_falha"] == [0.25]
    assert eventos[0]["strings_perdidas"] == [4]


def test_perda_de_strings_ativa_e_restaura_no_tempo():
    painel = ClassesDinamicas.Painel_Fotovoltaico.__new__(ClassesDinamicas.Painel_Fotovoltaico)
    painel.id_pv = "PV_1"
    falhas = [{
        "Tipo_Falha": "Perda_String_FV",
        "id_pv": "PV_1",
        "T_falha": [0.5],
        "duracao_falha": [0.25],
        "strings_perdidas": [4],
    }]

    GlobaisDinamicas.Passo_global = 0.1
    GlobaisDinamicas.Passo_atual_global = 6
    assert painel._strings_perdidas_ativas([500, 16], falhas) == 4

    GlobaisDinamicas.Passo_atual_global = 8
    assert painel._strings_perdidas_ativas([500, 16], falhas) == 0
