# ProjetoPowerFlow

Projeto único para análises de microrredes, com separação entre simulação dinâmica, fluxo de potência, falhas e análises fundamentais.

## Organização

```text
ProjetoPowerFlow/
├── microrredes/                 # API nova e CLI
│   ├── analises/
│   │   ├── fluxo_potencia.py    # fluxo AC independente
│   │   ├── falhas.py            # curto-circuito independente
│   │   └── fundamentais.py      # TE/TUSD, demanda e ICMS
│   └── dados/tarifas_aneel.py   # cliente da API aberta da ANEEL
├── sim-stable/                  # simulador dinâmico novo
├── Equipamentos/                # modelos dinâmicos de equipamentos
│   ├── gerador_diesel.py         # equações do gerador e governador/AVR
│   ├── celula_combustivel_pem.py # gerador PEMFC, regime estático e transitório
│   ├── gerador_motor_hidrogenio.py # motor-gerador H2, potência e consumo de combustível
│   ├── hidrogenio.py             # lei de Faraday e inventário de massa no tanque
│   ├── bess.py                   # estado de carga e limites do BESS
│   └── eletrolisador_pem.py      # EEC estático e dinâmico do stack PEM
├── old/                         # código, documentos e artefatos antigos preservados
├── resultados/                  # saídas atuais, inclusive HTML interativo
├── tests/                       # testes da camada nova
└── docs/                        # arquitetura, dados e qualidade
```

`sim-stable/` e `Equipamentos/` continuam sendo o núcleo de análises dinâmicas. O conteúdo movido para `old/` é mantido para consulta e comparação e não deve ser importado pela camada nova.

## Instalação

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Para executar os testes:
pip install -r requirements-dev.txt
```

Para instalar o pacote em modo editável:

```powershell
pip install -e .
```

## Execução

As análises são chamadas separadamente:

```powershell
# Fluxo de potência AC da rede demo
.venv\Scripts\python.exe -m microrredes fluxo-potencia

# Fluxo de potência permanente com entrada própria (independente do transitório)
.venv\Scripts\python.exe -m microrredes fluxo-potencia `
  --entrada Entradas\Entradas_regime_permanente.json `
  --saida resultados\fluxo_permanente.json

# Regime permanente hora a hora com curva CSV
.venv\Scripts\python.exe -m microrredes regime-permanente `
  --entrada Entradas\Entradas_regime_permanente.json `
  --periodo 24h --tipo-dia util `
  --saida resultados\regime_permanente_24h.json

# Ano civil: 8760 horas em 2025
.venv\Scripts\python.exe -m microrredes regime-permanente `
  --entrada Entradas\Entradas_regime_permanente.json `
  --periodo ano --ano 2025 `
  --saida resultados\regime_permanente_8760h.json

# Teste isolado do gerador diesel: governador, AVR, degrau de carga e curto 3 fases
.venv\Scripts\python.exe -m microrredes transitorio-gerador-diesel `
  --entrada Entradas\Entradas_transitorio_gerador_diesel.json `
  --saida resultados\transitorio_gerador_diesel_teste.json

# Prepare esse JSON com parâmetros identificados do stack e corrente de ensaio
.venv\Scripts\python.exe -m microrredes transitorio-eletrolisador-pem `
  --entrada Entradas\meu_eletrolisador_pem.json `
  --saida resultados\transitorio_eletrolisador_pem.json

# Regime permanente offgrid com PV, BESS e gerador diesel
.venv\Scripts\python.exe -m microrredes regime-permanente `
  --entrada Entradas\Entradas_regime_permanente_diesel.json `
  --periodo 24h --tipo-dia util `
  --saida resultados\regime_permanente_diesel_24h.json

# Limita o despacho do diesel a 8 horas no horizonte e calcula os custos
.venv\Scripts\python.exe -m microrredes regime-permanente `
  --entrada Entradas\Entradas_regime_permanente_diesel.json `
  --tempo-operacao-gerador-h 8

# Arquivo único: o regime lê estudos.regime_permanente do JSON
.venv\Scripts\python.exe -m microrredes regime-permanente `
  --entrada Entradas\Entradas_microrrede_completa.json

# Arquivo único no transitório conectado: PV+BESS+diesel, degrau e curto
.venv\Scripts\python.exe -m microrredes transitorio-bess-fv `
  --entrada Entradas\Entradas_microrrede_completa.json `
  --saida resultados\transitorio_microrrede_completa.json

# Curto-circuito separado do fluxo
.venv\Scripts\python.exe -m microrredes falhas --tipo 3ph

# Cenário completo FV + BESS, 650 kWh/dia, on-grid e perda de 4/16 strings
.venv\Scripts\python.exe -m microrredes cenario-bess-fv `
  --consumo-dia-kwh 650 --pv-kwp 80 --bess-kwh 100 --bess-kw 40 `
  --strings-fv 16 --strings-perdidas 4 `
  --contingencia-inicio 10 --contingencia-fim 18 `
  --graficos-dir resultados `
  --saida resultados\analise_bess_fv_650kwh.json

# Transitório em segundos, com HTML interativo e leitura de valores no cursor
.venv\Scripts\python.exe -m microrredes transitorio-bess-fv `
  --entrada Entradas\Entradas_microrrede_completa.json `
  --consumo-dia-kwh 650 --pv-kwp 80 --bess-kwh 100 --bess-kw 40 `
  --strings-fv 16 --strings-perdidas 4 --forcar-on-grid `
  --saida resultados\transitorio\resultado_transitorio_bess_fv.json `
  --graficos-dir resultados\transitorio `
  --html-interativo resultados\transitorio\transitorio_interativo.html

# Comparação Azul/Verde com tarifas ANEEL e ICMS de 19%
.venv\Scripts\python.exe -m microrredes fundamentais `
  --distribuidora "EQUATORIAL GO" --grupo A4 --icms 0.19 `
  --energia-ponta 1000 --energia-fora-ponta 5000 `
  --demanda-ponta 680 --demanda-fora-ponta 680
```

Por padrão, a análise fundamental consulta a fonte oficial da ANEEL. Para execução offline, use `--usar-fallback`; o resultado será marcado como `fallback_local_nao_atualizado`.

## Fonte tarifária e ICMS

O módulo consulta o conjunto oficial de tarifas de aplicação da ANEEL, seleciona a vigência aplicável e registra fonte, vigência e instante da consulta no resultado. O ICMS é uma alíquota decimal configurável e é aplicado por gross-up ao consumo:

```text
valor_com_ICMS = valor_sem_ICMS / (1 - aliquota)
```

PIS/COFINS, bandeiras, SCEE e regras específicas de créditos ainda não fazem parte do contrato atual. Consulte [docs/DADOS_E_TARIFAS.md](docs/DADOS_E_TARIFAS.md) antes de usar o resultado em estudo regulatório ou comercial.

## Modelo elétrico do eletrolisador PEM

`Equipamentos/eletrolisador_pem.py` implementa o equivalente CC de uma porta. O cálculo de regime permanente impõe `dV/dt = 0`; a simulação transitória integra a queda de polarização como estado. A variante padrão `combined_dle` usa o EEC 10 e `C_dle_cell_F`. A variante `separate_rc` usa o EEC 9 e `C_act_cell_F`/`C_con_cell_F`.

Informe os parâmetros por célula `V_rev_cell_V`, `R_ohm_cell_Ohm`, `R_act_cell_Ohm`, `R_con_cell_Ohm` e `n_series_cells`. `n_parallel_strings` é opcional e assume 1. O fluxo permanente também requer `corrente_stack_A`; o transitório lê a corrente inicial e os degraus de `estudos.transitorio_eletrolisador_pem` e `eventos`. Para transitórios também são necessárias as capacitâncias da variante selecionada. Os valores devem vir da ficha técnica, curva de polarização ou ensaio do stack; o projeto não fornece parâmetros de demonstração.

O fluxo permanente lê `eletrolisador_pem_info` e usa `corrente_stack_A` para calcular tensão e potência do stack. Na rede AC, essa potência é representada como elemento `load` pandapower. A conversão CC/CA está fora do EEC: `eficiencia_conversor` e `fator_potencia_ac` são parâmetros opcionais da interface, com defaults ideais de 1,0, explicitados no resultado. O pandapower também tem um elemento genérico [`load_dc`](https://pandapower.readthedocs.io/en/latest/elements/load_dc.html), que representa consumo numa barra CC, mas não implementa o EEC PEM nem sua dinâmica; a rede deste projeto permanece AC e usa o equivalente de carga no lado da interface.

O comando `transitorio-eletrolisador-pem` lê os parâmetros do stack em `eletrolisador_pem_info` e os parâmetros do ensaio em `estudos.transitorio_eletrolisador_pem` (`passo_s`, `duracao_s`, `corrente_inicial_A`, e opcionalmente `estado_inicial`). Eventos em `eventos` usam `tipo: "degrau_corrente"`, `inicio_s`, `corrente_stack_A` e, opcionalmente, `duracao_s`. A corrente é uma entrada prescrita; este modelo não calcula conversor, produção de gases, eficiência faradaica, temperatura ou pressão.

## Ciclo de hidrogênio e geradores

`Equipamentos/hidrogenio.py` calcula a produção do PEME pela lei de Faraday quando `eficiencia_faradaica` é informada e mantém o inventário ideal de massa do tanque. O eletrolisador permanece uma carga elétrica. A geração pode ser representada por uma única alternativa por execução: PEMFC em `gerador_hidrogenio_info` ou motor reciprocante em `motor_hidrogenio_info`.

O comando `transitorio-ciclo-hidrogenio` integra eletrolisador, tanque e uma dessas alternativas. A PEMFC usa seu equivalente elétrico dinâmico e consome H₂ pela lei de Faraday com `utilizacao_h2`. O motor usa `potencia_eletrica_kw` como estado, primeira ordem limitada por rampa, eficiência líquida sobre o PCI e consumo `P/(eta * PCI_H2)`. Para o motor, informe `potencia_nominal_kw`, `eficiencia_eletrica_liquida`, `constante_tempo_s` e `rampa_max_kw_min`; não há valores universais. A referência inicial pode ser informada em `estudos.transitorio_ciclo_hidrogenio.potencia_gerador_referencia_kw`, e eventos do gerador usam `componente: "gerador"`, `potencia_referencia_kw`, `inicio_s` e opcionalmente `duracao_s`. Eventos PEMFC continuam usando corrente.

Para usar o modelo Padulles-I inspirado no OPEM, selecione `"modelo_transitorio": "opem_padulles_i"` em `gerador_hidrogenio_info`. O arquivo [ciclo_pemfc_opem_padulles_demo.json](Entradas/ciclo_pemfc_opem_padulles_demo.json) traz um degrau de 10 A para 100 A em 5 s; execute `python -m microrredes transitorio-ciclo-hidrogenio --entrada Entradas/ciclo_pemfc_opem_padulles_demo.json --saida resultados/transitorio_ciclo_pemfc_opem_demo.json`. Ele gera pressao parcial, tensao por termos, potencia e fluxos de H2. O PEME do exemplo esta desligado e seus parametros sao placeholders; substitua-os antes de usar o cenario como estudo real.

Para comparar os dois tipos com o mesmo eletrolisador, tanque e perfil de produção, prepare um JSON com PEMFC e outro com `motor_hidrogenio_info`, mantendo iguais os parâmetros comuns, e execute:

```powershell
.venv\Scripts\python.exe -m microrredes comparar-geradores-hidrogenio `
  --entrada-pemfc Entradas\ciclo_pemfc.json `
  --entrada-motor Entradas\ciclo_motor_h2.json `
  --saida resultados\comparacao_geradores_h2.json
```

O resultado inclui as duas séries temporais e as diferenças de consumo de H₂, energia e potência máxima. A potência PEMFC é a potência CC do stack; a do motor é a potência elétrica líquida. Para comparar potência AC, aplique as perdas de conversores e auxiliares correspondentes.

O tanque recebe `armazenamento_hidrogenio_info` com `capacidade_kg` e `massa_inicial_kg`. O balanço levanta erro quando o consumo exige massa negativa ou a produção excede a capacidade. O modelo do tanque é apenas de massa; não calcula pressão, temperatura ou compressão.

No regime permanente e fluxo de potência AC, a PEMFC e o motor são injeções positivas de geração; o PEME continua como `load`. A rede conectada usa `sgen`. Em ilha, um gerador H₂ pode fornecer a referência de tensão quando não houver diesel, representado no pandapower como `gen` slack. O motor entra no saldo e no resumo horário do regime permanente. Esse resumo não rastreia o inventário horário do tanque; para verificar limites de estoque, use o estudo transitório do ciclo.

Para exemplos completos de campos e premissas, consulte [docs/modelo_ciclo_hidrogenio.md](docs/modelo_ciclo_hidrogenio.md). Os parâmetros do stack, rendimento, rampa e constantes de tempo devem vir da ficha técnica ou de ensaios do equipamento; os valores de referência publicados não são defaults do software.

## Testes

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Os testes cobrem a normalização de registros tarifários, vigência, ICMS, convergência do fluxo e curto-circuito da rede demo. A execução integral do simulador dinâmico continua pendente de corrigir a entrada `Falhas_sim` e de definir um caso de teste com tempo controlado.

O comando `cenario-bess-fv` gera gráficos de regime permanente/quase-estático. Gráficos transitórios dependem da execução validada do simulador dinâmico `sim-stable/Equipamentos`.

Consulte também:

- [docs/ARQUITETURA.md](docs/ARQUITETURA.md)
- [docs/DADOS_E_TARIFAS.md](docs/DADOS_E_TARIFAS.md)
- [docs/ENTRADAS_GERADOR_DIESEL.md](docs/ENTRADAS_GERADOR_DIESEL.md)
- [docs/LEGADO.md](docs/LEGADO.md)
- [docs/testing/QUALITY_PLAN.md](docs/testing/QUALITY_PLAN.md)

O comando `fluxo-potencia --entrada` aceita um JSON no contrato de equipamentos usado pelo
`Entradas.Json` do transitório e pelo legado (`painel_info`, `inversor_info`, `cargas_info`,
`bateria_info`, `barramento_info`, `geradordiesel_info` e `grafo_conexoes`). Cada execução
carrega uma rede nova. Os arquivos separados não compartilham estado; o arquivo único
`Entradas_microrrede_completa.json` pode ser usado nos dois estudos. Quando o JSON não
informa impedâncias de linhas, são usados defaults explícitos no resultado e na documentação
do módulo.

No regime permanente, `geradordiesel_info` pode informar
`custo_oleo_diesel_por_litro`, `consumo_especifico_litros_por_kwh` e
`custo_equipamento`. O primeiro custo é calculado pela energia efetivamente
gerada pelo diesel; `custo_equipamento: 0` indica que o grupo já existe e não
inclui CAPEX. O campo `operacao.tempo_operacao_h` (ou a opção
`--tempo-operacao-gerador-h`) limita as horas acumuladas de despacho no
horizonte simulado. O JSON de saída registra esses cálculos em
`analise_economica` e detalha combustível e custo por hora.
