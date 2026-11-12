# Plano de qualidade

Risco da mudança: alto, pois há reorganização de scripts, nova fonte externa e análise elétrica.

Gates executados nesta entrega:

Para o regime permanente, o gate econômico também verifica a identidade
`custo do combustível = energia do diesel × consumo específico × preço por
litro`, o CAPEX opcional e o limite de horas de operação configurado.

1. compilação/importação dos módulos novos;
2. testes unitários de ICMS, contrato tarifário e normalização ANEEL;
3. teste de integração da rede demo para fluxo e curto-circuito;
4. inspeção do relatório de conformidade e do diff.

Comando reprodutível: `.venv\Scripts\python.exe -m pytest tests -q`.

Não fazem parte deste gate: validação de um alimentador real, aderência regulatória de cada alíquota estadual, ensaio transitório completo do simulador dinâmico e publicação/deploy.
