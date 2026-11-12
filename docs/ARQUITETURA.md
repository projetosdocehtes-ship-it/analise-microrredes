# Arquitetura do ProjetoPowerFlow

O repositório agora separa três responsabilidades:

1. `sim-stable/Equipamentos`: simulador dinâmico de microrredes, com modelos de PV, inversor, bateria, carga, barramento, controle e eventos transitórios.
2. `Equipamentos/`: componentes dinâmicos reutilizáveis, com `GeradorDiesel` e `BESS` isolados, estados explícitos e equações diferenciais próprias.
3. `microrredes/analises`: camada nova para análises executáveis de forma independente:
   - `fluxo_potencia.py`: fluxo AC usando uma rede `pandapower`;
   - `falhas.py`: curto-circuito, sem depender da execução do fluxo;
   - `fundamentais.py`: custos de energia, demanda, TE/TUSD e ICMS;
   - `cenario_bess_fv.py`: fluxo AC horário on-grid para FV+BESS, com contingência de strings.
   - `transitorio_bess_fv.py`: transitório reduzido legado e integração do arquivo único PV+BESS+diesel.
   - `transitorio_gerador_diesel.py`: modelo reduzido isolado de gerador diesel com governador, AVR, eventos de carga e curto-circuito.
4. `old/`: scripts, testes, relatórios, entradas e resultados anteriores, preservados para consulta e comparação.

## Contratos principais

- Fluxo de potência recebe uma rede `pandapower` e devolve convergência, tensão por barra e carregamento de linhas.
- Falhas recebe uma rede `pandapower` e devolve corrente inicial simétrica por barra, tipo e caso da falta.
- Tarifas usam `TarifaSnapshot`, que mantém distribuidora, grupo, vigência, fonte, horário da consulta e quantidade de registros.
- ICMS é uma alíquota decimal configurável. O gross-up incide sobre consumo; demanda fica separada e não recebe ICMS automaticamente.

## Entrada própria do regime permanente

O comando `fluxo-potencia --entrada` aceita um JSON próprio no contrato de equipamentos do
`Entradas.Json` transitório e do legado. O arquivo é convertido para uma rede `pandapower`
nova por execução, sem acoplamento ao arquivo do simulador dinâmico. Quando o JSON não possui
impedâncias de linha, o módulo usa defaults explícitos e os registra no resultado; esses valores
devem ser substituídos pelo caso elétrico aprovado antes de uso regulatório.

## Chamadas independentes

Os contratos completos dos ensaios do diesel estão em
[docs/ENTRADAS_GERADOR_DIESEL.md](ENTRADAS_GERADOR_DIESEL.md). O arquivo
`Entradas_microrrede_completa.json` conecta PV, BESS e diesel no transitório
reduzido, além de poder ser usado no regime permanente. Os arquivos separados
continuam disponíveis para validação isolada e compatibilidade legada.

```powershell
.venv\Scripts\python.exe -m microrredes fluxo-potencia
.venv\Scripts\python.exe -m microrredes fluxo-potencia --entrada Entradas\Entradas_regime_permanente.json --saida resultados\fluxo_permanente.json
.venv\Scripts\python.exe -m microrredes regime-permanente --entrada Entradas\Entradas_regime_permanente.json --periodo 24h --tipo-dia util --saida resultados\regime_permanente_24h.json
.venv\Scripts\python.exe -m microrredes regime-permanente --entrada Entradas\Entradas_regime_permanente.json --periodo ano --ano 2025 --saida resultados\regime_permanente_8760h.json
.venv\Scripts\python.exe -m microrredes transitorio-gerador-diesel --entrada Entradas\gerador_diesel_teste.json --saida resultados\transitorio_gerador_diesel_teste.json
.venv\Scripts\python.exe -m microrredes transitorio-gerador-diesel --entrada Entradas\Entradas_transitorio_gerador_diesel.json --saida resultados\transitorio_gerador_diesel.json
.venv\Scripts\python.exe -m microrredes regime-permanente --entrada Entradas\Entradas_regime_permanente_diesel.json --periodo 24h --tipo-dia util --saida resultados\regime_permanente_diesel_24h.json
.venv\Scripts\python.exe -m microrredes regime-permanente --entrada Entradas\Entradas_microrrede_completa.json
.venv\Scripts\python.exe -m microrredes transitorio-bess-fv --entrada Entradas\Entradas_microrrede_completa.json --saida resultados\transitorio_microrrede_completa.json
.venv\Scripts\python.exe -m microrredes falhas --tipo 3ph
.venv\Scripts\python.exe -m microrredes cenario-bess-fv --consumo-dia-kwh 650 --graficos-dir resultados --saida resultados\analise_bess_fv_650kwh.json
.venv\Scripts\python.exe -m microrredes fundamentais --icms 0.19 --energia-fora-ponta 1000
```

As duas primeiras chamadas usam uma rede mínima de demonstração. Para estudos reais, o próximo passo é adaptar um construtor de rede a partir do caso elétrico aprovado, sem acoplar esse construtor ao simulador dinâmico.
