import matplotlib.pyplot as plt
import numpy as np
import Var_globais

Time = np.linspace(0, Var_globais.T_sim_global, Var_globais.Num_Iteracao_global)

def Plot_Graficos(Lista_Graficos, Equipamentos):
    """
    Função para plotar diferentes grupos de gráficos do inversor,
    conforme solicitado em Lista_Graficos.
    
    Parâmetros:
    ------------
    Lista_Graficos : list of str
        Lista de strings definindo quais gráficos serão plotados.
        Ex: ["Val_DC", "Val_AC", "Pot_AC", "Val_RMS"]
    
    inversor : objeto
        Objeto do inversor que fornece os valores.
    """

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


    print(inversor.Protecoes_acionadas)

    # ----- 1) Tensão e Corrente DC -----
    if "Val_DC" in Lista_Graficos:
        Curva_V_DC, Curva_I_DC, Curva_P_DC = painel.Retornar_Val_Paineis()

        fig_DC = plt.figure(figsize=(10, 8))
        plt.subplot(3, 1, 1)
        plt.plot(Time, Curva_P_DC, label="Potência DC")
        plt.title('Potência dos Paineis - Por string', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Potência [W]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        # plt.xlim(0.0, 0.1)
        plt.grid(True)
        print("1.1")
        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()
        print("1.2")

        plt.subplot(3, 1, 2)
        plt.plot(Time, Curva_V_DC, label="Tensão DC")
        plt.title('Tensão dos Paineis - Por string', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Tensão [V]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        # plt.xlim(0.0, 0.1)
        # plt.ylim(425, 433)
        plt.grid(True)
        print("1.3")
        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()
        print("1.4")
        plt.subplot(3, 1, 3)
        plt.plot(Time, Curva_I_DC, label="Corrente DC")
        plt.title('Corrente dos Paineis - Por string', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Corrente [A]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        # plt.xlim(0.0, 0.1)
        plt.grid(True)
        print("1.5")
        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()
        print("1.6")
        plt.tight_layout()
        plt.show(block=False)

    # ----- 2) Tensão e Corrente AC -----
    if "Val_AC" in Lista_Graficos:

        if inversor.Inversor_Param.Nm_fases > 1:
            # --- Figura 1: Tensões e Correntes de Linha ---
            (V_linhas, I_linhas, V_fases, I_fases) = inversor.Resgata_relacoes_trifasicas()
            fig_linhas = plt.figure(figsize=(12, 8))

            # Tensões de linha
            plt.subplot(2, 1, 1)
            plt.plot(Time, V_linhas[0], label="V_L12")
            plt.plot(Time, V_linhas[1], label="V_L23")
            plt.plot(Time, V_linhas[2], label="V_L31")
            plt.title('Tensões de linha do inversor trifásico', fontsize=12)
            plt.xlabel('Tempo [s]')
            plt.ylabel('Tensão [V]')
            plt.grid(True)
            # for prot, passo in inversor.Protecoes_acionadas:
            #     tempo_acao = Var_globais.Passo_global * passo
            #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada")
            plt.legend()

            # Correntes de linha
            plt.subplot(2, 1, 2)
            plt.plot(Time, I_linhas[0], label="I_L1")
            plt.plot(Time, I_linhas[1], label="I_L2")
            plt.plot(Time, I_linhas[2], label="I_L3")
            plt.title('Correntes de linha do inversor trifásico', fontsize=12)
            plt.xlabel('Tempo [s]')
            plt.ylabel('Corrente [A]')
            plt.grid(True)
            # for prot, passo in inversor.Protecoes_acionadas:
            #     tempo_acao = Var_globais.Passo_global * passo
            #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada")
            plt.legend()

            plt.tight_layout()
            plt.show(block=False)


            # --- Figura 2: Tensões e Correntes de Fase ---
            fig_fases = plt.figure(figsize=(12, 8))

            # Tensões de fase
            plt.subplot(2, 1, 1)
            plt.plot(Time, V_fases[0], label="V_a")
            plt.plot(Time, V_fases[1], label="V_b")
            plt.plot(Time, V_fases[2], label="V_c")
            plt.title('Tensões de fase do inversor trifásico', fontsize=12)
            plt.xlabel('Tempo [s]')
            plt.ylabel('Tensão [V]')
            plt.grid(True)
            # for prot, passo in inversor.Protecoes_acionadas:
            #     tempo_acao = Var_globais.Passo_global * passo
            #     plt.axvline(x=tempo_acao, color='r', linestyle='--')
            plt.legend()

            # Correntes de fase
            plt.subplot(2, 1, 2)
            plt.plot(Time, I_fases[0], label="I_a")
            plt.plot(Time, I_fases[1], label="I_b")
            plt.plot(Time, I_fases[2], label="I_c")
            plt.title('Correntes de fase do inversor trifásico', fontsize=12)
            plt.xlabel('Tempo [s]')
            plt.ylabel('Corrente [A]')
            plt.grid(True)
            # for prot, passo in inversor.Protecoes_acionadas:
            #     tempo_acao = Var_globais.Passo_global * passo
            #     plt.axvline(x=tempo_acao, color='r', linestyle='--')
            plt.legend()

            plt.tight_layout()
            plt.show(block=False)
            
        else:
            Curva_V_AC, Curva_I_AC = inversor.Resgata_forma_onda_AC()

            fig_AC = plt.figure(figsize=(10, 8))
            plt.subplot(2, 1, 1)
            plt.plot(Time, Curva_V_AC, label="Tensão AC")
            plt.title('Tensão de saída do inversor', fontsize=12)
            plt.xlabel('Tempo [s]', fontsize=12)
            plt.xticks(fontsize=12)
            plt.yticks(fontsize=12)
            plt.grid(True)

            # for prot, passo in inversor.Protecoes_acionadas:
            #     tempo_acao = Var_globais.Passo_global * passo
            #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
            plt.legend()

            plt.subplot(2, 1, 2)
            plt.plot(Time, Curva_I_AC, label="Corrente AC")
            plt.title('Corrente de saída do inversor', fontsize=12)
            plt.xlabel('Tempo [s]', fontsize=12)
            plt.ylabel('Corrente [A]', fontsize=12)
            plt.xticks(fontsize=12)
            plt.yticks(fontsize=12)
            plt.grid(True)

            # for prot, passo in inversor.Protecoes_acionadas:
            #     tempo_acao = Var_globais.Passo_global * passo
            #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
            plt.legend()

            plt.tight_layout()
            plt.show(block=False)

    # ----- 3) Potências AC -----
    if "Pot_AC" in Lista_Graficos:
        Curva_P_Instantanea_AC, Curva_P_AC, Curva_S_AC, Curva_Q_AC = inversor.Resgata_Potencias_AC()

        fig_Pot = plt.figure(figsize=(10, 12))
        plt.subplot(4, 1, 1)
        plt.plot(Time, Curva_P_Instantanea_AC, label="Potência instantânea")
        plt.title('Potência instantânea', fontsize=12)
        plt.ylabel('P inst [W]', fontsize=12)
        plt.legend()
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(4, 1, 2)
        plt.plot(Time, Curva_P_AC, label="Potência Ativa")
        plt.title('Potência Ativa', fontsize=12)
        plt.ylabel('P Ativa [W]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(4, 1, 3)
        plt.plot(Time, Curva_S_AC, label="Potência Aparente")
        plt.title('Potência Aparente', fontsize=12)
        plt.ylabel('P Aparente [VA]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(4, 1, 4)
        plt.plot(Time, Curva_Q_AC, label="Potência Reativa")
        plt.title('Potência Reativa', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('P Reativa [VAr]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()
        
        plt.tight_layout()
        plt.show(block=False)

    # ----- 4) Tensão e Corrente RMS -----
    if "Val_RMS" in Lista_Graficos:
        Curva_V_RMS_AC, Curva_I_RMS_AC = inversor.Resgata_Val_RMS_AC()

        fig_RMS = plt.figure(figsize=(10, 8))
        plt.subplot(2, 1, 1)
        plt.plot(Time, Curva_V_RMS_AC, label="Tensão RMS AC")
        plt.title('Tensão RMS de saída do inversor', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Tensão RMS [V]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(2, 1, 2)
        plt.plot(Time, Curva_I_RMS_AC, label="Corrente RMS AC")
        plt.title('Corrente RMS de saída do inversor', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Corrente RMS [A]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.tight_layout()
        plt.show(block=False)

    # ----- 6) Val_Baterias -----
    if "Val_Baterias" in Lista_Graficos and bateria:
        V_BAT, I_BAT, P_Baterias, _, SOC = bateria.Retornar_Val_Baterias()

        fig_Baterias = plt.figure(figsize=(10, 8))
        plt.subplot(4, 1, 1)
        plt.plot(Time, V_BAT, label="Tensão das Baterias")
        plt.title('Tensão das Baterias', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Tensão [V]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(4, 1, 2)
        plt.plot(Time, I_BAT, label="Corrente das Baterias")
        plt.title('Corrente das Baterias', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Corrente [A]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(4, 1, 3)
        plt.plot(Time, P_Baterias, label="Potência das Baterias")
        plt.title('Potência das Baterias', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Potência [W]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(4, 1, 4)
        plt.plot(Time, SOC, label="Estado de carga")
        plt.title('Estado de Carga das Baterias', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('SOC', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.tight_layout()
        plt.show(block=False)

    # ----- 6) Fluxo Potencias -----
    if "Potencias" in Lista_Graficos:
        _, _, Pot_paineis = painel.Retornar_Val_Paineis()
        Pot_Demandada, _ = carga.Retornar_Val_Carga_demandada()

        if bateria:
            _, _, P_Baterias, _ = bateria.Retornar_Val_Baterias()
        else:
            P_Baterias = None

        fig_Potencias = plt.figure(figsize=(10, 8))
        plt.subplot(3, 1, 1)
        plt.plot(Time, Pot_paineis, label="Potência dos Paineis")
        plt.title('Potência dos paineis', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Potência [W]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()
        if P_Baterias is not None:
            plt.subplot(3, 1, 2)
            plt.plot(Time, P_Baterias, label="Potência das Baterias")
            plt.title('Potência das Baterias', fontsize=12)
            plt.xlabel('Tempo [s]', fontsize=12)
            plt.ylabel('Potência [W]', fontsize=12)
            plt.xticks(fontsize=12)
            plt.yticks(fontsize=12)
            plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
            # plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()

        plt.subplot(3, 1, 3)
        plt.plot(Time, Pot_Demandada, label="Potência Demandada")
        plt.title('Potência Demandada pela Carga', fontsize=12)
        plt.xlabel('Tempo [s]', fontsize=12)
        plt.ylabel('Potência [W]', fontsize=12)
        plt.xticks(fontsize=12)
        plt.yticks(fontsize=12)
        plt.grid(True)

        # for prot, passo in inversor.Protecoes_acionadas:
        #     tempo_acao = Var_globais.Passo_global * passo
        #     plt.axvline(x=tempo_acao, color='r', linestyle='--', label=f"{prot} acionada" )
        plt.legend()
        
        plt.tight_layout()
        plt.show(block=False)
    # Para garantir que tudo apareça:
    plt.pause(0.1)
    input("Pressione ENTER para fechar todos os gráficos...")