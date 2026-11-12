import numpy as np
import requests
import math
import json
from scipy.interpolate import interp1d
from scipy.integrate import solve_ivp
from collections import deque

import Var_globais

# ================================================================== Próximos passos ==================================================================
# 1 - Ver como o sistema entregará pot reativa caso o sistema seja offgrid ( quando o FP da carga é diferente de 1)
# 2 - Erro quando fator de potência é >= 1
# 3 - Bateria está sendo simulada mesma quando não temos ela

# 4 - Fazer pelo numero de fases
# 4 - Melhorar sistema de filtro, normalmente usa-se "LCL" ou "LC"
# 4 - Ver como gerar quantidade de harmonicos de acordo com o datasheet (Amplitude cresce junto com MA)
# 4 - Implementar falhas e perturbações para análise de estabilidade transiente
# 4 - Nenhuma das falhas terá auto-reset
# ----------------------------------------------------------- Classe do Sistema -----------------------------------------------------------
class Sistema_Eletrico:
  def __init__(self, Equipamentos, Config_Projeto, Falhas, grafo_conexoes):
    self.mudanca_ambiental, self.falhas_carga, self.falhas_paineis, self.falhas_inversor = self.classificar_falhas(Falhas)
    self.equipamentos = Equipamentos
    self.config = Config_Projeto
    self.grafo = {}
    
    self.gerar_grafo(grafo_conexoes)

    self.agente_MQTT = Agente_Mensagem()
    self.topicos_equipamentos = self.agente_MQTT.criar_topicos_por_topologia( self.grafo, self.equipamentos )
    self.agrupar_equipamentos_por_tipo()

  def Simular_Sistema(self):
    if Var_globais.Passo_atual_global == 2:
      # self.debug_inscricao()
      # print(self.equipamentos)
      pass

    if self.clima_obj:
      self.clima_obj.Simular_Clima(self.mudanca_ambiental, self.agente_MQTT)

    for painel_obj, painel_id, quantidade in self.paineis:
      painel_obj.Simular_equipamento(quantidade, self.falhas_paineis, self.agente_MQTT)

    for bateria_obj, bateria_id, quantidade in self.baterias:
      bateria_obj.Simular_equipamento(quantidade, self.agente_MQTT)

    for carga_obj, carga_id, quantidade in self.cargas:
      carga_obj.Simular_equipamento(self.falhas_carga, self.agente_MQTT)

    self.agente_MQTT.entrega_msg()

    for inversor_obj, inversor_id, quantidade in self.inversores:
      inversor_obj.Simular_equipamento(self.falhas_inversor, self.agente_MQTT)
    
    self.agente_MQTT.entrega_msg()

    for barramento_obj, inversor_id, quantidade in self.barramento:
      barramento_obj.Simular_barramento(self.agente_MQTT)

    self.agente_MQTT.entrega_msg()

  def gerar_grafo(self, grafo_conexoes):
    for conexoes in grafo_conexoes:
      a, b = conexoes["between"]

      self.grafo.setdefault(a, []).append(b)
      self.grafo.setdefault(b, []).append(a)

  def agrupar_equipamentos_por_tipo(self):

    self.paineis = []
    self.inversores = []
    self.baterias = []
    self.cargas = []
    self.clima = []
    self.barramento = []

    mapear_classe_para_lista = {
      "Painel_Fotovoltaico": self.paineis,
      "Inversor_DC_AC": self.inversores,
      "Stack_Baterias": self.baterias,
      "Carga_ZIP": self.cargas,
      "Clima_Ambiente": self.clima,
      "Barramento": self.barramento
    }

    for equ_id, info in self.equipamentos.items():
      equipamento_obj = info["obj"]
      nome_classe = type(equipamento_obj).__name__

      lista_destino = mapear_classe_para_lista.get(nome_classe)

      if lista_destino is not None:

        if nome_classe == "Clima_Ambiente":
          # Clima deve ir SÓ o objeto
          lista_destino.append(equipamento_obj)
        else:
          # Para os demais equipamentos
          lista_destino.append((equipamento_obj, equ_id, info["quantidade"]))

    # Trata o clima separadamente
    if self.clima and len(self.clima) == 1:
      self.clima_obj = self.clima[0]
    elif self.clima:
      print("Aviso: Mais de um objeto de Clima Ambiente encontrado. Usando apenas o primeiro.")
      self.clima_obj = self.clima[0]
    else:
      self.clima_obj = None

  def debug_inscricao(self):
    # 3. Impressão de Debug para verificar as inscrições
    print("--- ⚙️ Debug de Inscrições de Tópicos ---")
    
    # O agente_MQTT tem a lista de inscritos em self.subscribers
    subscribers = self.agente_MQTT.subscribers
    
    # Itera sobre os tópicos existentes
    for topic, agents in subscribers.items():
        print(f"\n📢 Tópico: **{topic}**")
        print("   Inscritos:")
        # Itera sobre os agentes inscritos no tópico
        for agent in agents:
            # Tenta obter o ID do equipamento que o objeto representa para um output mais claro
            agent_id = next(
                (
                    eq_id for eq_id, info in self.equipamentos.items() 
                    if info["obj"] is agent
                ),
                "Agente Desconhecido"
            )
            print(f"   - {agent_id} (Classe: {type(agent).__name__})")
    
  def classificar_falhas(self, Falhas_sim):
      mudanca_ambiental = []
      falhas_carga = []
      falhas_paineis = []
      falhas_inversor = []

      for falha in Falhas_sim:
        T_falha = falha.get("T_falha", [])
        if isinstance(T_falha, list) and len(T_falha) > 0:
          tipo = falha.get("Tipo_Falha")
          if tipo in ["Mudanca_Irradiancia", "Mudanca_Temperatura"]:
            mudanca_ambiental.append(falha)
          elif tipo == "Mudanca_Carga":
            falhas_carga.append(falha)
          elif tipo == "Perda_String_FV":
            falhas_paineis.append(falha)
          elif tipo == "Curto_Circuito_CC":
            falhas_inversor.append(falha)

      return mudanca_ambiental, falhas_carga, falhas_paineis, falhas_inversor
  
# ----------------------------------------------------------- Classes dos paineis -----------------------------------------------------------
class Painel_Fotovoltaico:
  def __init__(self, id_pv, fabricante_painel, modelo_painel, Pmp, Isc, Voc, Imp, Vmp, Uisc, Uvoc, Upmp, material_painel, eficiencia):
    self.PV_Param = self.Param_Painel_Fotovoltaico(id_pv, fabricante_painel, modelo_painel, Pmp, Isc, Voc, Imp, Vmp, Uisc, Uvoc, Upmp, material_painel, eficiencia)
    self.id_pv = self.PV_Param.Retorna_id()

    self.Lista_V = []
    self.Lista_I = []
    self.Lista_P = []

    self.clima_atual = {"T": 25, "G": 1000}
    self.vref_inversor = None
    self.vmppt_init = Vmp
    # self.vref_inversor = 816
    
    self.Painel_simulado = None

  def receive(self, origem, tipo_origem, topico, mensagem):
    """
    mensagem é sempre:
    {
      "PV_1": {"valor": ...},
      "PV_2": {"valor": ...}
    }
    """
    # Dados climáticos
    if topico == "dados_climaticos":
      _, dados = next(iter(mensagem.items()))
      self.clima_atual["T"] = dados.get("T")
      self.clima_atual["G"] = dados.get("G")
      return

    # Saída MPPT do inversor
    if topico == "saida_mppt":
      if self.id_pv in mensagem:
        dados = mensagem[self.id_pv]
        self.vref_inversor = dados.get("V_mppt")
      return

  def Simular_equipamento(self, Nm_paineis, falhas_paineis, agente_MQTT):
    # 1️⃣ Criar a Simulação do painel no primeiro passo
    if Var_globais.Passo_atual_global == 0:
      self.Painel_simulado = self.Simulacao_painel( self.PV_Param, Nm_paineis )
      self.vref_inversor = self.vmppt_init * Nm_paineis[0]

    if Var_globais.Passo_atual_global <= 1:
      print(f"Painel -- Temp = {self.clima_atual["T"]}")
      print(f"Painel -- irrad = {self.clima_atual["G"]}")
      print(f"Painel -- Vmppt = {self.vref_inversor}")

    # 3️⃣ Rodar a simulação de PV
    V_pv, I_pv, P_pv = self.Painel_simulado.Simula_PV( self.clima_atual, falhas_paineis, self.vref_inversor )

    # 4️⃣ Multiplicar pela quantidade de strings disponíveis.
    strings_perdidas = self._strings_perdidas_ativas(Nm_paineis, falhas_paineis)
    strings_disponiveis = max(int(Nm_paineis[1]) - strings_perdidas, 0)
    V_total = V_pv * Nm_paineis[0]
    I_total = I_pv * strings_disponiveis
    P_total = P_pv * Nm_paineis[0] * strings_disponiveis
    self.Armazenar_Val_Paineis(V_total, I_total, P_total)
    
    # 5️⃣ Publicar os valores
    agente_MQTT.publicar_msg( f"{self.id_pv}/medicoes_pv", { self.id_pv: {"V_pv": V_total, "I_pv": I_total, "P_pv": P_total}})
    msg = { self.id_pv: {"V_pv": V_total, "I_pv": I_total, "P_pv": P_total}} # monta a mensagem com as tensões por entrada mppt

  def _strings_perdidas_ativas(self, Nm_paineis, falhas_paineis):
    """Retorna quantas strings do PV estão indisponíveis no instante atual."""
    tempo_atual = Var_globais.Passo_global * Var_globais.Passo_atual_global
    strings_perdidas = 0
    for falha in falhas_paineis or []:
      if falha.get("Tipo_Falha") != "Perda_String_FV":
        continue
      if falha.get("id_pv") not in (None, self.id_pv):
        continue
      tempos = falha.get("T_falha", [])
      duracoes = falha.get("duracao_falha", [])
      perdas = falha.get("strings_perdidas", [])
      if not isinstance(tempos, list):
        tempos = [tempos]
      if not isinstance(duracoes, list):
        duracoes = [duracoes]
      if not isinstance(perdas, list):
        perdas = [perdas]
      for indice, inicio in enumerate(tempos):
        duracao = duracoes[indice] if indice < len(duracoes) else None
        ativo = tempo_atual >= float(inicio) and (duracao is None or tempo_atual < float(inicio) + float(duracao))
        if ativo:
          strings_perdidas += int(perdas[indice] if indice < len(perdas) else 0)
    return min(max(strings_perdidas, 0), int(Nm_paineis[1]))

  def Armazenar_Val_Paineis(self, V_DC, I_DC, P_DC):
    self.Lista_V.append(V_DC)
    self.Lista_I.append(I_DC)
    self.Lista_P.append(P_DC)

  def Retornar_Val_Paineis(self):
    return self.Lista_V, self.Lista_I, self.Lista_P

  class Param_Painel_Fotovoltaico:
    def __init__(self, id_pv, fabricante_painel, modelo_painel, Pmp, Isc, Voc, Imp, Vmp, Uisc, Uvoc, Upmp, material_painel, eficiencia):
      self.id_pv = id_pv

      self.fabricante = fabricante_painel
      self.modelo = modelo_painel
      self.nome = fabricante_painel + "-" + modelo_painel
      self.Pmp = Pmp      # Potência Max do painel ok
      self.Isc = Isc      # Corrente de curto circuito ok
      self.Voc = Voc      # Tensão de circuito aberto ok
      self.Imp = Imp      # Corrente de maxima potência ok
      self.Vmp = Vmp      # Tensão de maxima potência ok
      self.Uisc = Uisc    # Coeficiente de temperatura de corrente
      self.Uvoc = Uvoc    # Coeficiente de temperatura de tensão
      self.Upmp = Upmp    # Coeficiente de temperatura de potência

      if material_painel == "Silicio": #ok
        self.Cs = 0.11175
        self.Csh = 34.49692
      elif material_painel == "HIT":
        self.Cs = 0.16129000
        self.Csh = 124.48114

      self.Rsho = self.Csh * (self.Voc / self.Isc)   #Eq 21
      self.Rso = self.Cs * (self.Voc / self.Isc)     #Eq 21
      self.T_STC_C = 25
      self.T_STC_K = self.T_STC_C + 273.15
      self.G_STC = 1000
      self.eficiencia = eficiencia  # Eficiência

      self.Rsh = 0
      self.Rs  = 0
      self.Io  = 0
      self.IL  = 0
      self.nT  = 0
      self.n   = 0

      Perda_sombreamento = 0
      Perda_mismatch = 0.02

      self.Perdas_Painel = Perda_sombreamento + Perda_mismatch

      self.Calcular_Parametros_painel()

    def Retorna_id(self):
      return self.id_pv

    def Retorna_Parametros_Calculados(self):
      return self.Rsh, self.Rs, self.Io, self.IL, self.nT, self.n

    def Retorna_Parametros_Datasheet(self):
      return self.Vmp, self.Pmp, self.Isc, self.Voc, self.Uisc, self.Uvoc, self.Upmp

    def Retorna_perdas(self):
      return self.Perdas_Painel

    def Normalizar_Parametros(self):
      Vrange = self.Voc
      Irange = self.Isc
      Voc_norm = self.Voc / Vrange
      Isc_norm = self.Isc / Irange
      Vmp_norm = self.Vmp / Vrange
      Imp_norm = self.Imp / Irange
      Rsho_norm = self.Rsho / Vrange * Irange
      Rso_norm = self.Rso / Vrange * Irange
      return Voc_norm, Isc_norm, Vmp_norm, Imp_norm, Rsho_norm, Rso_norm

    def sgn(self, x):
      if x > 0:
          return 1
      elif x < 0:
          return -1
      else:
          return 0

    def Calcular_Parametros_painel(self):
      Accuracy = 0.00001
      Rs = 0.01
      Step = 0.001
      Sign1 = 1
      Diff = Accuracy + 1

      Voc, Isc, Vmp, Imp, Rsho, Rso = self.Normalizar_Parametros()

      while 1:
          nT = (Vmp + Imp*Rs - Voc) / np.log(((Isc - Imp)*Rsho - (Vmp + Imp*Rs)) / (Isc*Rsho - Voc))
          Io = (Isc - Voc / Rsho) / (np.exp(Voc/nT) - 1)
          Diff = (Io / nT * np.exp(Voc/nT) + 1 / Rsho) / (1 + Rs * (Io / nT*np.exp(Voc/nT) + 1 / Rsho)) - 1 / Rso

          if abs(Diff) <= Accuracy:
              break
          Sign2 = self.sgn(Diff)
          if Sign1 != Sign2:  # Verifica se x1 é diferente de x2
              Step = -Step / 3
          Rs = Rs + Step
          Sign1 = Sign2

      self.Rsh = self.Rsho
      self.Rs = Rs * self.Voc / self.Isc
      self.Io = Io * self.Isc
      self.IL = self.Isc
      self.nT = nT * self.Voc
      self.n = nT / self.T_STC_K    #Diode Quality Factor

      return 0

  class Simulacao_painel:
    def __init__(self, Painel, Nm_paineis):
      self.Rsh, self.Rs, self.Io, self.IL, self.nT, self.n = Painel.Retorna_Parametros_Calculados()
      self.Vmp, self.Pmp, self.Isc, self.Voc, self.Uisc, self.Uvoc, self.Upmp = Painel.Retorna_Parametros_Datasheet()
      self.perdas = Painel.Retorna_perdas()

      # Parâmetros de simulação
      self.V_MPPT = self.Voc / 6
      self.G_antigo = 1000

      # Série / Paralelo
      self.Nm_PV_serie = Nm_paineis[0]
      self.Nm_PV_paralelo = Nm_paineis[1]

    def Simula_PV(self, clima_atual, falhas_paineis, vref_inversor):
      if self.V_MPPT == 0:    # --- OK
        self.V_MPPT = self.Voc / 6    # --- OK
      
      if Var_globais.Passo_atual_global < 5:
        vref_inversor = self.Vmp * self.Nm_PV_serie

      # print(vref_inversor)
      T = clima_atual["T"]    # --- OK
      G = clima_atual["G"]    # --- OK

      IL_GT, Io_GT, _ = self.Calcula_Param_auxiliares(T, G)    # --- OK

      I_init = self.Isc / 2    # --- OK
      I_calc = self.Newton_Raphson_Corrente(self.V_MPPT, I_init, IL_GT, Io_GT)

      if G != self.G_antigo:    # --- OK
        self.V_MPPT = self.Voc / 6    # --- OK

      if Var_globais.Passo_atual_global != 0:
        if vref_inversor == "Voc":
          self.V_MPPT = self.Voc
        else:
          self.V_MPPT = vref_inversor / self.Nm_PV_serie

      Pot_MPPT = self.V_MPPT * I_calc

      # print(f"V_MPPT = {self.V_MPPT}, I = {I_calc}, P = {Pot_MPPT}")

      Pot_c_perdas, I_c_perdas = self.Perdas_Painel(Pot_MPPT, self.V_MPPT)

      self.G_antigo = G
      # print(f"I = {I_calc}, V = {self.V_MPPT}, P = {Pot_MPPT}")

      return self.V_MPPT, I_c_perdas, Pot_c_perdas

    def Calcula_Param_auxiliares(self, T_sim, G_sim):
      C1 = 5.468511e-2
      C2 = 5.973869e-3
      C3 = 7.616178e-4
      T_STC_C = 25
      G_STC = 1000

      T_sim_K = T_sim + 273.15
      nT_sim = (T_sim + 273.15)*self.n
      if G_sim <= 0:
        G_sim = 1e-4
      aG = G_sim / G_STC  # Irradiância relativa

      IL_T = self.Isc + self.Uisc * (T_sim - T_STC_C)  # Corrente de curto-circuito ajustada # Foi alterada da formula do artigo
      IL_GT = IL_T * aG  # Corrente de curto-circuito com irradiância
      Voc_GT = self.Voc * (1 + C1*np.log(aG) + C2*np.log(aG)**2 + C3*np.log(aG)**3)  + self.Uvoc * (T_sim - T_STC_C)
      Io_GT = aG * ((IL_T - (Voc_GT / self.Rsh)) / (np.exp(Voc_GT / self.nT) - 1))  # Corrente de saturação ajustada

      return IL_GT, Io_GT, Voc_GT

    def Newton_Raphson_Corrente(self, V_init, I_init, IL, Io):
      for _ in range(100):
          exp_term = np.exp((V_init + I_init * self.Rs) / self.nT)
          f = IL - Io * (exp_term - 1) - (V_init + I_init * self.Rs) / self.Rsh - I_init
          df = -Io * (self.Rs / self.nT) * exp_term - self.Rs / self.Rsh - 1          # Derivada da função
          I_new = I_init - f / df

          if np.abs(I_new - I_init) < 1e-6:
              if I_new < 0:
                  return 0
              else:
                return I_new
          I_init = I_new          # Atualizar corrente para próxima iteração
      return max(I_init, 0)

    def Gerar_curva_IV(self, T_sim, G_sim):
      IL_GT, Io_GT, Voc_GT = self.Calcula_Param_auxiliares(T_sim, G_sim)
      V_array= np.linspace(0, Voc_GT, 10000)  # Vd_max variando de 0 até Voc_GT com 10000 pontos
      I_init = self.Isc / 2
      I_array = []
      for V_init in V_array:  # Limite de iterações
        I = self.Newton_Raphson_Corrente(V_init, I_init, IL_GT, Io_GT)
        I_array.append(I)

      return V_array, I_array

    def Perdas_Painel(self, Potencia, Tensao):
      if Tensao == 0:
        Tensao = 1e-8

      Potencia_perdas =  Potencia * (1 - self.perdas)
      Corrente_perdas = Potencia_perdas / Tensao
      return Potencia_perdas, Corrente_perdas

# ----------------------------------------------------------- Classes do inversor -----------------------------------------------------------
class Inversor_DC_AC:
  """
  Melhoria na classe
  1 - Atualmente o barramento DC está fixo. ele deve mudar dependendo de:
    1.1 - Se é grid-follower, grid-forming
    1.2 - sobrecarga no AC
    1.3 - excesso de geração FV, bateria cheia, baixa demanda da carga, exportação limitada para a rede
  2 - Implementar modo grid-follower
  3 - colocar o inversor para controlar se a bateria será carga ou geração
  """

  def __init__(self, id_inv, Nm_MPPT, In_Pmax, Imax_MPPT, In_Vnom, In_Vmin, In_Vmax, In_MPP_Vmin, In_MPP_Vmax, Out_Pmax, Out_Imax, Out_VL_nom, Out_Freq, Eficiencia, Max_THD, Fator_pot, Nm_fases, smart):
    self.Inversor_Param = self.Param_Inversor_DC_AC(id_inv, Nm_MPPT, In_Pmax, Imax_MPPT, In_Vnom, In_Vmin, In_Vmax, In_MPP_Vmin,  In_MPP_Vmax, Out_Pmax, Out_Imax, Out_VL_nom, Out_Freq, Eficiencia, Max_THD, Fator_pot, Nm_fases, smart)
    if smart == True:
      self.simulacao_inversor = self.Simulacao_inversor_smart(self.Inversor_Param)
    else:
      self.simulacao_inversor = self.Simulacao_inversor_convencional(self.Inversor_Param)

    self.mode = "grid-former"

    self.P_Demandada = []
    self.Q_Demandada = []

    self.saida_P_Instantanea_AC = []
    self.saida_P_AC = []
    self.saida_S_AC = []
    self.saida_Q_AC = []

    self.saida_V_AC = []
    self.saida_I_AC = []

    self.saida_V_RMS_AC = []
    self.saida_I_RMS_AC = []

    self.Protecoes_acionadas = []
    
    self.contadores_protecao_CA = {
      "sobretensao_CA": 0,
      "sobretensao_CA_Critica": 0,
      "subtensao_CA": 0,
      "sobrecorrente_CA": 0
    }

    self.contadores_protecao_CC = {"strings": {}}

    self.buffer_mensagens = {
      "Painel": {
        "medicoes_pv": {}
      },
      "Bateria": {
        "medicoes_bateria": {},
        "estado_bateria": {}
      },
      "Barramento": {
        "p_demandada": {},
        "parametros_barramento": {}
      }
    }

  def Simular_equipamento(self, falhas_inversor, agente_MQTT):
    Relacoes_potencias = self.Organiza_Relacoes_potencia() # Junta os valores de potencia em um array.np
    matriz_paineis = self.Obter_valores_mppt() # Junta as tensões e potência de cada string em um array.np
    matriz_baterias = self.Obter_valores_baterias()
    Valores_estaticos_carga = self.Calc_val_estaticos_carga() # junta os valores estáticos da carga em um array.np

    if Var_globais.Passo_atual_global != 0:
      self.Verifica_Protecoes(matriz_paineis)

    if Var_globais.Passo_atual_global <= 1:
      print(f"inversor = {self.buffer_mensagens}")

    val_onda, val_rms, acao_bateria, matriz_tensoes_mppt = self.simulacao_inversor.Simula_Inversor(Relacoes_potencias, matriz_paineis, Valores_estaticos_carga, self.Protecoes_acionadas, falhas_inversor)

    # ------------ Calcula e salva potencias, correntes e tensões ------------
    potencias = self.calcular_potencias_AC(val_onda, val_rms)  # Calcula as potencias AC
    self.Armazena_Saidas_AC(potencias, val_onda, val_rms)  # Salva todas as variáveis para consulta

    # ------------ Gera e salva todos os valores trifásicos ------------
    if Var_globais.Passo_atual_global == Var_globais.Num_Iteracao_global - 1 and (self.Inversor_Param.Nm_fases > 1): # Se chegou no ultimo passo da simulação
      self.V_linhas, self.I_linhas, self.V_fases, self.I_fases = self.Expande_Trifasico() # Gera e salva todos os valores trifásicos

    # ----------- Envia mensagens MQTT ---------------------------------
    msg_bateria = { str(linha[0]): {"acao": float(acao_bateria[0]), "Pot_requerida": float(acao_bateria[1]), } for linha in matriz_baterias }
    agente_MQTT.publicar_msg( f"{self.Inversor_Param.id_inv}/saida_bateria", msg_bateria)

    msg_mppt = { str(linha[0]): {"V_mppt": float(linha[1])} for linha in matriz_tensoes_mppt } # monta a mensagem com as tensões por entrada mppt
    agente_MQTT.publicar_msg( f"{self.Inversor_Param.id_inv}/saida_mppt", msg_mppt)

    agente_MQTT.publicar_msg( f"{self.Inversor_Param.id_inv}/saida_ac", { self.Inversor_Param.id_inv: {"V_ac_rms": val_rms[0], "I_ac_rms": val_rms[1], "V_ac_onda": val_onda[0], "I_ac_onda": val_onda[1]}})

  def receive(self, origem, tipo_origem, topico, mensagem):
    """
    origem: "PV_1", "BAT_1", "INV_1"...
    tipo_origem: "Painel", "Bateria", "Carga", "Inversor", ...
    topico: "medicoes_pv", "estado_bateria", etc.
    mensagem: dict padronizado
    """
    # Verifica tipo
    if tipo_origem not in self.buffer_mensagens:
        print(f"[INVERSOR] Tipo inesperado '{tipo_origem}'.")
        return

    # Verifica tópico
    if topico not in self.buffer_mensagens[tipo_origem]:
        print(f"[INVERSOR] Tópico '{topico}' não pertence ao tipo '{tipo_origem}'.")
        return

    if (origem not in mensagem) and (self.Inversor_Param.id_inv not in mensagem):
        print(f"[INVERSOR] Mensagem recebida mas receptor da mensagem não reconhecido.")
        return

    if origem not in mensagem:
      dados_extraidos = mensagem[self.Inversor_Param.id_inv]
      self.buffer_mensagens[tipo_origem][topico][origem] = dados_extraidos
    else:
      dados_extraidos = mensagem[origem]
      self.buffer_mensagens[tipo_origem][topico][origem] = dados_extraidos
    
  def Organiza_Relacoes_potencia(self):
    # -------- Potência dos painéis --------
    medicoes_PV = self.buffer_mensagens["Painel"]["medicoes_pv"]
    P_pv_total = sum(dados.get("P_pv", 0.0) for dados in medicoes_PV.values())

    # -------- Potência das baterias --------
    medicoes_bat = self.buffer_mensagens["Bateria"]["medicoes_bateria"]
    P_bat_total = sum(dados.get("P", 0.0) for dados in medicoes_bat.values())

    # -------- Potência demandada pela carga --------
    demanda_carga = self.buffer_mensagens["Barramento"]["p_demandada"]

    if len(demanda_carga) > 0:
      _, dados = next(iter(demanda_carga.items()))
      P_demandada = dados.get("P_demandada", 0.0)
    else:
      P_demandada = 0.0

    # -------- Agrupa --------
    Relacoes_potencias = np.array([P_demandada, P_pv_total, P_bat_total])
    
    return Relacoes_potencias  

  def Obter_valores_mppt(self):
    """
    Lê as tensões, correntes e potências enviadas pelas strings de painéis (medicoes_pv),
    verifica se o número de strings excede o Nm_MPPT do inversor,
    e retorna uma matriz numpy no formato:
      [[id_painel, V_pv, I_pv, P_pv],
      [id_painel, V_pv, I_pv, P_pv],
      ...]
    """
    medicoes_PV = self.buffer_mensagens["Painel"]["medicoes_pv"]

    num_strings_mppt = len(medicoes_PV)     # Strings conectadas
    Nm_MPPT = self.Inversor_Param.Nm_MPPT   # Limite do inversor

    # Verificação
    if num_strings_mppt > Nm_MPPT:
      raise ValueError(
        f"Erro: Foram detectados {num_strings_mppt} strings, "
        f"mas o inversor suporta apenas {Nm_MPPT} MPPTs."
      )

    matriz_mppt = []   # Vai virar matriz Nx3: [id, tensão, potência]

    for origem, dados in medicoes_PV.items():
      # Verifica se TODOS os parâmetros foram enviados
      if "V_pv" not in dados or "I_pv" not in dados or "P_pv" not in dados:
        print(f"[INVERSOR] Aviso: painel {origem} não enviou V_pv, I_pv e/ou P_pv.")
        continue

      V = float(dados["V_pv"])
      I = float(dados["I_pv"])
      P = float(dados["P_pv"])

      # Linha da matriz
      matriz_mppt.append([origem, V, I, P])

    # Converte lista → matriz numpy
    matriz_paineis = np.array(matriz_mppt, dtype=object)
    return matriz_paineis

  def Obter_valores_baterias(self):
    """
    Lê as tensões, correntes e potências enviadas pelas strings de painéis (medicoes_bateria),
    verifica se o número de strings excede o Nm_MPPT do inversor,
    e retorna uma matriz numpy no formato:
      [[id_bateria, V_bat, I_bat, P_bat],
      [id_bateria, V_bat, I_bat, P_bat],
      ...]
    """
    medicoes_batt = self.buffer_mensagens["Bateria"]["medicoes_bateria"]

    num_strings_bateria = len(medicoes_batt)     # Strings conectadas
    Nm_baterias = self.Inversor_Param.Nm_MPPT   # Limite do inversor

    # Verificação
    if num_strings_bateria > Nm_baterias:
      raise ValueError(
        f"Erro: Foram detectados {num_strings_bateria} strings, "
        f"mas o inversor suporta apenas {Nm_baterias} trings de baterias."
      )

    matriz_mppt_baterias = []   # Vai virar matriz Nx3: [id, tensão, potência]

    for origem, dados in medicoes_batt.items():
      # Verifica se TODOS os parâmetros foram enviados
      if "V_bat" not in dados or "I_bat" not in dados or "P_bat" not in dados:
        print(f"[INVERSOR] Aviso: Bateria {origem} não enviou toda as informações.")
        continue

      V_bat = float(dados["V_bat"])
      I_bat = float(dados["I_bat"])
      P_bat = float(dados["P_bat"])

      # Linha da matriz
      matriz_mppt_baterias.append([origem, V_bat, I_bat, P_bat])

    # Converte lista → matriz numpy
    matriz_baterias = np.array(matriz_mppt_baterias, dtype=object)
    return matriz_baterias

  def Calc_val_estaticos_carga(self):
    parametros_barramento = self.buffer_mensagens["Barramento"]["parametros_barramento"]
    if len(parametros_barramento) == 0:
      print("[INVERSOR] Barramento não enviou parâmetros.")
      self.V_bus = 380
    elif self.mode == "grid-former":
      self.V_bus = 380
    else:
      _, dados = next(iter(parametros_barramento.items()))
      self.V_bus = dados.get("V_bus", 380)

    relacoes_por_demandada = self.buffer_mensagens["Barramento"]["p_demandada"]

    if len(relacoes_por_demandada) == 0:
      print("[INVERSOR] P_demandada/Q_demandada ausentes.")
      return np.array([np.inf, 0.0, 0.0], dtype=float)

    primeiro_barramento = list(relacoes_por_demandada.keys())[0]
    dados_bus = relacoes_por_demandada[primeiro_barramento]

    P = float(dados_bus.get("P_demandada", 0.0))
    Q = float(dados_bus.get("Q_demandada", 0.0))

    S = np.sqrt(P**2 + Q**2)
    if S == 0:
      return np.array([np.inf, 0.0, 0.0], dtype=float)

    fp = P / S if S != 0 else 1.0

    I = S / self.V_bus if self.V_bus != 0 else 1e-4
    Z = self.V_bus / I
    R = Z * abs(fp)
    X = Z * np.sqrt(max(0, 1 - fp**2))

    L = 0
    C = 0

    w = 2 * np.pi * 60

    if Q > 0: # indutiva
      L = X / w
      C = 0
    elif Q < 0: # capacitiva
      C = 1 / (w * X)
      L = 0
    else:
      L = 0
      C = 0

    return np.array([R, L, C], dtype=float)

  def Verifica_Protecoes(self, Valores_CC_por_string):

      V_AC_Atual = self.saida_V_RMS_AC[-1]
      I_AC_Atual = self.saida_I_RMS_AC[-1]

      # ----------------------------------------------
      #   GARANTE ESTRUTURA PARA STRINGS
      # ----------------------------------------------
      if "strings" not in self.contadores_protecao_CC:
          self.contadores_protecao_CC["strings"] = {}

      protecoes_por_string = []

      # ======================================================
      #      PROTEÇÕES CC POR STRING
      # ======================================================
      for (id_str, V_str, I_str, P_str) in Valores_CC_por_string:

          # Criar contador da string caso não exista
          if id_str not in self.contadores_protecao_CC["strings"]:
              self.contadores_protecao_CC["strings"][id_str] = {
                  "Fora_Range_MPPT": 0,
                  "sobretensao_CC": 0,
                  "subtensao_CC": 0,
                  "sobrecorrente_CC": 0
              }

          c = self.contadores_protecao_CC["strings"][id_str]

          # -------- FORA DO RANGE MPPT --------
          if V_str > self.Inversor_Param.In_MPP_Vmax:
              c["Fora_Range_MPPT"] += Var_globais.Passo_global
          elif V_str < self.Inversor_Param.In_MPP_Vmax * 0.7:
              c["Fora_Range_MPPT"] = 0

          # -------- SOBRETENSÃO CC --------
          if V_str > self.Inversor_Param.In_Vmax:
              c["sobretensao_CC"] += Var_globais.Passo_global
          elif V_str < self.Inversor_Param.In_Vmax * 0.7:
              c["sobretensao_CC"] = 0

          # -------- SUBTENSÃO CC --------
          if V_str < self.Inversor_Param.In_Vmin:
              c["subtensao_CC"] += Var_globais.Passo_global
          elif V_str > self.Inversor_Param.In_Vmin * 1.3:
              c["subtensao_CC"] = 0

          # -------- SOBRECORRENTE CC --------
          if I_str > self.Inversor_Param.Imax_MPPT:
              c["sobrecorrente_CC"] += Var_globais.Passo_global
          else:
              c["sobrecorrente_CC"] = 0

          # -------- VERIFICA SE ALGUMA PROTEÇÃO ACIONA --------
          for prot, cont in c.items():

              tempo_min = 0.5 if prot == "Fora_Range_MPPT" else 0.16

              if cont >= tempo_min:

                  # Proteção ainda não registrada
                  if not any(p[0] == f"{prot}_{id_str}" for p in self.Protecoes_acionadas):
                      self.Protecoes_acionadas.append(
                          (f"{prot}", Var_globais.Passo_atual_global)
                      )
                      # print(f"[PROTEÇÃO] {prot} acionada na string {id_str}")

                  protecoes_por_string.append((id_str, prot))

      # ======================================================
      #                 PROTEÇÕES AC
      # ======================================================

      # Sobe tensão CA
      if V_AC_Atual > self.Inversor_Param.Out_VL_nom * 1.2:
          self.contadores_protecao_CA["sobretensao_CA_Critica"] += Var_globais.Passo_global

      elif V_AC_Atual > self.Inversor_Param.Out_VL_nom * 1.1:
          self.contadores_protecao_CA["sobretensao_CA"] += Var_globais.Passo_global

      else:
          self.contadores_protecao_CA["sobretensao_CA"] = 0
          self.contadores_protecao_CA["sobretensao_CA_Critica"] = 0

      # Subtensão CA
      if V_AC_Atual < self.Inversor_Param.Out_VL_nom * 0.88:
          self.contadores_protecao_CA["subtensao_CA"] += Var_globais.Passo_global
      else:
          self.contadores_protecao_CA["subtensao_CA"] = 0

      # Sobrecorrente CA
      if I_AC_Atual > self.Inversor_Param.Out_Imax:
          self.contadores_protecao_CA["sobrecorrente_CA"] += Var_globais.Passo_global
      else:
          self.contadores_protecao_CA["sobrecorrente_CA"] = 0

      # -------- VERIFICA ACIONAMENTO CA --------
      for prot, cont in self.contadores_protecao_CA.items():

          if prot == "sobretensao_CA_Critica":
              tempo_min = 0.05
          elif prot == "sobretensao_CA":
              tempo_min = 0.5
          else:
              tempo_min = 0.16

          if cont >= tempo_min:

              # Se ainda não registrado
              if not any(p[0] == prot for p in self.Protecoes_acionadas):
                  self.Protecoes_acionadas.append((prot, Var_globais.Passo_atual_global))
                  # print(f"[PROTEÇÃO AC] {prot} acionada")

      return self.Protecoes_acionadas

  # ------------ Funções inalteradas ---------------------

  def Expande_Trifasico(self):    
    f = self.Inversor_Param.Out_Freq
    dt = Var_globais.Passo_global

    samples_per_cycle = int(round(1.0 / (f * dt)))
    samples_120deg = int(round(samples_per_cycle / 3.0))

    V_L12, I_L12 = self.Resgata_forma_onda_AC()   
    V_L12 = np.array(V_L12, dtype=float)
    I_L12 = np.array(I_L12, dtype=float) 

    # Deslocamento circular
    V_L23 = np.roll(V_L12, -samples_120deg)  # -120°
    V_L31 = np.roll(V_L12, samples_120deg)   # +
    # V_L31 = - (V_L12 + V_L23) ------- Se for implementar desbalanço.

    V_a = (2.0*V_L12 + 1.0*V_L23) / 3.0
    V_b = (-1.0*V_L12 + 1.0*V_L23) / 3.0
    V_c = (-1.0*V_L12 - 2.0*V_L23) / 3.0

    I_L23 = np.roll(I_L12, -samples_120deg)  # -120°
    I_L31 = np.roll(I_L12, samples_120deg)   # +

    I_a = I_L12
    I_b = I_L23
    I_c = I_L31

    return [V_L12, V_L23, V_L31], [I_L12, I_L23, I_L31], [V_a, V_b, V_c], [I_a, I_b, I_c]

  def Resgata_relacoes_trifasicas(self):
    return self.V_linhas, self.I_linhas, self.V_fases, self.I_fases

  def calcular_potencias_AC(self, Val_onda, Val_rms):
    V_out = Val_onda[0]
    I_out = Val_onda[1]
    V_AC_RMS = Val_rms[0]
    I_AC_RMS = Val_rms[1]

    if self.Inversor_Param.Nm_fases > 1:
      P_instantanea = np.sqrt(3) * V_out * I_out
      P_ativa =  np.sqrt(3) * V_AC_RMS * I_AC_RMS * self.Inversor_Param.Fator_pot
      S_aparente =  np.sqrt(3) * V_AC_RMS * I_AC_RMS
      Q_reativa = np.sqrt(S_aparente**2 - P_ativa**2)

      potencias = [P_instantanea, P_ativa, S_aparente, Q_reativa]

    elif self.Inversor_Param.Nm_fases == 1:
      P_instantanea = V_out * I_out
      P_ativa = V_AC_RMS * I_AC_RMS * self.Inversor_Param.Fator_pot
      S_aparente = V_AC_RMS * I_AC_RMS
      Q_reativa = np.sqrt(S_aparente**2 - P_ativa**2)

      potencias = [P_instantanea, P_ativa, S_aparente, Q_reativa]

    return potencias

  # ----------------- Dados saida inversor --------------------- #
  def Armazena_Saidas_AC(self, potencias, formas_onda, valores_RMS):
    P_instantanea, P, S, Q = potencias

    self.saida_P_Instantanea_AC.append(P_instantanea)
    self.saida_P_AC.append(P)
    self.saida_S_AC.append(S)
    self.saida_Q_AC.append(Q)

    V_AC, I_AC = formas_onda
    self.saida_V_AC.append(V_AC)
    self.saida_I_AC.append(I_AC)

    V_RMS_AC, I_RMS_AC = valores_RMS
    self.saida_V_RMS_AC.append(V_RMS_AC)
    self.saida_I_RMS_AC.append(I_RMS_AC)

  def Resgata_Potencias_AC(self):
    return self.saida_P_Instantanea_AC, self.saida_P_AC, self.saida_S_AC, self.saida_Q_AC
  
  def Resgata_forma_onda_AC(self):
    return self.saida_V_AC, self.saida_I_AC
  
  def Resgata_Val_RMS_AC(self):
    return self.saida_V_RMS_AC, self.saida_I_RMS_AC
  
  class Param_Inversor_DC_AC:
    def __init__(self, id_inv, Nm_MPPT, In_Pmax, Imax_MPPT, In_Vnom, In_Vmin, In_Vmax, In_MPP_Vmin,  In_MPP_Vmax, Out_Pmax, Out_Imax, Out_VL_nom, Out_Freq, Eficiencia, Max_THD, Fator_pot, Nm_fases, smart):
      # Parametros de Entrada  
      self.id_inv = id_inv
      self.Nm_MPPT = Nm_MPPT          # Numero de MPPT's
      self.In_Pmax = In_Pmax          # Potência Max do painel
      self.Imax_MPPT = Imax_MPPT      # Corrente Max por MPPT
      self.In_Vnom = In_Vnom          # Tensão nominal de entrada
      self.In_Vmin = In_Vmin          # Tensão minima de entrada
      self.In_Vmax = In_Vmax          # Tensão maxima de entrada
      self.In_MPP_Vmin = In_MPP_Vmin  # Tensão minima de ajuste MPPT
      self.In_MPP_Vmax = In_MPP_Vmax  # Tensão maxima de ajuste MPPT

      # Parametros de Saida
      self.Out_Pmax = Out_Pmax                  # Potencia max de saida
      self.Out_Imax = Out_Imax                  # Corrente max de saida

      self.Out_VL_nom = Out_VL_nom
      self.Out_VF_nom = Out_VL_nom/np.sqrt(3)

      if Nm_fases == 1:
        self.Out_V_Pico = self.Out_VF_nom * np.sqrt(2)  # Tensão nominal de saida Pico a Pico
      elif Nm_fases > 1:
        self.Out_V_Pico = self.Out_VL_nom * np.sqrt(2)  # Tensão nominal de saida Pico a Pico
      else:
        self.Out_V_Pico = "ERRO"

      self.Out_Freq = Out_Freq                  # Frequencia de saida

      # Outros
      self.Eficiencia = Eficiencia  # Eficiencia do inversor
      self.Max_THD = Max_THD        # Maxima distorção harmonica
      self.Fator_pot = Fator_pot    # Fator de potência do inversor
      self.Nm_fases = Nm_fases
      self.smart = smart

      # Param Simulacao
      self.Filtro_R = 3.5
      self.Filtro_L = 0.01
      self.Filtro_C = 680e-6

      self.Cond_Iniciais_V = [0, 0]
      self.Cond_Iniciais_I = [0, 0]
      self.Tolerancia_relativa = 1e-8
      self.Metodo_EDO = 'RK45'

      self.Perda_inversor = 1 - Eficiencia
      self.Perda_Cabo = 0
      self.Perda_Mismatch = 0

      self.Tempo_acionamento_protecao = 2

    def Retorna_Parametros_Tecnicos(self):
      return self.Out_V_Pico, self.Out_VL_nom, self.Out_VF_nom, self.Out_Freq, self.Eficiencia, self.Filtro_R, self.Filtro_L, self.Filtro_C
    
    def Retorna_Parametros_Saturacao(self):
      return self.Imax_MPPT, self.In_Vmin, self.In_Vmax, self.In_MPP_Vmin, self.In_MPP_Vmax

    def Retorna_Parametros_EDO(self):
      return self.Cond_Iniciais_V, self.Cond_Iniciais_I, self.Tolerancia_relativa, self.Metodo_EDO

    def Retorna_Perdas(self):
      return self.Perda_inversor, self.Perda_Cabo, self.Perda_Mismatch

  class Simulacao_inversor_convencional:
    def __init__(self, Inversor):
      self.inversor_param = Inversor
      self.Out_V_PP, self.Out_VL_nom, self.Out_VF_nom, self.Out_Freq, self.eficiencia, self.Filtro_R, self.Filtro_L, self.Filtro_C  = Inversor.Retorna_Parametros_Tecnicos()
      self.Imax_MPPT, self.In_Vmin, self.In_Vmax, self.In_MPP_Vmin, self.In_MPP_Vmax = Inversor.Retorna_Parametros_Saturacao()
      self.Cond_Iniciais_V, self.Cond_Iniciais_I, self.Tolerancia_relativa, self.Metodo_EDO = Inversor.Retorna_Parametros_EDO()
      self.Nm_fases = Inversor.Nm_fases

      Perda_inversor, Perda_Cabo, Perda_Mismatch = Inversor.Retorna_Perdas()
      
      self.Vref_painel = 0

      self.V_IN_DC, self.I_IN_DC, self.P_IN_DC = 0, 0, 0
      self.R, self.L, self.C = np.inf, 0, 0
      
      self.Tempo_Sim = 0  # Começa do tempo 0
      #Valores Relacionados ao MPPT
      self.P_PV_Anterior = -1
      self.V_PV_Anterior = -1

      self.MPPT_learning_rate =  2
      self.prev_dir = +1

      self.Perdas_totais = Perda_inversor + Perda_Cabo + Perda_Mismatch

      self.V_AC_RMS = 0
      self.I_AC_RMS = 0

      # Parametros de modulação do inversor
      self.Mf = 35                              # Modulação de Frequência
      self.Amp_sine = 1                              # Amplitude da onda seno referencia
      self.f_tri = self.Mf * self.Out_Freq      # Frequencia chaveamento
      self.T_sw = 1 / self.f_tri                # Tempo de chaveamento
      self.Ma = self.Out_V_PP / (self.In_Vmax/2)
      # self.Ma = self.Out_V_PP / (500)
      self.Amp_Tri = self.Amp_sine / self.Ma
      # ---------------- RMS Sliding Window ----------------
      self.janela_tempo = 1 / self.Out_Freq  # 1 ciclo
      self.janela_tamanho = int(self.janela_tempo / Var_globais.Passo_global)
      self.janela_Vout = deque(maxlen=self.janela_tamanho)
      self.janela_Iout = deque(maxlen=self.janela_tamanho)

      self.flag_falha = 0
      
      self.margem = 200
      self.V_bus_DC = np.sqrt(2)*self.Out_VF_nom + self.margem

    def Simula_Inversor(self, Relacoes_potencias, Valores_mppt, Valores_RLC_carga, Protecoes_Acionadas, falhas_inversor):
      # ------------ Pega variáveis úteis para uso ------------
      self.Relacoes_potencias = Relacoes_potencias
      
      self.Valores_mppt = Valores_mppt

      self.carga_R = Valores_RLC_carga[0]
      self.carga_L = Valores_RLC_carga[1]
      self.carga_C = Valores_RLC_carga[2]
      
      # ------------ Funções de simulação e controle do equipamento ------------
      self.Logica_falhas(falhas_inversor)
      acao_bateria, matriz_tensoes_mppt = self.Logica_Controle_offgrid(Protecoes_Acionadas)  # Chama função que faz a lógica de controle
      self.V_out, self.I_out = self.Sim_VI(Protecoes_Acionadas)  # Chama função que resolve as EDO's para gerar valores de saída

      # ------------ Faz o calculo dos valores RMS ------------
      self.V_AC_RMS, self.I_AC_RMS = self.Calcula_Valores_RMS(self.V_out, self.I_out)

      Val_rms = [float(self.V_AC_RMS), float(self.I_AC_RMS)]
      Val_onda = np.array([self.V_out, self.I_out])

      return Val_onda, Val_rms, acao_bateria, matriz_tensoes_mppt

    # ------------------------------ Algoritmos de cálculo para sáida do inversor -----------------------------------------
    def Sim_VI(self, Protecoes_Acionadas):
      if Protecoes_Acionadas:
        V_out = 0.0  # tensão de circuito aberto = tensão no capacitor
        I_out = 0.0  # corrente zera pois está aberto
        self.Tempo_Sim += Var_globais.Passo_global
        return V_out, I_out
  
      sol_V = solve_ivp(self.EDO_Filtro_RLC, (self.Tempo_Sim, self.Tempo_Sim + Var_globais.Passo_global), self.Cond_Iniciais_V, method=self.Metodo_EDO, t_eval=[self.Tempo_Sim + Var_globais.Passo_global], rtol=self.Tolerancia_relativa)

      self.Cond_Iniciais_V = sol_V.y[:, -1]  # Atualiza o estado da Tensão
      q_solution = self.Cond_Iniciais_V[0]
      V_out = q_solution / self.Filtro_C

      sol_I = solve_ivp(lambda t, y: self.EDO_Corrente_carga(t, y, V_out), (self.Tempo_Sim, self.Tempo_Sim + Var_globais.Passo_global), self.Cond_Iniciais_I, method=self.Metodo_EDO, t_eval=[self.Tempo_Sim + Var_globais.Passo_global], rtol=self.Tolerancia_relativa)

      self.Cond_Iniciais_I = sol_I.y[:, -1]  # Atualiza o estado da Corrente
      I_out = self.Cond_Iniciais_I[0]

      self.Tempo_Sim = sol_V.t[-1]  # Atualiza o tempo
      return V_out, I_out

    def Modulacao_PWM(self, t):
      Onda_triangular = self.Amp_Tri * ( 1 - 2 * np.abs( (self.Tempo_Sim / self.T_sw) - np.floor( (self.Tempo_Sim / self.T_sw) + (1 / 2) ) ) )

      Onda_seno1 = np.sin(2 * np.pi * self.Out_Freq * self.Tempo_Sim + 0)
      Onda_PWM1 = 0.5 * (1 + np.sign(Onda_seno1 - Onda_triangular))

      Onda_seno2 = np.sin(2 * np.pi * self.Out_Freq * self.Tempo_Sim + np.pi)
      Onda_PWM2 = 0.5 * (1 + np.sign(Onda_seno2 - Onda_triangular))

      pwm_resultante = Onda_PWM1 - Onda_PWM2

      return pwm_resultante

    def EDO_Filtro_RLC(self, t, y):
      q, dq_dt = y
      m_t = self.Modulacao_PWM(t)     # Modulação PWM fictícia para teste
      d2q_dt2 = (1 / self.Filtro_L) * (self.V_bus_DC * m_t - q / self.Filtro_C - dq_dt * self.Filtro_R) # EDO do filtro RLC em uma onda PWM
      return [dq_dt, d2q_dt2]

    def EDO_Corrente_carga(self, t, y, Vout):
      if self.carga_R == np.inf and self.carga_L == 0:
        di_dt = 0
        dv_c_dt = 0
      else:
        i = y[0]  # Corrente no circuito
        v_c = y[1] if self.carga_C != 0 else 0  # Tensão no capacitor

        if self.Nm_fases > 1:
          Vout = Vout/np.sqrt(3)

        # Equações diferenciais para o circuito RLC (ou RL, se C = 0)
        if self.carga_C != 0:
          di_dt = (Vout - self.carga_R * i - v_c) / self.carga_L
          dv_c_dt = i / self.carga_C
        else:  # Caso RL apenas
          di_dt = (Vout - self.carga_R * i) / self.carga_L
          dv_c_dt = 0  # Sem variação de tensão no capacitor

        di_dt = di_dt * (1 - self.Perdas_totais)

      return [di_dt, dv_c_dt]

    # ------------------------------ Algoritmos de controle do inversor -----------------------------------------
    def Logica_Controle_offgrid(self, Protecoes_Acionadas):

      P_demandada = self.Relacoes_potencias[0]
      P_painel = self.Relacoes_potencias[1]
      P_baterias = self.Relacoes_potencias[2]

      if Protecoes_Acionadas:
        lista_V = []
        self.Vref_painel = "Voc"
        self.Ma = 1e-12
        self.Amp_Tri = self.Amp_sine / self.Ma

        for linha in self.Valores_mppt:
          id_pv = str(linha[0])
          lista_V.append([id_pv, 0])

        matriz_tensoes_mppt = np.array(lista_V, dtype=object)
        acao_bateria = np.array(["espera", 0], dtype=object)
        return acao_bateria, matriz_tensoes_mppt

      self.Calcula_Param_Modulacao()

      if self.flag_falha:
        return

      if P_painel > P_demandada:
        acao_bateria = np.array(["carregar", P_painel - P_demandada], dtype=object)
      elif P_painel < P_demandada:
        acao_bateria = np.array(["descarregar", P_demandada - P_painel], dtype=object)
      else:
        acao_bateria = np.array(["espera", 0], dtype=object)

      # P_geracao_total:
      # - Bateria como fonte (P_baterias > 0): painel + bateria
      # - Caso contrário: só painel
      P_geracao_total = P_painel + P_baterias if P_baterias > 0 else P_painel

      # P_demandada_total:
      # - Bateria como carga (P_baterias < 0): demanda + (valor negativo)
      # - Caso contrário: demanda normal
      P_demandada_total = P_demandada + P_baterias if P_baterias < 0 else P_demandada

      # print(f"[INVERSOR] - P_GER = {P_geracao_total}, P_DEM = {P_demandada_total}")

      if P_geracao_total > (P_demandada_total * 1.05): #Ativar curtailment
        matriz_ajustada = self.Ajustar_Potencia_MPPT(self.Valores_mppt, P_demandada_total)
        matriz_tensoes_mppt = self.Calcular_MPPT_Strings(self.Valores_mppt, matriz_ajustada)
        
      elif P_geracao_total < (P_demandada_total * 0.95): # Ativa proteção de sobrecarga
        matriz_tensoes_mppt = self.Calcular_MPPT_Strings(self.Valores_mppt, -1)

        # print(f"[Controle] Potência insuficiente: Acionando proteção de sobrecarga")
      else:
        matriz_tensoes_mppt = self.Calcular_MPPT_Strings(self.Valores_mppt, -1)
      
      # print(f"[INVERSOR] - MATRIZ MPPT = {matriz_tensoes_mppt}")
      # print("---------")
      return acao_bateria, matriz_tensoes_mppt

    def Calcula_Param_Modulacao(self):
      # Referências
      Ma = (self.Out_V_PP / self.V_bus_DC)*0.901

      V_ref = self.Out_VL_nom
      V_RMS = self.V_AC_RMS

      erro = V_ref - V_RMS

      # Parâmetros do controlador PID
      Kp = 5.2e-7   # Proporcional
      Ki = 2e-8   # Integral
      Kd = 1e-9  # Derivativo (ajuste conforme necessário)

      dt = Var_globais.Passo_global  # Tempo de amostragem já definido em outra parte

      # Inicializa histórico se não existir
      if not hasattr(self, 'erro_integral'):
          self.erro_integral = 0.0
      if not hasattr(self, 'erro_anterior'):
          self.erro_anterior = erro

      # Integral com dt
      self.erro_integral += erro * dt
      self.erro_integral = max(min(self.erro_integral, 1000), -1000)  # Limita integral

      # Derivativo com dt
      derivada = (erro - self.erro_anterior) / dt
      self.erro_anterior = erro

      # PID
      ajuste = Kp * erro + Ki * self.erro_integral + Kd * derivada

      # Aplica ajuste no índice de modulação
      self.Ma = Ma + ajuste
      self.Ma = max(0.01, min(self.Ma, 2.0))
      # Debug
      # print(f"PID Ma: V_RMS={V_RMS:.2f}, V_ref={V_ref:.2f}, erro={erro:.2f}, integral={self.erro_integral:.2f}, derivada={derivada:.4f}, Ma={self.Ma:.4f}")

      # Ajusta a amplitude da portadora triangular
      self.Amp_Tri = self.Amp_sine / self.Ma

      Var_globais.MA_G.append(self.Ma)
      Var_globais.ERRO_G.append(erro)
      Var_globais.V_RMS_G.append(self.V_AC_RMS)

    def Ajustar_Potencia_MPPT(self, matriz_mppt, P_demandada):
      """
      Ajusta a potência gerada pelas strings MPPT proporcionalmente
      para que a soma final das potências seja igual à potência demandada.

      Parâmetros
      ----------
      matriz_mppt : np.array (dtype=object)
          [[id, V, I, P], ...]
      P_demandada : float
          Potência desejada na saída do inversor.

      Retorno
      -------
      nova_matriz : np.array
          [[id, V_original, P_ajustada], ...]
      """

      # Extrai potências atuais
      potencias = np.array([linha[3] for linha in matriz_mppt], dtype=float)
      P_total = potencias.sum()

      if P_total == 0:
        P_total = 1e-6

      # Fator de redução proporcional
      fator = P_demandada / P_total

      nova_matriz = []
      for (id_pv, V_pv, I_pv, P_pv) in matriz_mppt:
          P_novo = P_pv * fator
          nova_matriz.append([id_pv, P_novo])

      return np.array(nova_matriz, dtype=object)

    def Calcular_MPPT_Strings(self, Valores_mppt, matriz_ajustada):
        if isinstance(matriz_ajustada, np.ndarray):                                 # Se variável matriz_ajustada for uma matriz
            mapa_Pdesejada = {linha[0]: linha[1] for linha in matriz_ajustada}      # Cria um par chave-valor onde a chave é id_painel e o valor é pot deejada
        else:                       # Se não for uma matriz
            mapa_Pdesejada = None   # O mapa de potência deesjada fica nulo

        if not hasattr(self, "estado_mppt"):    # se variável estado_mppt não existir ainda
            self.estado_mppt = {}               # cria o dicionário self.estado_mppt que vai armazenar os valores antigos de pontecia e tensão dos paineis

        matriz_V_nova = []                      # instancia a variavel matriz_V_nova

        for linha in Valores_mppt:                                  # Itera sobre a matriz de valores MPPTs
            id_pv = str(linha[0])                                   # salva o id do painel atual                           
            V_atual = float(linha[1])                               # salva a tensão do painel atual  
            P_atual = float(linha[3])                               # salva a potência do painel atual  

            # P_desejada
            if mapa_Pdesejada is None:                              # Se o mapa_Pdesejada não existir
                P_desejada = -1                                     # Define a P_desejada para o painel atual como -1, ou seja, a pot_desejada é pot máxima
            else:                                                   # Se o mapa_Pdesejada existir
                P_desejada = mapa_Pdesejada.get(id_pv, -1)          # Pega a potência desejada para o painel com o id atual, se o id não existir, P_desejada = -1

            if id_pv not in self.estado_mppt:                       # Se não existir o id do painel no dicionário estado_mppt
                self.estado_mppt[id_pv] = {                         # coloca no dicionario o id do painel com as chaves p_anterior e v_anterior
                    "P_ant": -1,
                    "V_ant": -1,
                    "dir_mppt_ant": 1
                }

            estado_mppt_atual = self.estado_mppt[id_pv]                               # Referencia o estado mppt do painel atual na nova variavel
            V_novo = self.MPPT( P_atual, V_atual, P_desejada, estado_mppt_atual )     # chama a função que faz o calculo mppt para o painel atual
            matriz_V_nova.append([id_pv, V_novo])                                     # Coloca na matriz tensão nova os valores de mppt calculados que serão mandados para os painéis

        return np.array(matriz_V_nova, dtype=object)

    def MPPT(self, P_Atual, V_Atual, P_desejada, estado_mppt):
                
        P_ant = estado_mppt["P_ant"]
        V_ant = estado_mppt["V_ant"]
        dir_ant = estado_mppt["dir_mppt_ant"]

        if P_desejada == -1:    # Se a potencia desejada for igual -1, ele se comporta como mppt convencional
            if (P_Atual >= P_ant) and (P_Atual > 0.001):              # Se a potência aumentou
                if V_Atual >= V_ant:                                  # e a tensão aumentou
                    V_MPPT_Novo = V_Atual + self.MPPT_learning_rate   # Aumenta a tensão
                elif V_Atual < V_ant:                                 # e a tensão diminuiu
                    V_MPPT_Novo = V_Atual - self.MPPT_learning_rate   # diminui a tensão

            elif (P_Atual < P_ant) and (P_Atual > 0.001):             # Se a potência diminuiu
                if V_Atual >= V_ant:                                  # e a tensão aumentou
                    V_MPPT_Novo = V_Atual - self.MPPT_learning_rate   # diminui a tensão
                elif V_Atual < V_ant:                                 # e a tensão diminuiu
                    V_MPPT_Novo = V_Atual + self.MPPT_learning_rate   # Aumenta a tensão
            
            else:                                                     # Se a potência for igual a 0
                V_MPPT_Novo = V_Atual                                 # Mantém a tensão
          
            estado_mppt["P_ant"] = P_Atual
            estado_mppt["V_ant"] = V_MPPT_Novo

        else:    # Caso contrário ele se comporta como mppt inteligente
          if P_ant == -1:                                                     # Caso o sistema estivesse funcionando no modo de mppt convencional
              estado_mppt["P_ant"] = P_Atual                                  # atualiza os estados de potencia
              estado_mppt["V_ant"] = V_Atual                                  # atualiza os estados de tensão
              return V_Atual                                                  # Retorna o valor mppt inalterado

          deltaP = P_Atual - P_ant                                            # Calcula variações entre as potências ao longo do tempo

          if deltaP > 0:                                                      # Se potência subiu
              dir_atual = dir_ant                                             # continua na mesma direção
          else:                                                               # Se potência caiu
              dir_atual = -dir_ant                                            # inverte direção do mppt

          if P_Atual < P_desejada:                                            # Se queremos aumentar a potência => andar na direção que aumentou antes
              V_MPPT_Novo = V_Atual + dir_atual * self.MPPT_learning_rate
          else:                                                               # Se queremos diminuir a potência => andar na direção contrária
              V_MPPT_Novo = V_Atual - dir_atual * self.MPPT_learning_rate

          # Atualiza histórico
          estado_mppt["P_ant"] = P_Atual
          estado_mppt["V_ant"] = V_Atual
          estado_mppt["dir_mppt_ant"] = dir_atual

        return V_MPPT_Novo

    def old_MPPT(self, P_Atual, V_Atual, P_desejada):
      if P_desejada == -1:    # Se a potencia desejada for igual -1, ele se comporta como mppt convencional
        if (P_Atual >= self.P_PV_Anterior) and (P_Atual > 0.001):    # Se a potência aumentou
          if V_Atual >= self.V_PV_Anterior:                           # e a tensão aumentou
            V_MPPT_Novo = V_Atual + self.MPPT_learning_rate         # Aumenta a tensão
          if V_Atual < self.V_PV_Anterior:                            # e a tensão diminuiu
            V_MPPT_Novo = V_Atual - self.MPPT_learning_rate         # diminui a tensão

        elif (P_Atual < self.P_PV_Anterior) and (P_Atual > 0.001):  # Se a potência diminuiu
          if V_Atual >= self.V_PV_Anterior:                           # e a tensão aumentou
            V_MPPT_Novo = V_Atual - self.MPPT_learning_rate         # diminui a tensão
          if V_Atual < self.V_PV_Anterior:                            # e a tensão diminuiu
            V_MPPT_Novo = V_Atual + self.MPPT_learning_rate         # Aumenta a tensão

        else:                                                       # Se a potência for igual a 0
          V_MPPT_Novo = V_Atual                                      # Mantém a tensão

        self.P_PV_Anterior = P_Atual
        self.V_PV_Anterior = V_MPPT_Novo
      
      else:
        if self.P_PV_Anterior == -1:
            self.P_PV_Anterior = P_Atual
            self.V_PV_Anterior = V_Atual
            return V_Atual

        deltaP = P_Atual - self.P_PV_Anterior    # Calcula variações

        if deltaP > 0:    # Se potência subiu, continua na mesma direção
            dir = self.prev_dir
        else:             # Se potência caiu, inverte direção
            dir = -self.prev_dir

        if P_Atual < P_desejada:        # Queremos aumentar a potência => andar na direção que aumentou antes
            V_MPPT_Novo = V_Atual + dir * self.MPPT_learning_rate
        else:                           # Já passou do desejado => reduzir
            V_MPPT_Novo = V_Atual - dir * self.MPPT_learning_rate

        # Atualiza histórico
        self.P_PV_Anterior = P_Atual
        self.V_PV_Anterior = V_Atual
        self.prev_dir = dir

      return V_MPPT_Novo

    # ------------------------------ Algoritmos de cálculo do inversor -----------------------------------------
    def Calcula_Valores_RMS(self, V_out, I_out):
      self.janela_Vout.append(V_out)
      self.janela_Iout.append(I_out)

      if len(self.janela_Vout) == self.janela_tamanho:
        Vrms = float(np.sqrt(np.mean(np.square(self.janela_Vout))))
        Irms = float(np.sqrt(np.mean(np.square(self.janela_Iout))))
        return Vrms, Irms
      else:
        return 0, 0

    # ------------------------------ Algoritmos de proteção do inversor -----------------------------------------
    def Logica_falhas(self, falhas_inversor):
      if not falhas_inversor:
        return
      
      tempo_atual = Var_globais.Passo_global * Var_globais.Passo_atual_global
      tolerancia = Var_globais.Passo_global

      for falha in falhas_inversor:
        tipo = falha["Tipo_Falha"]
        tempos_falha = falha["T_falha"]
        duracoes = falha["duracao_falha"]

        for i, t_falha in enumerate(tempos_falha):
          duracao = duracoes[i] if i < len(duracoes) else None

          # Ativação da falha
          if abs(tempo_atual - t_falha) < tolerancia:
            if tipo == "Curto_Circuito_CC":
              self.Vref_painel = 1E-3
              self.flag_falha = 1
              self.inicio_falha = tempo_atual  # salva início
              self.duracao_falha = duracao

          # Desativação da falha
          if getattr(self, "flag_falha", 0) == 1 and hasattr(self, "inicio_falha"):
            if self.duracao_falha is not None:
              if tempo_atual - self.inicio_falha >= self.duracao_falha:
                self.flag_falha = 0
                del self.inicio_falha
                del self.duracao_falha

# ----------------------------------------------------------- Classes da carga -----------------------------------------------------------
class Carga_ZIP:
  def __init__(self, id_carga, nome_carga, tipo_carga, curva_carga, s_instalada, fp, v_nom, f_rede, conectado_rede):
    self.Carga_Param = self.Param_Carga_ZIP(id_carga, nome_carga, tipo_carga, curva_carga, s_instalada, fp, v_nom, f_rede)

    self.conectado_rede = conectado_rede
    self.V_rms_recebida = 381.5
    self.I_rms_recebida = None
    self.P_rms_recebida = None
    self.Q_rms_recebida = None

    self.P_Demandada = []
    self.Q_Demandada = []

  def Simular_equipamento(self, falhas_carga, agente_MQTT):
    if Var_globais.Passo_atual_global == 0:
      self.Carga_simulada = self.Simulacao_carga(self.Carga_Param)

    R, L, C, P, Q = self.Carga_simulada.Simula_Carga(falhas_carga, self.V_rms_recebida)
    self.Armazenar_Val_Carga_demandada(P, Q)

    agente_MQTT.publicar_msg( f"{self.Carga_Param.id_carga}/demanda_carga", {self.Carga_Param.id_carga: {"P_demandada": P, "Q_demandada": Q}})
    
    self.Val_calc_R = R
    self.Val_calc_L = L
    self.Val_calc_C = C
    self.Val_calc_P = P
    self.Val_calc_Q = Q

  def receive(self, origem, tipo_origem, topico, mensagem):
    if topico == "grandezas_ac":
      if self.Carga_Param.id_carga in mensagem:
        dados = mensagem[self.Carga_Param.id_carga]
        self.V_rms_recebida = dados.get("V_recebida")
        self.I_rms_recebida = dados.get("I_recebida")
        self.P_rms_recebida = dados.get("P_recebida")
        self.Q_rms_recebida = dados.get("Q_recebida")
      return

    # if topico == "grandezas_ac":
    #   if self.Carga_Param.id_carga in mensagem:
    #     dados = mensagem[self.Carga_Param.id_carga]
    #     self.V_rms_recebida = dados.get("V_rms")
    #     self.I_rms_recebida = dados.get("I_rms")
    #     self.P_rms_recebida = dados.get("P_rms")

    #     self.V_onda_recebida = dados.get("V_onda")
    #     self.I_onda_recebida = dados.get("I_onda")
    #     self.P_onda_recebida = dados.get("P_onda")
    #   return

  def Retorna_Param_Estatico(self):
    return self.Val_calc_R, self.Val_calc_L, self.Val_calc_C, self.Val_calc_P, self.Val_calc_Q

  def Estado_conexao_rede(self):
    return self.conectado_rede
  
  def Armazenar_Val_Carga_demandada(self, P_demandada, Q_demandada):
    self.P_Demandada.append(P_demandada)
    self.Q_Demandada.append(Q_demandada)
  
  def Retornar_Val_Carga_demandada(self):
    return self.P_Demandada, self.Q_Demandada

  class Param_Carga_ZIP:
    def __init__(self, id_carga, nome_carga, tipo_carga, curva_carga, s_instalada, fp, v_nom, f_rede):
      # Dados básicos
      self.id_carga = id_carga
      self.nome_carga = nome_carga
      self.tipo_carga = tipo_carga
      self.S_instalada = s_instalada
      self.V_nom = v_nom    # Tensão nominal
      self.fp = fp          # Fator de potência
      self.f_rede = f_rede       # Frequência da rede (ex: 60Hz)

      coeficientes_zip = {
        "Residencial": { "P": [0.15, 0.25, 0.60], "Q": [0.30, 0.40, 0.30] },
        "Comercial":   { "P": [0.20, 0.35, 0.45], "Q": [0.35, 0.35, 0.30] },
        "Industrial":  { "P": [0.30, 0.40, 0.30], "Q": [0.40, 0.30, 0.30] }
      }

      Curvas_Tipicas_Demanda = {
        "Residencial": { "Curva_R": [0.41, 0.21, 0.1, 0.05, 0.02, 0.02, 0.06, 0.21, 0.19, 0.2, 0.21, 0.23, 0.31, 0.3, 0.29, 0.29, 0.28, 0.36, 0.59, 0.9, 1.0, 0.91, 0.74, 0.55]},
        "Comercial":   { "Curva_C": [0.41, 0.21, 0.1, 0.05, 0.02, 0.02, 0.06, 0.21, 0.19, 0.2, 0.21, 0.23, 0.31, 0.3, 0.29, 0.29, 0.28, 0.36, 0.59, 0.9, 1.0, 0.91, 0.74, 0.55]},
        "Industrial":  { "Curva_I": [0.41, 0.21, 0.1, 0.05, 0.02, 0.02, 0.06, 0.21, 0.19, 0.2, 0.21, 0.23, 0.31, 0.3, 0.29, 0.29, 0.28, 0.36, 0.59, 0.9, 1.0, 0.91, 0.74, 0.55]}
      }

      if tipo_carga in coeficientes_zip:
        self.parametros_ZIP = coeficientes_zip[tipo_carga]
        self.Curva_Demanda = list(Curvas_Tipicas_Demanda[tipo_carga].values())[0]
      else:
        self.parametros_ZIP =  { "P": [0.15, 0.25, 0.60], "Q": [0.30, 0.40, 0.30] }
        self.Curva_Demanda = curva_carga

      # Estados dinâmicos
      self.R_eq = 1
      self.L_eq = 0.01

    def Retorna_gerais_carga(self):
      return self.nome_carga, self.tipo_carga

    def Retorna_dados_eletricos_carga(self):
      return self.S_instalada, self.V_nom, self.fp, self.f_rede
    
    def Retorna_curvas_carga(self):
      return self.parametros_ZIP, self.Curva_Demanda
    
    def Retorna_param_dinamicos(self):
      return self.R_eq, self.L_eq
    
  class Simulacao_carga:
    def __init__(self, Carga):
      self.nome_carga, self.tipo_carga = Carga.Retorna_gerais_carga()
      self.S_instalada, self.V_nom, self.fp, self.f_rede = Carga.Retorna_dados_eletricos_carga()
      self.parametros_ZIP, self.Curva_Demanda = Carga.Retorna_curvas_carga()
      self.R_eq, self.L_eq = Carga.Retorna_param_dinamicos()

      self.V_ac = [0]
      self.Vt_anterior = self.V_nom

      self.S_anterior = self.S_instalada

      self.P_instalada = self.S_instalada * self.fp
      self.Q_instalada = self.S_instalada * math.sin( math.acos(self.fp) )

      self.S_instalada_Atual = self.S_instalada

    def Simula_Carga(self, falhas_carga, V_ac_RMS):
      if Var_globais.Passo_atual_global == 0:
        self.V_ac = self.V_nom
      else:
        self.V_ac = V_ac_RMS

      self.aplicar_Mudanca_Carga(falhas_carga)

      if Var_globais.Passo_atual_global != 0:
        R, L, C, P, Q = self.Atualiza_RL_Estatico(self.V_ac) # Essa função deve mudar a carga dinamicamente, de acordo com o comportamento do sistema
      else:
        R, L, C, P, Q = self.Atualiza_RL_Estatico(0)
      
      return R, L, C, P, Q

    def aplicar_Mudanca_Carga(self, falhas_carga):
      tempo_atual = Var_globais.Passo_global * Var_globais.Passo_atual_global
      tolerancia = Var_globais.Passo_global

      # Dicionário para rastrear mudanças ativas (se ainda não existir)
      if not hasattr(self, "mudancas_ativas"):
        self.mudancas_ativas = {}

      for falha in falhas_carga:
        tipo = falha["Tipo_Falha"]
        tempos_falha = falha["T_falha"]
        duracoes = falha["duracao_falha"]

        for i, t_falha in enumerate(tempos_falha):
          duracao = duracoes[i] if i < len(duracoes) else None

          # Ativação da mudança
          if abs(tempo_atual - t_falha) < tolerancia:
            if tipo == "Mudanca_Carga":
              if "Carga" not in self.mudancas_ativas:
                valor_base = self.S_instalada_Atual
              else:
                valor_base = self.mudancas_ativas["Carga"]["valor_base"]
    
              self.mudancas_ativas["Carga"] = {
                "inicio": tempo_atual,
                "duracao": duracao,
                "valor_base": valor_base
              }
              self.S_instalada_Atual = falha["Pot_Carga"][i]
              print(f"[{tempo_atual}s] Carga alterada para {self.S_instalada_Atual} VA")

      # Desativação das mudanças quando a duração expira
      for chave, dados in list(self.mudancas_ativas.items()):
        if dados["duracao"] is not None:
          if tempo_atual - dados["inicio"] >= dados["duracao"]:
            if chave == "Carga":
              self.S_instalada_Atual = dados["valor_base"]
              print(f"[{tempo_atual}s] Carga alterada para {self.S_instalada_Atual} VA")

            del self.mudancas_ativas[chave]

    def Atualiza_RL_Estatico(self, Vt):
      Vt = self.V_nom

      if Vt != self.Vt_anterior or self.S_instalada_Atual != self.S_anterior or Var_globais.Passo_atual_global == 0:

        self.P = self.S_instalada_Atual * self.fp
        self.Q = self.S_instalada_Atual * np.sqrt(1-self.fp**2)
        S = self.S_instalada_Atual

        I = S / Vt if Vt != 0 else 1e-4
        Z = Vt / I
        R = Z * self.fp
        XL = Z * np.sqrt(1-self.fp**2)
        L = XL / (2 * np.pi * self.f_rede)

        # Atualiza para simulação
        self.Carga_R = R
        self.Carga_L = L
        self.Carga_C = 0

      self.Vt_anterior = Vt
      self.S_anterior = self.S_instalada_Atual

      return self.Carga_R, self.Carga_L, self.Carga_C, self.P, self.Q

    def Atualiza_RL(self, Vt):
      if Vt == 0:
        Vt = 1e-3

      if Vt != self.Vt_anterior or Var_globais.Passo_atual_global == 0:
        self.P, self.Q = self.Calcula_PQ_ZIP(Vt)

        S = np.sqrt(self.P**2 + self.Q**2)
        I = S / Vt if Vt != 0 else 1e-4
        Z = Vt / I
        R = self.P / I**2 if I != 0 else 1e6
        X = self.Q / I**2 if I != 0 else 1e6
        L = X / (2 * np.pi * self.f_rede)

        # Atualiza para simulação
        self.Carga_R = R
        self.Carga_L = L
        self.Carga_C = 0

      Vt_anterior = Vt

      return self.Carga_R, self.Carga_L, self.Carga_C, self.P, self.Q

    def Calcula_PQ_ZIP(self, V_ac):
      Vpu = V_ac / self.V_nom
      a1, a2, a3 = self.parametros_ZIP["P"]
      b1, b2, b3 = self.parametros_ZIP["Q"]
      P = self.P_instalada * (a1 * Vpu**2 + a2 * Vpu + a3)
      Q = self.Q_instalada * (b1 * Vpu**2 + b2 * Vpu + b3)
      P = P * self.Curva_Demanda[0] # Valor de demanda de 0.41
      Q = Q * self.Curva_Demanda[0] # Valor de demanda de 0.41
      return P, Q
    
# ----------------------------------------------------------- Classes da bateria -----------------------------------------------------------
class Stack_Baterias:
  def __init__(self, id_bateria, fabricante_bateria, modelo_bateria, Tipo_bateria, Capacidade, I_charge_max, I_discharge_max, V_min, V_max, V_nom, DoD, Ciclo_vida):
    self.Bateria_Param = self.Param_Baterias(id_bateria, fabricante_bateria, modelo_bateria, Tipo_bateria, Capacidade, I_charge_max, I_discharge_max, V_min, V_max, V_nom, DoD, Ciclo_vida)
    self.acao_bateria = ["espera", 0]

    self.V_Baterias = []
    self.I_Baterias = []
    self.P_Baterias = []
    self.SOC = []

  def Simular_equipamento(self, Nm_baterias, agente_MQTT):
    if Var_globais.Passo_atual_global == 0:
      self.bateria_simulada = self.Simulacao_Baterias(self.Bateria_Param, Nm_baterias)

    if Var_globais.Passo_atual_global <= 1:
      print(f"bateria -- acao = {self.acao_bateria[0]}")
      print(f"bateria -- pot = {self.acao_bateria[1]}")

    V_pack, I_pack, P_bat, SOC_atual= self.bateria_simulada.Simula_Bateria(self.acao_bateria)
    self.Armazenar_Val_Baterias(V_pack, I_pack, P_bat, SOC_atual)

    agente_MQTT.publicar_msg( f"{self.Bateria_Param.id_bateria}/medicoes_bateria", {self.Bateria_Param.id_bateria: {"V_bat": V_pack, "I_pack": I_pack, "P_bat": P_bat}})
    agente_MQTT.publicar_msg( f"{self.Bateria_Param.id_bateria}/estado_bateria", {self.Bateria_Param.id_bateria: {"SOC": SOC_atual}})

  def receive(self, origem, tipo_origem, topico, mensagem):
    if topico == "saida_bateria":
      if self.Bateria_Param.id_bateria in mensagem:
        dados = mensagem[self.Bateria_Param.id_bateria]

        self.acao_bateria = np.array([dados.get("acao", "espera"), dados.get("Pot_requerida", 0)], dtype=object)
      return

  # ----------------- Dados Baterias --------------------- #
  def Armazenar_Val_Baterias(self, V_bat, I_bat, P_bat, SOC):
    self.V_Baterias.append(V_bat)
    self.I_Baterias.append(I_bat)
    self.P_Baterias.append(P_bat)
    self.SOC.append(SOC)
  
  def Retornar_Val_Baterias(self):
    return self.V_Baterias, self.I_Baterias, self.P_Baterias, self.SOC

  class Param_Baterias:
    def __init__(self, id_bateria, fabricante_bateria, modelo_bateria, Tipo_bateria, Capacidade, I_charge_max, I_discharge_max, V_min, V_max, V_nom, DoD, Ciclo_vida):
      self.id_bateria = id_bateria
      self.fabricante = fabricante_bateria
      self.modelo = modelo_bateria
      self.nome = self.fabricante + "-" + self.modelo

      self.tipo = Tipo_bateria
      self.capacidade = Capacidade
      self.I_CH_max = I_charge_max
      self.I_DC_max = I_discharge_max
      self.V_min = V_min
      self.V_max = V_max
      self.V_nom = V_nom
      self.DoD = DoD
      self.ciclos_vida_util = Ciclo_vida

      self.Cond_Iniciais_soc = [0.8]
      self.Tolerancia_relativa = 1e-8
      self.Metodo_EDO = 'RK45'

    def Retorna_Parametros_EDO(self):
      return self.Cond_Iniciais_soc, self.Tolerancia_relativa, self.Metodo_EDO

    def Retorna_Parametros_Datasheet(self):
      return self.capacidade, self.I_CH_max, self.I_DC_max, self.V_nom, self.DoD
    
    def Retorna_tabelas_consulta(self):
      SOC_table = np.array([0,0.01,0.02,0.03,0.04,0.05,0.06,0.07,0.08,0.09,0.1,0.11,0.12,0.13,0.14,0.15,0.16,0.17,0.18,0.19,0.2,0.21,0.22,0.23,0.24,0.25,0.26,
                            0.27,0.28,0.29,0.3,0.31,0.32,0.33,0.34,0.35,0.36,0.37,0.38,0.39,0.4,0.41,0.42,0.43,0.44,0.45,0.46,0.47,0.48,0.49,0.5,0.51,0.52,0.53,
                            0.54,0.55,0.56,0.57,0.58,0.59,0.6,0.61,0.62,0.63,0.64,0.65,0.66,0.67,0.68,0.69,0.7,0.71,0.72,0.73,0.74,0.75,0.76,0.77,0.78,0.79,0.8,
                            0.81,0.82,0.83,0.84,0.85,0.86,0.87,0.88,0.89,0.9,0.91,0.92,0.93,0.94,0.95,0.96,0.97,0.98,0.99,1])
      
      OCV_table = np.array([269.5, 271.9108897, 274.32172396, 276.73255821, 279.14344791,
                            281.55428217, 285.21178041, 288.31771286, 290.14094577, 291.83478331,
                            293.02545358, 293.9918718, 294.57570328, 294.99454734, 295.37031505,
                            295.60099806, 295.7507951, 295.95963501, 296.13471239, 296.29099583,
                            296.41201986, 296.50050102, 296.61858677, 296.71266729, 296.80508464,
                            296.88813274, 296.96735553, 297.05023731, 297.12957098, 297.20596636,
                            297.27914626, 297.34944332, 297.41613682, 297.46747363, 297.518755,
                            297.5724757, 297.63018804, 297.68784493, 297.73746312, 297.77549449,
                            297.81358131, 297.85161268, 297.88387836, 297.91858338, 297.95328839,
                            297.98799341, 298.02530407, 298.06255929, 298.09887205, 298.13113773,
                            298.16096408, 298.19023604, 298.21401951, 298.23774754, 298.26153101,
                            298.28625695, 298.31242431, 298.33936781, 298.36575693, 298.3908155,
                            298.41592952, 298.43904771, 298.46077993, 298.48179143, 298.50851318,
                            298.53529037, 298.57160313, 298.61163031, 298.6516575, 298.69168469,
                            298.72489284, 298.75311146, 298.78099744, 298.80694304, 298.83322128,
                            298.8603311, 298.88749637, 298.91604762, 298.94681644, 298.98606748,
                            299.02526308, 299.06451412, 299.10287813, 299.12865741, 299.15670971,
                            299.18470656, 299.21275886, 299.24358312, 299.27523897, 299.2971375,
                            299.3140465, 299.33328394, 299.35246594, 299.36787807, 299.40435715,
                            299.44959563, 299.48474416, 299.61269811, 299.80529431, 300.53182659,
                            307.1])
      
      return OCV_table, SOC_table

  class Simulacao_Baterias:
    def __init__(self, Baterias, Nm_baterias):
      self.capacidade, self.I_CH_max, self.I_DC_max, self.V_nom, self.DoD = Baterias.Retorna_Parametros_Datasheet()
      self.OCV_table, self.SOC_table  = Baterias.Retorna_tabelas_consulta()
      self.Cond_Iniciais_soc, self.Tolerancia_relativa, self.Metodo_EDO = Baterias.Retorna_Parametros_EDO()

      self.nm_baterias_serie = Nm_baterias[0]
      self.nm_baterias_paralelo = Nm_baterias[1]

      self.SOC_atual = self.Cond_Iniciais_soc[0]

      self.Tempo_Sim = 0  # Começa do tempo 0

      self.I_pack = 0
      self.V_pack = 0
      self.I_cell = 0
      self.V_cell = 0

    def Simula_Bateria(self, acao_bateria):
      self.acao_bateria = acao_bateria

      self.Sim_Bat_SOC()

      P_bat = self.V_pack * self.I_pack

      return self.V_pack, self.I_pack, P_bat, self.SOC_atual

    def Sim_Bat_SOC(self):
      sol_SOC = solve_ivp(self.EDO_SOC, (self.Tempo_Sim, self.Tempo_Sim + Var_globais.Passo_global), self.Cond_Iniciais_soc, method=self.Metodo_EDO, t_eval=[self.Tempo_Sim + Var_globais.Passo_global], rtol=self.Tolerancia_relativa)

      self.Cond_Iniciais_soc = sol_SOC.y[:, -1]  # Atualiza o estado da Tensão
      self.SOC_atual = self.Cond_Iniciais_soc[0]

      self.Tempo_Sim = sol_SOC.t[-1]  # Atualiza o tempo

      return self.SOC_atual
    
    def EDO_SOC(self, t, y):
      SOC = y[0]
      I = self.Corrente_Bateria()
      dSOC_dt = (1 / 3600) * (I / self.capacidade)
      return [dSOC_dt]

    def Corrente_Bateria(self):
      acao_bateria = self.acao_bateria[0]
      Pot_requerida = self.acao_bateria[1]

      # Atualiza tensões da bateria
      self.V_cell = self.Consulta_Vbat()
      self.V_pack = self.V_cell * self.nm_baterias_serie

      # Evita divisão por zero
      if self.V_pack == 0:
        self.I_pack = 0
        self.I_cell = 0
        return self.I_cell

      if acao_bateria == "carregar":
        # Potência requerida deve gerar corrente NEGATIVA
        self.I_pack = - Pot_requerida / self.V_pack

      elif acao_bateria == "descarregar":
        # Potência requerida gera corrente POSITIVA
        self.I_pack = Pot_requerida / self.V_pack

      else:
        # Espera (Standby)
        self.I_pack = 0

      # Distribui corrente por célula
      self.I_cell = 0 if self.I_pack == 0 else self.I_pack / self.nm_baterias_paralelo

      if acao_bateria == "descarregar" and self.I_cell > self.I_DC_max: # Se estiver descarregando e a corrente for maior que o valor maximo de descarga
        self.I_cell = self.I_DC_max
        self.I_pack = self.I_cell * self.nm_baterias_paralelo

      elif acao_bateria == "carregar" and abs(self.I_cell) > self.I_CH_max: # Se estiver carregando e a corrente for maior que o valor maximo de carga
        self.I_cell = -self.I_CH_max
        self.I_pack = self.I_cell * self.nm_baterias_paralelo

      return self.I_cell
    
    def Consulta_Vbat(self):
      if Var_globais.Passo_atual_global == 0:
        V_bat = np.interp(self.Cond_Iniciais_soc[0], self.SOC_table, self.OCV_table)
      else:
        V_bat = np.interp(self.SOC_atual, self.SOC_table, self.OCV_table)
      
      return V_bat

# ----------------------------------------------------------- Classes do clima -----------------------------------------------------------
class Clima_Ambiente:
  def __init__(self, clima_id, nome_cidade, pais, data):
    self.clima_id = clima_id
    self.nome_cidade = nome_cidade
    self.pais = pais
    self.data = data

    self.latitude = 0
    self.longitude = 0
    self.Temperatura = 0
    self.Irradiancia = 0

    self.Temperatura_Base = 25
    self.Irradiancia_Base = 1000

    self.Temperatura_Atual = self.Temperatura_Base
    self.Irradiancia_Atual = self.Irradiancia_Base

    # self.Obter_Dados_Cidade()
    # self.Temperatura_Interpolada = self.Arruma_Array(self.Temperatura, "T")
    # self.Irradiancia_Interpolada = self.Arruma_Array(self.Irradiancia, "G")

  def aplicar_Mudanca_Ambiental(self, falhas_clima):
    tempo_atual = Var_globais.Passo_global * Var_globais.Passo_atual_global
    tolerancia = Var_globais.Passo_global

    # Dicionário para rastrear mudanças ativas (se ainda não existir)
    if not hasattr(self, "mudancas_ativas"):
      self.mudancas_ativas = {}

    for falha in falhas_clima:
      tipo = falha["Tipo_Falha"]
      tempos_falha = falha["T_falha"]
      duracoes = falha["duracao_falha"]

      for i, t_falha in enumerate(tempos_falha):
        duracao = duracoes[i] if i < len(duracoes) else None

        # Ativação da mudança
        if abs(tempo_atual - t_falha) < tolerancia:
          if tipo == "Mudanca_Irradiancia":
            self.mudancas_ativas["irradiancia"] = {
              "inicio": tempo_atual,
              "duracao": duracao,
              "valor_base": getattr(self, "Irradiancia_Base", self.Irradiancia_Atual)
            }
            self.Irradiancia_Atual = falha["Val_Irrad"][i]
            print(f"[{tempo_atual}s] Irradiância alterada para {self.Irradiancia_Atual} W/m²")

          elif tipo == "Mudanca_Temperatura":
            self.mudancas_ativas["temperatura"] = {
              "inicio": tempo_atual,
              "duracao": duracao,
              "valor_base": getattr(self, "Temperatura_Base", self.Temperatura_Atual)
            }
            self.Temperatura_Atual = falha["Val_Temp"][i]
            print(f"[{tempo_atual}s] Temperatura alterada para {self.Temperatura_Atual} °C")

    # Desativação das mudanças quando a duração expira
    for chave, dados in list(self.mudancas_ativas.items()):
      if dados["duracao"] is not None:
        if tempo_atual - dados["inicio"] >= dados["duracao"]:
          if chave == "irradiancia":
            self.Irradiancia_Atual = dados["valor_base"]
            print(f"[{tempo_atual}s] Irradiância restaurada para {self.Irradiancia_Atual} W/m²")
          elif chave == "temperatura":
            self.Temperatura_Atual = dados["valor_base"]
            print(f"[{tempo_atual}s] Temperatura restaurada para {self.Temperatura_Atual} °C")

          del self.mudancas_ativas[chave]

  def Simular_Clima(self, falhas_clima, agente_MQTT):
    self.aplicar_Mudanca_Ambiental(falhas_clima)

    agente_MQTT.publicar_msg( f"{self.clima_id}/dados_climaticos", {self.clima_id: {"T": self.Temperatura_Atual, "G": self.Irradiancia_Atual}})

  def Retorna_Curvas(self):
    return self.Temperatura_Interpolada, self.Irradiancia_Interpolada

  def Retorna_Array(self):
    return self.Temperatura, self.Irradiancia

  def Obter_Dados_Cidade(self):
    # Etapa 1: Obter latitude e longitude
    url_nominatim = "https://nominatim.openstreetmap.org/search"
    params_nominatim = {
        'q': f"{self.nome_cidade}, {self.pais}",
        'format': 'json',
        'limit': 1,
        'addressdetails': 1
    }
    headers_nominatim = {
        'User-Agent': 'YourAppName/1.0 (your.email@domain.com)',
        'Referer': 'https://yourdomain.com'
    }

    response = requests.get(url_nominatim, params=params_nominatim, headers=headers_nominatim)

    if response.status_code == 200:
        data_nominatim = response.json()
        if not data_nominatim:
            raise ValueError("Cidade não encontrada.")
        latitude = float(data_nominatim[0]['lat'])
        longitude = float(data_nominatim[0]['lon'])
    else:
        raise ConnectionError(f"Erro na requisição Nominatim: {response.status_code}")

    # Etapa 2: Obter dados climáticos
    base_url_nasa = "https://power.larc.nasa.gov/api/temporal/hourly/point?"
    api_url_nasa = (
        f"{base_url_nasa}"
        f"start={self.data}&end={self.data}&"
        f"latitude={latitude}&longitude={longitude}&"
        f"community=ag&parameters=ALLSKY_SFC_SW_DWN,T2M&"
        f"format=json&header=true&time-standard=utc"
    )

    response = requests.get(api_url_nasa)

    if response.status_code == 200:
        data_nasa = response.json()
        try:
            allsky_data = data_nasa["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
            t2m_data = data_nasa["properties"]["parameter"]["T2M"]
        except KeyError:
            raise KeyError("Dados de irradiância ou temperatura não encontrados na resposta da API.")

        array_irradiancia = list(allsky_data.values())
        array_temperatura = list(t2m_data.values())

        array_irradiancia = np.roll(array_irradiancia, -3)
        array_temperatura = np.roll(array_temperatura, -3)
        print("Sucesso na requisição NASA")
    else:
        raise ConnectionError(f"Erro na requisição NASA: {response.status_code}")

    self.latitude = latitude
    self.longitude = longitude
    self.Temperatura = array_temperatura
    self.Irradiancia = array_irradiancia

    return 1

  def Arruma_Array(self, array, tipo):
    t = np.linspace(0, 23, Var_globais.Resolucao_Clima)

    if tipo == 'G':
      array = np.array(array) * 1000 / 2.5

    array[array == 0] = 1
    tempo_original = np.linspace(0, len(array) - 1, len(array))
    interp = interp1d(tempo_original, array, kind='cubic', fill_value="extrapolate")
    curva_interpolada = interp(t)
    curva_interpolada = np.clip(curva_interpolada, 0.5, None)

    return curva_interpolada

  def Retorna_Valores(self):
    return self.Temperatura_Atual, self.Irradiancia_Atual

# ----------------------------------------------------------- Classes do barramento -----------------------------------------------------------
class Barramento:
  def __init__(self, id_barramento, tipo, nm_fases, V_linha_nominal, V_fase_nominal, V_min, V_max):
    self.barramento_Param = self.Param_barramento(id_barramento, tipo, nm_fases, V_linha_nominal, V_fase_nominal, V_min, V_max)
    self.barramento_simulado = self.Simulacao_Barramento(self.barramento_Param)

    self.id_bus = id_barramento
    if nm_fases > 1:
      self.V_bus = V_linha_nominal
    else:
      self.V_bus = V_fase_nominal

    self.V_ac_rms = None
    self.V_ac_rms = None

    self.S_gerada_gerada = None
    self.P_gerada = None
    self.Q_gerada = None

    self.buffer_mensagens = {
      "Inversor": {
        "saida_ac": {}
      },
      "Carga": {
        "demanda_carga": {}
      },
      "Rede": {
        "Grandezas_rede": {}
      }
    }

  def Simular_barramento(self, agente_MQTT):
    
    matriz_inversores = self.Obter_valores_inversores()
    matriz_cargas = self.Obter_valores_cargas()
    dados_rede = self.Obter_valores_rede()

    pot_demandada_inversor, saida_para_carga, saida_para_rede = self.barramento_simulado.Simula_barramento(matriz_inversores, matriz_cargas, dados_rede)

    if Var_globais.Passo_atual_global == 0:
      print(f"matriz_inversores = {matriz_inversores}")
      print(f"matriz_cargas = {matriz_cargas}")
      print(f"dados_rede = {dados_rede}")
      print(f"pot_demandada_inversor = {pot_demandada_inversor}")
      print(f"saida_para_carga = {saida_para_carga}")

    self.V_bus = saida_para_carga[0][1]

    msg_inversor = { str(linha[0]): {"P_demandada": float(linha[1]), "Q_demandada": float(linha[2]), } for linha in pot_demandada_inversor }
    agente_MQTT.publicar_msg( f"{self.id_bus}/p_demandada", msg_inversor)

    msg_param_bar = { str(linha[0]): {"V_bus": self.V_bus} for linha in pot_demandada_inversor }
    agente_MQTT.publicar_msg( f"{self.id_bus}/parametros_barramento", msg_param_bar)

    msg_carga = { str(linha[0]): {"V_recebida": linha[1], "I_recebida": linha[2], "P_recebida": linha[3], "Q_recebida": linha[3]} for linha in saida_para_carga }
    agente_MQTT.publicar_msg( f"{self.id_bus}/grandezas_ac", msg_carga)

    # msg_rede = { str(linha[0]): {"P_grid_requerida": linha[1], "Q_grid_requerida": linha[2]} for linha in saida_para_rede }
    # agente_MQTT.publicar_msg( f"{self.id_bus}/P_requerida_rede", msg_rede)

  def receive(self, origem, tipo_origem, topico, mensagem):
    """
    origem: "PV_1", "BAT_1", "INV_1"...
    tipo_origem: "rede", "Carga", "Inversor", ...
    topico: "medicoes_pv", "estado_bateria", etc.
    mensagem: dict padronizado
    """

    # Verifica tipo
    if tipo_origem not in self.buffer_mensagens:
        print(f"[Barramento] Tipo inesperado '{tipo_origem}'.")
        return

    # Verifica tópico
    if topico not in self.buffer_mensagens[tipo_origem]:
        print(f"[Barramento] Tópico '{topico}' não pertence ao tipo '{tipo_origem}'.")
        return

    if origem not in mensagem:
        print(f"[Barramento] Mensagem recebida mas ID '{origem}' não está dentro da mensagem.")
        return

    dados_extraidos = mensagem[origem]   # <- pega só o conteúdo interno

    self.buffer_mensagens[tipo_origem][topico][origem] = dados_extraidos

  def Obter_valores_inversores(self):

    lista_inversor = []

    medicoes_inversor = self.buffer_mensagens["Inversor"]["saida_ac"]

    for origem, dados in medicoes_inversor.items():
      # Verifica se TODOS os parâmetros foram enviados
      if "V_ac_rms" not in dados or "I_ac_rms" not in dados or "V_ac_onda" not in dados or "I_ac_onda" not in dados:
        print(f"[barramento] Aviso: inversor {origem} não enviou os dados necessários.")
        continue

      V_ac_rms = float(dados["V_ac_rms"])
      I_ac_rms = float(dados["I_ac_rms"])
      V_ac_onda = float(dados["V_ac_onda"])
      I_ac_onda = float(dados["I_ac_onda"])

      # Linha da matriz
      lista_inversor.append([origem, V_ac_rms, I_ac_rms, V_ac_onda, I_ac_onda])

    # Converte lista → matriz numpy
    matriz_inversor = np.array(lista_inversor, dtype=object)
    return matriz_inversor

  def Obter_valores_cargas(self):

    lista_cargas = []

    medicoes_cargas = self.buffer_mensagens["Carga"]["demanda_carga"]
    
    for origem, dados in medicoes_cargas.items():
      # Verifica se TODOS os parâmetros foram enviados
      if "P_demandada" not in dados or "Q_demandada" not in dados:
        print(f"[barramento] Aviso: carga {origem} não enviou os dados necessários.")
        continue

      P_demandada = float(dados["P_demandada"])
      Q_demandada = float(dados["Q_demandada"])

      # Linha da matriz
      lista_cargas.append([origem, P_demandada, Q_demandada])

    # Converte lista → matriz numpy
    matriz_carga = np.array(lista_cargas, dtype=object)
    return matriz_carga
  
  def Obter_valores_rede(self):
    Valores_rede = []

    grandezas_rede = self.buffer_mensagens["Rede"]["Grandezas_rede"]
    
    for origem, dados in grandezas_rede.items():
      # Verifica se TODOS os parâmetros foram enviados
      if "V_rede" not in dados or "I_rede" not in dados or "P_rede" not in dados or "Q_rede" not in dados:
        print(f"[barramento] Aviso: Rede {origem} não enviou os dados necessários.")
        continue

      V_rms_rede = float(dados["V_rede"])
      I_rms_rede = float(dados["I_rede"])
      P_rms_rede = float(dados["P_rede"])
      Q_rms_rede = float(dados["Q_rede"])

      # Linha da matriz
      Valores_rede.append([origem, V_rms_rede, I_rms_rede, P_rms_rede, Q_rms_rede])

    # Converte lista → matriz numpy
    dados_rede = np.array(Valores_rede, dtype=object)
    return dados_rede

  class Param_barramento:
    def __init__(self, id_barramento, tipo, nm_fases, V_linha_nominal, V_fase_nominal, V_min, V_max):
      self.id_barramento = id_barramento
      self.tipo = tipo
      self.nm_fases = nm_fases
      self.V_linha_nominal = V_linha_nominal
      self.V_fase_nominal = V_fase_nominal
      self.V_min = V_min
      self.V_max = V_max

  class Simulacao_Barramento:
    def __init__(self, barramento_Param):
      self.barramento_Param = barramento_Param

      self.nm_fases = self.barramento_Param.nm_fases

      self.FP_sistema = 1

      self.contador = 0
      self.flag_cont = 0

      self.array_Pdem_total = []
      self.array_Pfv_disponivel = []
      self.P_total_disponivel = []

    def Simula_barramento(self, matriz_inversores, matriz_cargas, dados_rede):
      #--------------------
      # cálculo do balanço de potência no passo atual
      #--------------------
      self.array_Pdem_total = self.calcula_Ptotal_demandada(matriz_cargas)              # verifica o quanto as cargas precisam de potencia
      self.array_Pfv_disponivel = self.calcula_Ptotal_inversores(matriz_inversores)     # verifica o quanto os inversores estão entregando de potencia
      self.P_total_disponivel = self.calcula_Ptotal_disponivel(dados_rede)

      #--------------------
      # cálculo do balanço de potência para o próximo passo
      #--------------------

      pot_demandada_inversor = self.Distribui_P_para_inversores(matriz_inversores)
      saida_para_carga = self.Distribui_P_para_Cargas(matriz_inversores, matriz_cargas)
      saida_para_rede = self.Distribui_P_para_rede()

      return pot_demandada_inversor, saida_para_carga, saida_para_rede

    def calcula_Ptotal_inversores(self, matriz_inversores):
      if len(matriz_inversores) == 0:
        return np.array([0, 0])
      
      FP_inv = self.FP_sistema

      P_inv_total = 0.0
      Q_inv_total = 0.0

      for linha in matriz_inversores:
        V_rms = float(linha[1])   # linha se trifásico, fase se monofásico
        I_rms = float(linha[2])

        if self.nm_fases == 1:            # Monofásico
          P_inv = V_rms * I_rms * FP_inv
          Q_inv = V_rms * I_rms * np.sqrt(1 - (FP_inv*FP_inv))
        elif self.nm_fases > 1:           # Trifásico: valores de linha
          P_inv = np.sqrt(3) * V_rms * I_rms * FP_inv
          Q_inv = V_rms * I_rms * np.sqrt(1 - (FP_inv*FP_inv)) * np.sqrt(3)
        else:
          raise ValueError(f"nm_fases inválido: {self.nm_fases}")

        P_inv_total += P_inv
        Q_inv_total += Q_inv
      
      return np.array([P_inv_total, Q_inv_total])

    def calcula_Ptotal_demandada(self, matriz_cargas):
      if len(matriz_cargas) == 0:
        return np.array([0, 0])
  
      P_carga_total = sum(float(linha[1]) for linha in matriz_cargas)
      Q_carga_total = sum(float(linha[2]) for linha in matriz_cargas)

      S_carga = np.sqrt(P_carga_total**2 + Q_carga_total**2)

      FP = 1.0 if S_carga == 0 else P_carga_total / S_carga   # fator de potência da carga
      FP = max(0.01, FP)  # evitar divisão por zero

      self.FP_sistema = FP

      return np.array([P_carga_total, Q_carga_total])

    def calcula_Ptotal_disponivel(self, dados_rede):
      matriz_saida = []

      if len(dados_rede) == 0:
        Prede_total = 0
        Qrede_total = 0
      else:
        Prede_total = dados_rede[0]
        Qrede_total = dados_rede[1]
    
      Pfv_total = self.array_Pfv_disponivel[0]
      Qfv_total = self.array_Pfv_disponivel[1]


      # Soma todas as potências pra calcular qual o valor total disponível de potência
      P_total_disponivel = Pfv_total + Prede_total
      Q_total_disponivel = Qfv_total + Qrede_total

      matriz_saida = [P_total_disponivel, Q_total_disponivel]
      return np.array(matriz_saida)


    def Distribui_P_para_inversores(self, matriz_inversores):
      """
      Recebe:
        - matriz_inversores: np.array([[id_inv, V_ac_rms, I_ac_rms, V_ac_onda, I_ac_onda], ...])
        - matriz_cargas:     np.array([[id_carga, P_demandada, Q_demandada], ...])

      Retorna:
        np.array([[id_inversor, P_requerida, Q_requerida], ...])
      """
      matriz_saida = []

      Pdem_total = self.array_Pdem_total[0]
      Qdem_total = self.array_Pdem_total[1]

      Pfv_total = self.array_Pfv_disponivel[0]
      Qfv_total = self.array_Pfv_disponivel[1]

      n_inv = len(matriz_inversores)
      if n_inv == 0:
          raise ValueError("Nenhum inversor disponível para distribuir potência.")

      for linha in matriz_inversores:        # cria array que pede potencia maxima
        id_inv = linha[0]
        V_rms = linha[1]
        I_rms = linha[2]

        if self.nm_fases == 1:            # Monofásico
          P = V_rms * I_rms * self.FP_sistema
          Q = V_rms * I_rms * np.sqrt(1 - (self.FP_sistema*self.FP_sistema))
        elif self.nm_fases > 1:           # Trifásico
          P = np.sqrt(3) * V_rms * I_rms * self.FP_sistema
          Q = V_rms * I_rms * np.sqrt(1 - (self.FP_sistema*self.FP_sistema)) * np.sqrt(3)

        if Pfv_total > 500:
          P_percent = P / Pfv_total
          Q_percent = Q / Qfv_total

          P_requerido = P_percent * Pdem_total + 1
          Q_requerido = Q_percent * Qdem_total + 1
        else:
          P_requerido = Pdem_total / n_inv
          Q_requerido = Qdem_total / n_inv
          
        matriz_saida.append([id_inv, P_requerido, Q_requerido])

      return np.array(matriz_saida, dtype=object)

    def Distribui_P_para_rede(self):
      matriz_saida = []

      if Var_globais.flag_ongrid == False:
        matriz_saida = [0, 0]
        return np.array(matriz_saida)
    
      Pgrid_requerida = self.array_Pdem_total[0] - self.array_Pfv_disponivel[0]
      Qgrid_requerida = self.array_Pdem_total[1] - self.array_Pfv_disponivel[1]

      matriz_saida.append([Pgrid_requerida, Qgrid_requerida])
      return np.array(matriz_saida, dtype=object)

    def Distribui_P_para_Cargas(self, matriz_inversores, matriz_cargas):
      """
      Recebe matrizes de inversores e cargas e verifica se a potência dos inversores
      atende exatamente a soma das potências das cargas.

      Retorna:
        [[id_carga, V_rms_entregue, I_rms_entregue, P_rms_entregue, Q_rms_entregue], ...]
      """
      matriz_saida = []    
      V_barramento = np.mean([float(linha[1]) for linha in matriz_inversores])

      P_restante = self.P_total_disponivel[0]
      Q_restante = self.P_total_disponivel[1]

      for linha in matriz_cargas:
        id_carga = linha[0]

        P_requerido = float(linha[1])
        Q_requerido = float(linha[2])
        
        if P_restante >= P_requerido:
          P_entregue = P_requerido
          Q_entregue = Q_requerido
        else:
          P_entregue = P_restante
          Q_entregue = Q_restante
        
        P_restante -= P_entregue
        Q_restante -= Q_entregue


        I_entregue = np.float64(0.0) if V_barramento == 0 else P_entregue / (V_barramento * self.FP_sistema)

        matriz_saida.append([id_carga, V_barramento, I_entregue, P_entregue, Q_entregue])

      return np.array(matriz_saida, dtype=object)

# ----------------------------------------------------------- Classes do MQTT -----------------------------------------------------------
class Agente_Mensagem:
  def __init__(self):
    self.subscribers = {}   # topic → [agentes]
    self.messages = []      # fila de mensagens publicadas

  def inscrever_topico(self, agent, topic):
    """Agente se inscreve em um tópico."""
    self.subscribers.setdefault(topic, []).append(agent)

  def publicar_msg(self, topic, message):
    """Publica uma mensagem em um tópico."""
    self.messages.append((topic, message))

  def entrega_msg(self):
    """Entrega todas as mensagens para os inscritos."""
    while self.messages:
      topic, message = self.messages.pop(0)

      if topic not in self.subscribers:
        continue

      # Extrai <origem>/<topico>
      try:
          origem, topico_bruto = topic.split("/")
      except ValueError:
          print(f"[MQTT] Tópico mal-formatado: {topic}")
          continue

      # Identifica o tipo pelo prefixo do ID
      if origem.startswith("PV"):
        tipo_origem = "Painel"
      elif origem.startswith("Batt"):
        tipo_origem = "Bateria"
      elif origem.startswith("Load"):
        tipo_origem = "Carga"
      elif origem.startswith("Inv"):
        tipo_origem = "Inversor"
      elif origem.startswith("Bus"):
        tipo_origem = "Barramento"
      elif origem.startswith("Clima"):
        tipo_origem = "Clima"
      elif origem.startswith("Rede"):
        tipo_origem = "Rede"
      else:
        tipo_origem = "Desconhecido"

      # Entrega padronizada
      for agent in self.subscribers[topic]:
        agent.receive(origem, tipo_origem, topico_bruto, message)

  def obter_mapa_inscricao(self):
    """Define as regras de quais tipos de tópicos um Agente Vizinho se inscreve."""
    # Chave: Tipo do Agente Vizinho (Quem se inscreve)
    # Valor: Dicionário onde a chave é o Tipo da Origem (Quem publica)
    #        e o valor é a lista de nomes de tópicos (sufixos) relevantes
    return {
      "Painel": {
        "Inversor": ["saida_mppt"], 
        "Clima_Ambiente": ["dados_climaticos"],
      },
      "Inversor": {
        "Painel": ["medicoes_pv"],
        "Bateria": ["medicoes_bateria", "estado_bateria"],
        "Barramento": ["parametros_barramento", "p_demandada"],
      },
      "Bateria": {
        "Inversor": ["saida_bateria"],
      },
      "Carga": {
        "Barramento": ["grandezas_ac"],
      },
      "Barramento": {
        "Inversor": ["saida_ac"],
        "Carga": ["demanda_carga", "parametros_carga"],
        "Rede": ["grandezas_rede"],
      },
      "Rede": {
        "Barramento": ["P_requerida_rede"],
      },
      "Clima_Ambiente": {
        # O clima não se inscreve em nada
      }
    }

  def criar_topicos_por_topologia(self, grafo, equipamentos):

    # 1️⃣ Mapeamento de Configuração
    
    topicos_por_tipo = {
        "Painel": ["medicoes_pv"],
        "Inversor": ["saida_mppt", "saida_ac", "saida_bateria"],
        "Bateria": ["medicoes_bateria", "estado_bateria"],
        "Carga": ["demanda_carga", "parametros_carga"],
        "Barramento": ["grandezas_ac", "p_demandada", "parametros_barramento"],
        "Rede": ["grandezas_rede"],
        "Clima_Ambiente": ["dados_climaticos"],
    }

    mapear_classe_para_tipo = {
        "Painel_Fotovoltaico": "Painel",
        "Inversor_DC_AC": "Inversor",
        "Stack_Baterias": "Bateria",
        "Carga_ZIP": "Carga",
        "Barramento": "Barramento",
        "Rede_Eletrica": "Rede",
        "Clima_Ambiente": "Clima_Ambiente"
    }
    
    mapa_inscricao = self.obter_mapa_inscricao()

    topicos_de_cada_equip = {}

    # 2️⃣ Criar tópicos
    for eq_id, info in equipamentos.items():

        obj = info["obj"]
        nome_classe = type(obj).__name__
        tipo = mapear_classe_para_tipo.get(nome_classe)

        if tipo is None:
            raise ValueError(f"Classe desconhecida: {nome_classe}")

        lista_topicos = [
            f"{eq_id}/{t}" for t in topicos_por_tipo[tipo] # ⚠️ topicos_por_tipo é acessado aqui!
        ]

        topicos_de_cada_equip[eq_id] = {
            "agente": obj,
            "topicos": lista_topicos,
            "tipo": tipo # Guardar o tipo para facilitar o filtro
        }

    # 3️⃣ Processamento do Grafo e Assinaturas
    
    inscricoes_diretas = set() # ⚠️ inscricoes_diretas é acessado aqui!
    
    # 🟢 3.1: Identificar Busses e criar regras de inscrição para vizinhos indiretos
    busses = {node for node in grafo if node not in equipamentos}
    
    for bus_id in busses:
        # Encontrar todos os equipamentos agentes conectados ao Bus
        equipamentos_conectados = [eq for eq in grafo[bus_id] if eq in equipamentos]
        
        # Forçar a inscrição mútua entre todos os equipamentos conectados ao mesmo Bus
        for i in range(len(equipamentos_conectados)):
            for j in range(i + 1, len(equipamentos_conectados)):
                eq1 = equipamentos_conectados[i]
                eq2 = equipamentos_conectados[j]
                
                inscricoes_diretas.add((eq1, eq2)) # A se inscreve em B
                inscricoes_diretas.add((eq2, eq1)) # B se inscreve em A

    # 🟠 3.2: Iterar sobre todas as conexões (Bus-forçadas e diretas) e aplicar a inscrição com filtro

    # Lista de todas as tuplas (origem, vizinho) que precisam de inscrição:
    todas_conexoes = inscricoes_diretas.copy()

    # Adicionar todas as conexões diretas (não-bus) para garantir que elas também sejam filtradas
    for origem, vizinhos in grafo.items():
        if origem not in equipamentos: continue # Ignora se a origem for um Bus
        for vizinho in vizinhos:
            if vizinho not in equipamentos: continue # Ignora se o vizinho for um Bus
            # Adiciona a conexão direta, o set garante que não haverá duplicatas com as regras do Bus
            todas_conexoes.add((origem, vizinho))
    
    # Aplicar o filtro e a inscrição:
    for origem_id, vizinho_id in todas_conexoes:
        
        # Recuperar informações dos equipamentos envolvidos
        origem_info = topicos_de_cada_equip[origem_id]
        vizinho_info = topicos_de_cada_equip[vizinho_id]
        
        tipo_origem = origem_info["tipo"]
        tipo_vizinho = vizinho_info["tipo"]
        agente_vizinho = vizinho_info["agente"]

        # Encontrar os tópicos desejados usando o mapa de inscrição
        topicos_sufixos_desejados = mapa_inscricao.get(tipo_vizinho, {}).get(tipo_origem, [])
        
        if not topicos_sufixos_desejados:
            continue # O Vizinho não precisa de nenhum tópico específico desta Origem

        # Realizar a inscrição apenas nos tópicos filtrados
        for topico_sufixo in topicos_sufixos_desejados:
            topico_completo = f"{origem_id}/{topico_sufixo}"
            
            # Garante que o tópico existe antes de inscrever
            if topico_completo in origem_info["topicos"]:
                self.inscrever_topico(agente_vizinho, topico_completo)
        
    return topicos_de_cada_equip

# ----------------------------------------------------------- A fazer ------------------------------------------------------------------------------

class Rede_Eletrica:
  def __init__(self, id_rede, fases, f_nom, V_linha_nominal, V_fase_nominal, Harmonicos_amp, Harmonicos_ordem, Desbalanco_amp):
    self.id_rede = id_rede

    self.rede_param = self.Param_rede(id_rede, fases, f_nom, V_linha_nominal, V_fase_nominal, Harmonicos_amp, Harmonicos_ordem, Desbalanco_amp)
    self.amb_simulacao = self.Simulacao_rede(self.rede_param)
    
    self.P_demandada = 0
    self.Q_demandada = 0
    self.Matriz_pot = np.array([self.P_demandada, self.Q_demandada])

    self.buffer_mensagens = {
      "Barramento": {
        "p_demandada": {}
      }
    }

  def Simular_rede(self, agente_MQTT):
    self.Ler_pot_demandada()

    v_instantaneo, i_instantaneo = self.amb_simulacao.simula_rede(self.Matriz_pot)
    P_instantaneo = v_instantaneo*i_instantaneo

    agente_MQTT.publicar_msg( f"{self.id_rede}/grandezas_rede", { self.id_rede: {"V_rede": v_instantaneo, "I_rede": i_instantaneo, "P_rede": P_instantaneo, "Q_rede": P_instantaneo}})

  def Ler_pot_demandada(self):
    demanda = self.buffer_mensagens["Barramento"]["p_demandada"]

    if len(demanda) > 0:
      _, dados = next(iter(demanda_carga.items()))
      P_demandada = dados.get("P_demandada", 0.0)
    else:
      P_demandada = 0.0

    # -------- Agrupa --------
    self.Matriz_pot = np.array([P_demandada, Q_demandada])

  def receive(self, origem, tipo_origem, topico, mensagem):
    """
    origem: "PV_1", "BAT_1", "INV_1"...
    tipo_origem: "Painel", "Bateria", "Carga", "Inversor", ...
    topico: "medicoes_pv", "estado_bateria", etc.
    mensagem: dict padronizado
    """
    # Verifica tipo
    if tipo_origem not in self.buffer_mensagens:
        print(f"[Rede] Tipo inesperado '{tipo_origem}'.")
        return

    # Verifica tópico
    if topico not in self.buffer_mensagens[tipo_origem]:
        print(f"[Rede] Tópico '{topico}' não pertence ao tipo '{tipo_origem}'.")
        return

    if (origem not in mensagem) and (self.Inversor_Param.id_inv not in mensagem):
        print(f"[Rede] Mensagem recebida mas receptor da mensagem não reconhecido.")
        return

    dados_extraidos = mensagem[self.id_rede]
    self.buffer_mensagens[tipo_origem][topico][origem] = dados_extraidos

  class Param_rede:
    def __init__(self, id_rede, fases, f_nom, V_linha_nominal, V_fase_nominal, Harmonicos_amp, Harmonicos_ordem, Desbalanco_amp):
      self.id_rede = id_rede
      self.nm_fases = fases
      self.f_nom = f_nom
      self.V_linha_nominal = V_linha_nominal
      self.V_fase_nominal = V_fase_nominal
      self.Harmonicos_amp = Harmonicos_amp
      self.Harmonicos_ordem = Harmonicos_ordem
      self.Desbalanco_amp = Desbalanco_amp

    def retorna_param_nominais(self):
      return  self.f_nom, self.V_linha_nominal, self.nm_fases

  class Simulacao_rede:
    def __init__(self, rede_param):
      self.f_nom, self.V_linha_nominal, self.nm_fases = rede_param.retorna_param_nominais()
      
      self.Vp = np.sqrt(2) * self.V_linha_nominal
      self.omega = 2 * np.pi * self.f_nom
      self.theta = 0
      self.dtheta = self.omega * Var_globais.Passo_global

    def simula_rede(self):

      va = self.Vp * np.sin(self.theta)

      if self.nm_fases == 3:
        vb = self.Vp * np.sin(self.theta - 2*np.pi/3)
        vc = self.Vp * np.sin(self.theta + 2*np.pi/3)
      else:
        vb = None
        vc = None

      v_instantaneo = np.array([va, vb, vc])
      i_instantaneo = np.array([va, vb, vc])

      self.theta += self.dtheta
      self.theta = np.mod(self.theta, 2*np.pi)

      return v_instantaneo, i_instantaneo


""""  Outras EQ da Rede
  def simula_rede(self):
    R_L1, L_L1, R_S1, L_S1, R_L2, L_L2, R_S2, L_S2 = self.calcula_impedancias()
    M_phase, K_phase = self.phase_blocks(R_S1,L_S1, R_L1,L_L1, R_S2,L_S2, R_L2,L_L2)
    self.M = np.zeros((9,9))
    self.K = np.zeros((9,9))
    for b in range(3):
        i0 = 3*b
        self.M[i0:i0+3, i0:i0+3] = M_phase
        self.K[i0:i0+3, i0:i0+3] = K_phase
    
    x0 = np.zeros(9)

    sol = solve_ivp(self.rhs, (self.Tempo_Sim, self.Tempo_Sim + Var_globais.Passo_global), x0, method=self.Metodo_EDO, t_eval=[self.Tempo_Sim + Var_globais.Passo_global], rtol=self.Tolerancia_relativa)
    self.Tempo_Sim = sol.t[-1]  # Atualiza o tempo

    i_s1 = sol.y[0:9:3, :]  # shape (3 fases, Nt)
    i_L1 = sol.y[1:9:3, :]
    i_s2 = sol.y[2:9:3, :]  # = i_L2

    # Derivadas para tensões nas cargas
    dt = Var_globais.Passo_global
    di_L1_dt = np.gradient(i_L1, dt, axis=1)
    di_s2_dt  = np.gradient(i_s2,  dt, axis=1)

    # Tensões de fase nos PCCs:
    # v1 = R_L1*i_L1 + L_L1*di_L1/dt
    # v2 = R_L2*i_s2 + L_L2*di_s2/dt
    v1 = R_L1*i_L1 + L_L1*di_L1_dt
    v2 = R_L2*i_s2 + L_L2*di_s2_dt

    # Corrente do trafo (por fase) = corrente no trecho 1
    I_traf = i_s1

  def RL_from_S_pf(self, S, pf):
    I_rms_line = S/(np.sqrt(3)*self.V_ll_rms)  # corrente de linha (rms)
    Zmag = self.V_ln_rms / I_rms_line          # impedância por fase (módulo)
    R = Zmag * pf
    XL = Zmag*np.sqrt(max(0.0,1.0-pf**2))
    L = XL/self.omega
    if S == 0:
        return 1e15, 1e15

    return R, L

  def calcula_impedancias(self):
    R_L1, L_L1 = self.RL_from_S_pf(S1, pf1)
    R_L2, L_L2 = self.RL_from_S_pf(S2, pf2)
    R_S1 = self.R_linha * self.d1
    L_S1 = self.L_linha * self.d1
    R_S2 = self.R_linha * (self.d2 - self.d1)
    L_S2 = self.L_linha * (self.d2 - self.d1)

    return R_L1, L_L1, R_S1, L_S1, R_L2, L_L2, R_S2, L_S2 

  def v_trafo_phase(self, t):
    Vpk = self.V_ln_rms*np.sqrt(2)
    Va = Vpk*np.sin(self.omega*t)
    Vb = Vpk*np.sin(self.omega*t - 2*np.pi/3)
    Vc = Vpk*np.sin(self.omega*t + 2*np.pi/3)
    return np.array([Va, Vb, Vc])  # shape (3,)

  def phase_blocks(self, Rs1,Ls1, RL1,LL1, Rs2,Ls2, RL2,LL2):
    M = np.array([
        [Ls1,      LL1,          0.0],
        [0.0,     -LL1,    Ls2 + LL2],
        [1.0,     -1.0,        -1.0]
    ], dtype=float)

    K = np.array([
        [Rs1,      RL1,          0.0],
        [0.0,     -RL1,    Rs2 + RL2],
        [0.0,      0.0,         0.0]
    ], dtype=float)
    return M, K

  def f_vector(self, t):
    f = np.zeros(9)
    vt = self.v_trafo_phase(t)  # [Va,Vb,Vc]
    f[0] = vt[0]  # fase a, eq. 1
    f[3] = vt[1]  # fase b, eq. 1
    f[6] = vt[2]  # fase c, eq. 1
    return f

  def rhs(self, t, x):
    Minv = np.linalg.inv(self.M)
    return Minv @ (self.f_vector(t) - self.K @ x)
"""

