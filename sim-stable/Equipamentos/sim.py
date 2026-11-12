import numpy as np
import pandas as pd
import os
import matplotlib.pyplot as plt
import sys
import json

import Classes
import Var_globais

import Prints
import Exporta_valores

def resource_path(relative_path):
    """Retorna o caminho absoluto para o recurso, compatível com PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(base_path, relative_path))

def resource_path_external(relative_path):
    """Retorna o caminho absoluto para um recurso externo, baseado no diretório atual de execução."""
    base_path = os.getcwd()
    return os.path.abspath(os.path.join(base_path, relative_path))

# Carrega os dados do JSON (pasta paralela à Equipamentos).
# O arquivo de falhas pode ser separado de Entradas.json para facilitar
# cenários transitórios versionados.
json_path = resource_path_external(os.path.join("Arquivos_Temp_Json", "Entradas.json"))

with open(json_path, "r") as file:
    data = json.load(file)

# ------------------- Criando Objetos com base no JSON -------------------

Equipamentos = {}

if data["painel_info"]:
    for painel in data["painel_info"]:
        painel_id = painel["pv_id"]

        Equipamentos[painel_id] = {
            "obj": Classes.Painel_Fotovoltaico(
                painel["pv_id"],
                painel["fabricante_painel"],
                painel["modelo_painel"],
                painel["Pmp"],
                painel["Isc"],
                painel["Voc"],
                painel["Imp"],
                painel["Vmp"],
                painel["Uisc"],
                painel["Uvoc"],
                painel["Upmp"],
                painel["material_painel"],
                painel["eficiencia"]
            ),
            "quantidade": painel["quantidade"]
        }

if data["inversor_info"]:
    for inversor in data["inversor_info"]:
        inversor_id = inversor["inv_id"]

        Equipamentos[inversor_id] = {
            "obj": Classes.Inversor_DC_AC(
                inversor["inv_id"],
                inversor["Nm_MPPT"],
                inversor["In_Pmax"],
                inversor["Imax_MPPT"],
                inversor["In_Vnom"],
                inversor["In_Vmin"],
                inversor["In_Vmax"],
                inversor["In_MPP_Vmin"],
                inversor["In_MPP_Vmax"],
                inversor["Out_Pmax"],
                inversor["Out_Imax"],
                inversor["Out_VL_nom"],
                inversor["Out_Freq"],
                inversor["Eficiencia"],
                inversor["Max_THD"],
                inversor["Fator_pot"],
                inversor["Nm_fases"],
                inversor["smart"],
            ),
            "quantidade": inversor["quantidade"]
        }

if data["bateria_info"]:
    for bateria in data["bateria_info"]:
        bateria_id = bateria["bat_id"]

        Equipamentos[bateria_id] = {
            "obj": Classes.Stack_Baterias(
                bateria["bat_id"],
                bateria["fabricante_bateria"],
                bateria["modelo_bateria"],
                bateria["Tipo_bateria"],
                bateria["Capacidade"],
                bateria["I_charge_max"],
                bateria["I_discharge_max"],
                bateria["V_min"],
                bateria["V_max"],
                bateria["V_nom"],
                bateria["DoD"],
                bateria["Ciclo_vida"],
            ),
            "quantidade": bateria["quantidade"]
        }

if data["cargas_info"]:
    conectado_rede = data["conectado_rede"]

    for carga in data["cargas_info"]:
        carga_id = carga["carga_id"]

        Equipamentos[carga_id] = {
            "obj": Classes.Carga_ZIP(
                carga["carga_id"],
                carga["nome_carga"],
                carga["tipo_carga"],
                carga["curva_carga"],
                carga["s_instalada"],
                carga["fp"],
                carga["v_nom"],
                carga["f_rede"],
                conectado_rede
            ),
            "quantidade": carga["quantidade"]
        }

if data["barramento_info"]:
    for barramento in data["barramento_info"]:
        barramento_id = barramento["bus_id"]

        Equipamentos[barramento_id] = {
            "obj": Classes.Barramento(
                barramento["bus_id"],
                barramento["tipo"],
                barramento["fases"],
                barramento["V_linha_nominal"],
                barramento["V_fase_nominal"],
                barramento["V_min"],
                barramento["V_max"],
            ),
            "quantidade": 1
        }

# if data["rede_eletrica_info"]:
#     rede = data["rede_eletrica_info"][0]

#     Equipamentos["Rede_1"] = {
#         "obj": Classes.Rede_Eletrica(
#             rede["rede_id"], 
#             rede["fases"], 
#             rede["F_nominal"], 
#             rede["V_linha_nominal"], 
#             rede["V_fase_nominal"], 
#             rede["Harmonicos_amp"],
#             rede["Harmonicos_ordem"],
#             rede["Desbalanco_amp"]
#         ),
#         # Você pode adicionar outras chaves aqui, se necessário (ex: "quantidade": 1)
#     }

if data["Clima_Ambiente"]:
    clima = data["Clima_Ambiente"][0]
    
    # MODIFICAÇÃO AQUI: Envolver o objeto em um dicionário com a chave "obj"
    Equipamentos["Clima_Ambiente"] = {
        "obj": Classes.Clima_Ambiente(
            clima["clima_id"], 
            clima["nome_cidade"], 
            clima["pais"], 
            clima["data"]
        ),
        # Você pode adicionar outras chaves aqui, se necessário (ex: "quantidade": 1)
    }

if data.get("Config_Simulacao"):
    Config_Projeto = data["Config_Simulacao"][0]

Falhas_sim = data.get("Falhas_sim")
if Falhas_sim is None:
    falhas_path = data.get("Falhas_sim_arquivo", "Falhas_sim.json")
    candidatos_falhas = [
        resource_path_external(os.path.join("Arquivos_Temp_Json", falhas_path)),
        resource_path(os.path.join("..", "Arquivos_Temp_Json", falhas_path)),
    ]
    Falhas_sim = []
    for candidato in candidatos_falhas:
        if os.path.exists(candidato):
            with open(candidato, "r", encoding="utf-8") as arquivo_falhas:
                Falhas_sim = json.load(arquivo_falhas)
            break

if data.get("grafo_conexoes"):
    grafo_conexoes = data["grafo_conexoes"]
#------------------------------------------- Criando Projeto -------------------------------------------

Sistema_Fotovoltaico = Classes.Sistema_Eletrico(Equipamentos, Config_Projeto, Falhas_sim, grafo_conexoes)

#------------------------------------------- Simulando modelo -------------------------------------------
for i in range(Var_globais.Num_Iteracao_global):
    Sistema_Fotovoltaico.Simular_Sistema()
    Var_globais.Passo_atual_global = Var_globais.Passo_atual_global + 1

#------------------------------------------- Plotando os resultados dos valores DC -------------------------------------------

Exporta_valores.Exporta_Dados(Equipamentos)
print("chegou aqui")
# Lista_Graficos = ["Val_DC", "Val_AC", "Pot_AC", "Val_RMS", "Val_Baterias", "Potencias"]
Lista_Graficos = ["Val_DC", "Val_AC", "Pot_AC", "Val_RMS", "Potencias"]

Prints.Plot_Graficos(Lista_Graficos, Equipamentos)
print("finalizou")



# Time = np.linspace(0, Var_globais.T_sim_global, Var_globais.Num_Iteracao_global)

# plt.figure(figsize=(10, 8))

# # Gráfico 1: Tensões
# plt.subplot(3, 1, 1)
# plt.plot(Time, [Var_globais.V_REF_G]*len(Time), label='V_REF (220V)', linestyle='--', color='gray')
# plt.plot(Time, Var_globais.V_RMS_G, label='V_RMS', color='blue')
# plt.ylabel('Tensão (V)')
# plt.title('Tensões ao longo do tempo')
# plt.grid(True)
# plt.legend()

# # Gráfico 2: Erro
# plt.subplot(3, 1, 2)
# plt.plot(Time, Var_globais.ERRO_G, label='Erro', color='red')
# plt.ylabel('Erro (V)')
# plt.title('Erro ao longo do tempo')
# plt.grid(True)
# plt.legend()

# # Gráfico 3: MA (Modulação)
# plt.subplot(3, 1, 3)
# plt.plot(Time, Var_globais.MA_G, label='Índice de modulação (Ma)', color='green')
# plt.xlabel('Tempo (s)')
# plt.ylabel('Ma')
# plt.title('Índice de Modulação ao longo do tempo')
# plt.grid(True)
# plt.legend()

# plt.tight_layout()
# plt.show()
