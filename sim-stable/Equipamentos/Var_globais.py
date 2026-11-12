import math

#------------------------------------------- Variaveis Globais -------------------------------------------

Resolucao_Clima = 300000
Passo_global = 2E-5
Passo_atual_global = 0
T_sim_global = 1
Num_Iteracao_global = math.ceil( T_sim_global / Passo_global )

flag_ongrid = False


MA_G = []
ERRO_G = []
V_REF_G = 220
V_RMS_G = []