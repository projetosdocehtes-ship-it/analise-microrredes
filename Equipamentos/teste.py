import numpy as np
import math
import json
from scipy.interpolate import interp1d
from scipy.integrate import solve_ivp
from collections import deque
import matplotlib.pyplot as plt

import Var_globais

hist_v1   = np.empty((3, 0))
hist_iL1   = np.empty((3, 0))
hist_v2   = np.empty((3, 0))
hist_iS2   = np.empty((3, 0))
hist_vt   = np.empty((3, 0))
hist_Itraf   = np.empty((3, 0))


class Rede_Eletrica:
  def __init__(self):
    self.V_ll_rms = 380.0                       # Tensão de fase RMS
    self.V_ln_rms = self.V_ll_rms/np.sqrt(3)    # Tensão de linha RMS

    self.freq = 60.0

    self.omega = 2*np.pi*self.freq

    self.R_linha = 0.04       # ohm/km
    self.L_linha = 2e-5      # H/km

    self.d1 = 10.0            # km (trafo -> carga 1)
    self.d2 = 000            # km (carga 1 -> carga 2: será d2-d1)

    self.S1 = 13000.0
    self.pf1 = 0.8
    self.S2 = 000
    self.pf2 = 00

    self.Tempo_Sim = 0

    self.Tolerancia_relativa = 1e-8
    self.Metodo_EDO = 'RK45'

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

    i_s1 = sol.y[0:9:3, :]  # shape (3 fases, Nt)
    i_L1 = sol.y[1:9:3, :]
    i_s2 = sol.y[2:9:3, :]  # = i_L2

    # Derivadas para tensões nas cargas
    dxdt = self.rhs(sol.t[-1], sol.y[:, -1])
    di_L1_dt = dxdt[1:9:3]   # pega as derivadas correspondentes
    di_s2_dt = dxdt[2:9:3]

    # Tensões de fase nos PCCs:
    # v1 = R_L1*i_L1 + L_L1*di_L1/dt
    # v2 = R_L2*i_s2 + L_L2*di_s2/dt
    di_L1_dt = di_L1_dt.reshape(3,1)
    di_s2_dt = di_s2_dt.reshape(3,1)

    v1 = R_L1*i_L1 + L_L1*di_L1_dt
    v2 = R_L2*i_s2 + L_L2*di_s2_dt
    
    # Corrente do trafo (por fase) = corrente no trecho 1
    vt = self.v_trafo_phase(self.Tempo_Sim)
    I_traf = i_s1
    
    global hist_v1, hist_iL1, hist_v2, hist_iS2, hist_vt, hist_Itraf
    hist_v1    = np.hstack((hist_v1, v1))
    hist_iL1   = np.hstack((hist_iL1, i_L1))
    hist_v2    = np.hstack((hist_v2, v2))
    hist_iS2   = np.hstack((hist_iS2, i_s2))
    hist_vt    = np.hstack((hist_vt, vt.reshape(3,1)))   # reshape para (3,1)
    hist_Itraf = np.hstack((hist_Itraf, I_traf))

    self.Tempo_Sim = sol.t[-1]  # Atualiza o tempo
    # print(hist_v1.shape)
    # print("-------")


  def RL_from_S_pf(self, S, pf):
    if S == 0:
        return 1e15, 1e15
    
    I_rms_line = S/(np.sqrt(3)*self.V_ll_rms)  # corrente de linha (rms)
    Zmag = self.V_ln_rms / I_rms_line          # impedância por fase (módulo)
    R = Zmag * pf
    XL = Zmag*np.sqrt(max(0.0,1.0-pf**2))
    L = XL/self.omega
    
    return R, L

  def calcula_impedancias(self):
    R_L1, L_L1 = self.RL_from_S_pf(self.S1, self.pf1)
    R_L2, L_L2 = self.RL_from_S_pf(self.S2, self.pf2)
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
  

Rede = Rede_Eletrica()

for i in range(Var_globais.Num_Iteracao_global):
    Rede.simula_rede()

    Var_globais.Passo_atual_global = Var_globais.Passo_atual_global + 1

# hist_v1   = np.hstack(hist_v1).T   # shape (3, N)
# hist_iL1  = np.hstack(hist_iL1).T
# hist_v2   = np.hstack(hist_v2).T
# hist_iS2  = np.hstack(hist_iS2).T
# hist_vt   = np.hstack(hist_vt).T
# hist_Itraf= np.hstack(hist_Itraf).T

N = int(Var_globais.T_sim_global / Var_globais.Passo_global) + 1
t_eval = np.linspace(0, Var_globais.T_sim_global, N)

print(hist_v1.shape)
print(hist_iL1.shape)
print(hist_v2.shape)
print(hist_iS2.shape)
print(hist_vt.shape)
print(hist_Itraf.shape)
# print(t_eval.shape)

fig, axs = plt.subplots(3, 2, figsize=(13, 9), sharex=True)

# Carga 1: tensões e correntes
axs[0,0].plot(t_eval, hist_v1[0,:], label='Va1')
axs[0,0].plot(t_eval, hist_v1[1,:], label='Vb1')
axs[0,0].plot(t_eval, hist_v1[2,:], label='Vc1')
axs[0,0].set_title('Tensão no PCC da Carga 1')
axs[0,0].set_ylabel('V [V]'); axs[0,0].grid(True); axs[0,0].legend()

axs[0,1].plot(t_eval, hist_iL1[0,:], label='Ia1')
axs[0,1].plot(t_eval, hist_iL1[1,:], label='Ib1')
axs[0,1].plot(t_eval, hist_iL1[2,:], label='Ic1')
axs[0,1].set_title('Corrente da Carga 1')
axs[0,1].set_ylabel('I [A]'); axs[0,1].grid(True); axs[0,1].legend()

# Carga 2: tensões e correntes
axs[1,0].plot(t_eval, hist_v2[0,:], label='Va2')
axs[1,0].plot(t_eval, hist_v2[1,:], label='Vb2')
axs[1,0].plot(t_eval, hist_v2[2,:], label='Vc2')
axs[1,0].set_title('Tensão no PCC da Carga 2')
axs[1,0].set_ylabel('V [V]'); axs[1,0].grid(True); axs[1,0].legend()

axs[1,1].plot(t_eval, hist_iS2[0,:], label='Ia2 (i_L2)')
axs[1,1].plot(t_eval, hist_iS2[1,:], label='Ib2 (i_L2)')
axs[1,1].plot(t_eval, hist_iS2[2,:], label='Ic2 (i_L2)')
axs[1,1].set_title('Corrente da Carga 2')
axs[1,1].set_ylabel('I [A]'); axs[1,1].grid(True); axs[1,1].legend()

# Trafo: tensão e corrente
axs[2,0].plot(t_eval, hist_vt[0,:], label='VaT')
axs[2,0].plot(t_eval, hist_vt[1,:], label='VbT')
axs[2,0].plot(t_eval, hist_vt[2,:], label='VcT')
axs[2,0].set_title('Tensão do Trafo (fase)')
axs[2,0].set_ylabel('V [V]'); axs[2,0].grid(True); axs[2,0].legend()

axs[2,1].plot(t_eval, hist_Itraf[0,:], label='IaT')
axs[2,1].plot(t_eval, hist_Itraf[1,:], label='IbT')
axs[2,1].plot(t_eval, hist_Itraf[2,:], label='IcT')
axs[2,1].set_title('Corrente do Trafo (fase) = i_s1')
axs[2,1].set_ylabel('I [A]'); axs[2,1].grid(True); axs[2,1].legend()

for ax in axs[-1,:]:
    ax.set_xlabel('Tempo [ms]')

plt.tight_layout()
plt.show()