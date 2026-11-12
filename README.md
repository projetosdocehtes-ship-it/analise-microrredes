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
│   └── bess.py                   # estado de carga e limites do BESS
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
