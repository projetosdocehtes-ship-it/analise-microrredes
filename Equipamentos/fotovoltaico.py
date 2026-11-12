import numpy as np
from scipy.interpolate import interp1d
from scipy.integrate import solve_ivp
from collections import deque
import matplotlib.pyplot as plt

Passo_atual_global = 0

class Painel_Fotovoltaico:
  def __init__(self, fabricante_painel, modelo_painel, Pmp, Isc, Voc, Imp, Vmp, Uisc, Uvoc, Upmp, material_painel, eficiencia):
    self.PV_Param = self.Param_Painel_Fotovoltaico(fabricante_painel, modelo_painel, Pmp, Isc, Voc, Imp, Vmp, Uisc, Uvoc, Upmp, material_painel, eficiencia)

  def Simular_painel(self, Nm_paineis, Clima, Inversor, falhas_paineis):
    if Passo_atual_global == 0:
      self.Painel_simulado = self.Simulacao_painel(self.PV_Param, Inversor, Nm_paineis)

    V, I, P = self.Painel_simulado.Simula_PV(Clima, falhas_paineis)

    Inversor.Armazenar_Val_Paineis(V*Nm_paineis[0], I*Nm_paineis[1], P*Nm_paineis[0]*Nm_paineis[1])
    
    return V, I, P

  class Param_Painel_Fotovoltaico:
    def __init__(self, fabricante_painel, modelo_painel, Pmp, Isc, Voc, Imp, Vmp, Uisc, Uvoc, Upmp, material_painel, eficiencia):

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

    def Retorna_Parametros_Calculados(self):
      return self.Rsh, self.Rs, self.Io, self.IL, self.nT, self.n

    def Retorna_Parametros_Datasheet(self):
      return self.Pmp, self.Isc, self.Voc, self.Uisc, self.Uvoc, self.Upmp

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

# ----------------------

pfv = Painel_Fotovoltaico("Canadian Solar", "CS6.2-66TB-610", 610, 15.97, 48, 14.96, 40.8, 0.05, -0.25, -0.29, "Silicio", 22.6)

# --- 1️⃣ Gráfico: Temperatura variando (5, 25, 45, 65 °C) e irradiância fixa em 1000 W/m² ---
plt.figure(figsize=(12, 5))

# --- 1️⃣ Gráfico à esquerda: Temperatura variando (G = 1000 W/m²) ---
plt.subplot(1, 2, 1)
temperaturas = [5, 25, 45, 65]
for T in temperaturas:
    V, I = pfv.PV_Param.Gerar_curva_IV(T, 1000)
    plt.plot(V, I, label=f'{T}°C')

plt.title("Curvas I–V para diferentes Temperaturas\n(G = 1000 W/m²)")
plt.xlabel("Tensão (V)")
plt.ylabel("Corrente (A)")
plt.legend()
plt.grid(True)

# --- 2️⃣ Gráfico à direita: Irradiância variando (T = 25°C) ---
plt.subplot(1, 2, 2)
irradiancias = [1000, 900, 800]
for G in irradiancias:
    V, I = pfv.PV_Param.Gerar_curva_IV(26, G)
    plt.plot(V, I, label=f'{G} W/m²')

plt.title("Curvas I–V para diferentes Irradiâncias\n(T = 25°C)")
plt.xlabel("Tensão (V)")
plt.ylabel("Corrente (A)")
plt.legend()
plt.grid(True)

# Ajuste do layout e exibição
plt.tight_layout()
plt.show()