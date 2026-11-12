# ----------------------------------------------------------- Classes do barramento (Nova)-----------------------------------------------------------
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

      if (Pdem_total > Pfv_total) or Var_globais.flag_ongrid == True:             # Se potencia demandada for maior que potencia Fotovoltaica disponivel ou o sistema estiver conectado a rede
        for linha in matriz_inversores:                               # cria array que pede potencia maxima
          id_inv = linha[0]
          matriz_saida.append([id_inv, -1, -1])

        return np.array(matriz_saida, dtype=object)

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

        P_percent = (P*100) / Pfv_total
        Q_percent = (Q*100) / Qfv_total

        P_requerido = P_percent * Pdem_total + 1
        Q_requerido = Q_percent * Qdem_total + 1

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


        I_entregue = 0 if V_barramento == 0 else P_entregue / (V_barramento * self.FP_sistema)

        matriz_saida.append([id_carga, V_barramento, I_entregue, P_entregue, Q_entregue])

      return np.array(matriz_saida, dtype=object)

# ----------------------------------------------------------- Classes do barramento (velha)-----------------------------------------------------------
class Barramento:
  def __init__(self, id_barramento, tipo, nm_fases, V_linha_nominal, V_fase_nominal, V_min, V_max):
    self.barramento_Param = self.Param_barramento(id_barramento, tipo, nm_fases, V_linha_nominal, V_fase_nominal, V_min, V_max)
    
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
      }
    }

  def Simular_barramento(self, agente_MQTT):
    if Var_globais.Passo_atual_global <= 1:
      print(f"barramento = {self.buffer_mensagens}")
  
    if Var_globais.Passo_atual_global == 0:
      self.barramento_simulado = self.Simulacao_Barramento(self.barramento_Param)

    matriz_inversores = self.Obter_valores_inversores()
    matriz_cargas = self.Obter_valores_cargas()

    pot_demandada_inversor, saida_para_carga = self.barramento_simulado.Simula_barramento(matriz_inversores, matriz_cargas)

    self.V_bus = saida_para_carga[0][1]

    msg_inversor = { str(linha[0]): {"P_demandada": float(linha[1]), "Q_demandada": float(linha[2]), } for linha in pot_demandada_inversor }
    agente_MQTT.publicar_msg( f"{self.id_bus}/p_demandada", msg_inversor)

    msg_param_bar = { str(linha[0]): {"V_bus": self.V_bus} for linha in pot_demandada_inversor }
    agente_MQTT.publicar_msg( f"{self.id_bus}/parametros_barramento", msg_param_bar)

    msg_carga = { str(linha[0]): {"V_recebida": linha[1], "I_recebida": linha[2], "P_recebida": linha[3]} for linha in saida_para_carga }
    agente_MQTT.publicar_msg( f"{self.id_bus}/grandezas_ac", msg_carga)

  def receive(self, origem, tipo_origem, topico, mensagem):
    """
    origem: "PV_1", "BAT_1", "INV_1"...
    tipo_origem: "Painel", "Bateria", "Carga", "Inversor", ...
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

    def Simula_barramento(self, matriz_inversores, matriz_cargas):
      pot_demandada_inversor = self.Distribui_P_para_inversores(matriz_inversores, matriz_cargas)
      saida_para_carga = self.Distribui_P_para_Cargas(matriz_inversores, matriz_cargas)

      return pot_demandada_inversor, saida_para_carga

    def Distribui_P_para_inversores(self, matriz_inversores, matriz_cargas):
      """
      Recebe:
        - matriz_inversores: np.array([[id_inv, V_ac_rms, I_ac_rms, V_ac_onda, I_ac_onda], ...])
        - matriz_cargas:     np.array([[id_carga, P_demandada, Q_demandada], ...])

      Retorna:
        np.array([[id_inversor, P_requerida, Q_requerida], ...])
      """

      # ---------------------
      # 1. Soma total das cargas
      # ---------------------
      if len(matriz_cargas) == 0:
          return np.array([])

      P_total = sum(linha[1] for linha in matriz_cargas)
      Q_total = sum(linha[2] for linha in matriz_cargas)

      # ---------------------
      # 2. Quantidade de inversores
      # ---------------------
      n_inv = len(matriz_inversores)
      if n_inv == 0:
          raise ValueError("Nenhum inversor disponível para distribuir potência.")

      # ---------------------
      # 3. Divide potência igualmente
      # ---------------------
      P_por_inv = P_total / n_inv
      Q_por_inv = Q_total / n_inv

      # ---------------------
      # 4. Cria a matriz resultado
      # ---------------------
      matriz_saida = []

      for linha in matriz_inversores:
          id_inv = linha[0]
          matriz_saida.append([id_inv, P_por_inv, Q_por_inv])

      return np.array(matriz_saida, dtype=object)

    def Distribui_P_para_Cargas(self, matriz_inversores, matriz_cargas):
      """
      Recebe matrizes de inversores e cargas e verifica se a potência dos inversores
      atende exatamente a soma das potências das cargas.

      Retorna:
        [[id_carga, V_rms_entregue, I_rms_entregue, P_rms_entregue], ...]
      """
      if Var_globais.Passo_atual_global == 0:
        matriz_saida = []

        for linha in matriz_cargas:
          id_carga = linha[0]
          matriz_saida.append([id_carga, 0, 0, 0])
        return np.array(matriz_saida, dtype=object)        

      if len(matriz_inversores) == 0:
        raise ValueError("Nenhum inversor disponível.")

      if len(matriz_cargas) == 0:
        raise ValueError("Nenhuma carga informada.")

      P_carga_total = sum(float(linha[1]) for linha in matriz_cargas)
      Q_carga_total = sum(float(linha[2]) for linha in matriz_cargas)

      S_carga = np.sqrt(P_carga_total**2 + Q_carga_total**2)

      FP = 1.0 if S_carga == 0 else P_carga_total / S_carga   # fator de potência da carga
      FP = max(0.01, FP)  # evitar divisão por zero

      # FP do inversor = FP da carga (conforme solicitado)
      FP_inv = FP

      # -------------------------------------------------------------------------
      # 2) Calcular potência total dos inversores considerando nº de fases
      # -------------------------------------------------------------------------
      P_inv_total = 0.0

      for linha in matriz_inversores:
        V_rms = float(linha[1])   # linha se trifásico, fase se monofásico
        I_rms = float(linha[2])

        if self.nm_fases == 1:
          # Monofásico
          P_inv = V_rms * I_rms * FP_inv

        elif self.nm_fases > 1:
          # Trifásico: valores de linha
          P_inv = (np.sqrt(3) * V_rms * I_rms) * FP_inv

        else:
          raise ValueError(f"nm_fases inválido: {self.nm_fases}")

        P_inv_total += P_inv

      # -------------------------------------------------------------------------
      # 3) Verificar equilíbrio (±10 W de tolerância)
      # -------------------------------------------------------------------------
      # if abs(P_inv_total - P_carga_total) >= 10:
      #   if P_inv_total < P_carga_total:
      #     raise ValueError(
      #       f"Potência insuficiente: inversores geram {P_inv_total:.2f} W "
      #       f"e cargas exigem {P_carga_total:.2f} W."
      #     )
      #   else:
      #     raise ValueError(
      #       f"Potência sobrando: inversores geram {P_inv_total:.2f} W "
      #       f"e cargas exigem {P_carga_total:.2f} W."
      #     )

      # -------------------------------------------------------------------------
      # 4) Tensão do barramento (média das tensões)
      # -------------------------------------------------------------------------
      V_barramento = np.mean([float(linha[1]) for linha in matriz_inversores])

      # -------------------------------------------------------------------------
      # 5) Gerar matrizes de saída
      # Corrente da carga já considera FP
      # -------------------------------------------------------------------------
      matriz_saida = []

      for linha in matriz_cargas:
        id_carga = linha[0]
        P = float(linha[1])

        I = 0 if V_barramento == 0 else P / (V_barramento * FP)

        matriz_saida.append([id_carga, V_barramento, I, P])

      return np.array(matriz_saida, dtype=object)
