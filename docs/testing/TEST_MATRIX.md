# Matriz de testes

| Área | Teste | Evidência |
|---|---|---|
| Economia do regime permanente | custo do óleo diesel, consumo específico, CAPEX opcional, equipamento existente e limite de horas do gerador | `tests/test_regime_permanente.py` |
| Fundamentos | gross-up do ICMS e comparação Azul/Verde | `tests/test_fundamentais.py` |
| Dados | unidade, modalidade, grupo e vigência do snapshot | `tests/test_tarifas_aneel.py` |
| Fluxo | convergência e tensões da rede demo | `tests/test_analises_eletricas.py` |
| Falhas | curto 3 fases e corrente por barra | `tests/test_analises_eletricas.py` |
| Fluxo com arquivo | dois JSONs próprios, isolamento entre execuções e rejeição de entrada ilhada sem fonte | `tests/test_analises_eletricas.py` |
| Regime permanente horário | leitura da curva CSV, seleção util/fim de semana, simulação curta e geração do calendário anual de 8760 horas | `tests/test_regime_permanente.py` |
| Transitório do gerador diesel | `pandapower.gen` com parâmetros de curto, fluxo convergido, governador/AVR, degrau de carga e curto 3 fases | `tests/test_transitorio_gerador_diesel.py` |
| Contratos JSON do diesel | entradas independentes para regime permanente, curto-circuito pandapower e transitório isolado, incluindo compatibilidade legada | `tests/test_analises_eletricas.py`, `tests/test_regime_permanente.py`, `tests/test_transitorio_gerador_diesel.py` |
| Arquivo único da microrrede | mesmo JSON executado no regime permanente e no transitório integrado PV+BESS+diesel, mantendo os testes isolados | `tests/test_regime_permanente.py`, `tests/test_transitorio_bess_fv.py` |
| Componentes dinâmicos | equações do `GeradorDiesel`, integração do estado e equação de SOC do `BESS` | `tests/test_equipamentos_dinamicos.py` |
| Cenário FV+BESS | 24 fluxos horários, consumo diário, perda de strings e geração de PNGs | `tests/test_cenario_bess_fv.py` |
| Dinâmico | execução integral de `sim-stable/Equipamentos` | pendente: requer fixar `Entradas.json`/`Falhas_sim` e tempo de simulação |
