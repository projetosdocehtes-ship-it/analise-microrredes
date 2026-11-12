import numpy as np
import json
import os

import Var_globais

# ----------------------------------------------
# Gerar dados da simulação
def numpy_to_python(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: numpy_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [numpy_to_python(v) for v in obj]

    return obj

def Exporta_Dados(Equipamentos):
    Time = np.linspace(0, Var_globais.T_sim_global, Var_globais.Num_Iteracao_global)

    inversor_total = Equipamentos.get("Inv_1")
    painel_total = Equipamentos.get("PV_1")
    bateria_total = Equipamentos.get("bat_1")    # None se a chave não existir
    barramento_total = Equipamentos.get("Bus_ac_1")
    carga_total = Equipamentos.get("Load_1")

    # Pegar os OBJETOS reais
    inversor = inversor_total["obj"] if inversor_total else None
    painel = painel_total["obj"] if painel_total else None
    bateria = bateria_total["obj"] if bateria_total else None 
    barramento = barramento_total["obj"] if barramento_total else None
    carga = carga_total["obj"] if carga_total else None

    Curva_V_DC, Curva_I_DC, Curva_P_DC = painel.Retornar_Val_Paineis()

    if inversor.Inversor_Param.Nm_fases > 1:
        # --- Figura 1: Tensões e Correntes de Linha ---
        (V_linhas, I_linhas, V_fases, I_fases) = inversor.Resgata_relacoes_trifasicas()
    else:
        V_linhas, I_linhas = inversor.Resgata_forma_onda_AC()

    Curva_P_Instantanea_AC, Curva_P_AC, Curva_S_AC, Curva_Q_AC = inversor.Resgata_Potencias_AC()
    Curva_V_RMS_AC, Curva_I_RMS_AC = inversor.Resgata_Val_RMS_AC()

    if bateria:
        V_BAT, I_BAT, P_BAT, SOC = bateria.Retornar_Val_Baterias()

    P_Demandada, Q_demandada = carga.Retornar_Val_Carga_demandada()


    resultado = {
        "Curva_T_simulacao": Time.tolist(),
        "Painel_PV": {
            "Curva_V_DC": numpy_to_python(Curva_V_DC),
            "Curva_I_DC": numpy_to_python(Curva_I_DC),
            "Curva_P_DC": numpy_to_python(Curva_P_DC),
        },
        "Inversor_AC": {
            "Curva_V_AC_linha": numpy_to_python(V_linhas),
            "Curva_I_AC_linha": numpy_to_python(I_linhas),
            "Curva_V_AC_fase": None,
            "Curva_I_AC_fase": None,
            "Curva_V_RMS_AC": numpy_to_python(Curva_V_RMS_AC),
            "Curva_I_RMS_AC": numpy_to_python(Curva_I_RMS_AC),
        },
        "Potencias_AC": {
            "Curva_P_Instantanea_AC": numpy_to_python(Curva_P_Instantanea_AC),
            "Curva_P_AC": numpy_to_python(Curva_P_AC),
            "Curva_S_AC": numpy_to_python(Curva_S_AC),
            "Curva_Q_AC": numpy_to_python(Curva_Q_AC),
        },
        "Baterias": {
            "V_BAT": None,
            "I_BAT": None,
            "P_BAT": None,
            "SOC": None
        },
        "Carga_Demandada": {
            "P_Demandada": numpy_to_python(P_Demandada),
            "Q_Demandada": numpy_to_python(Q_demandada)
        }
    }

    if inversor.Inversor_Param.Nm_fases > 1:
        resultado["Inversor_AC"].update({
            "Curva_V_AC_fase": numpy_to_python(V_fases),
            "Curva_I_AC_fase": numpy_to_python(I_fases)
        })

    if bateria:
        resultado["Baterias"].update({
            "V_BAT": numpy_to_python(V_BAT),
            "I_BAT": numpy_to_python(I_BAT),
            "P_BAT": numpy_to_python(P_BAT),
            "SOC": numpy_to_python(SOC)
        })

    # ----------------------------------------------
    # Definir o caminho do JSON de saída
    base_dir = os.getcwd()
    json_path = os.path.join(base_dir, "Arquivos_Temp_Json")

    output_dir = os.path.join(json_path, "Resultados_Simulacao")
    os.makedirs(output_dir, exist_ok=True)  # cria a pasta se não existir

    output_path = os.path.join(output_dir, "resultado.json")

    # ----------------------------------------------
    # Salvar como JSON
    with open(output_path, "w") as json_file:
        json.dump(resultado, json_file, indent=2)

    print(f"Resultados salvos em: {output_path}")
