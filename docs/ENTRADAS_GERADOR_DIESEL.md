# Entradas do gerador diesel

Há dois arquivos de entrada independentes para o gerador diesel:

- `Entradas/Entradas_regime_permanente_diesel.json`: rede AC e despacho horário de PV, BESS e diesel.
- `Entradas/Entradas_transitorio_gerador_diesel.json`: ensaio transitório isolado do grupo, com degrau de carga e curto-circuito.
- `Entradas/Entradas_microrrede_completa.json`: arquivo único com equipamentos, eventos e configurações dos dois estudos.

O arquivo único pode ser usado diretamente nos comandos `regime-permanente`,
`transitorio-bess-fv` e `transitorio-gerador-diesel`. Os arquivos separados
continuam disponíveis para testes e análises isoladas.

Eles não compartilham estado. O primeiro é consumido por `fluxo-potencia` e
`regime-permanente`; o segundo é consumido por `transitorio-gerador-diesel`.

## Regime permanente

Execute:

```powershell
.venv\Scripts\python.exe -m microrredes fluxo-potencia `
  --entrada Entradas\Entradas_regime_permanente_diesel.json

.venv\Scripts\python.exe -m microrredes regime-permanente `
  --entrada Entradas\Entradas_regime_permanente_diesel.json `
  --periodo 24h --tipo-dia util `
  --saida resultados\regime_permanente_diesel_24h.json

# Mesmo regime usando o arquivo único; período e horizonte vêm de estudos.regime_permanente
.venv\Scripts\python.exe -m microrredes regime-permanente `
  --entrada Entradas\Entradas_microrrede_completa.json
```

O arquivo deve informar:

- `conectado_rede`: `false` para o diesel ser a referência de tensão e ângulo da
  microrrede ilhada; `true` mantém a distribuidora como referência e modela o
  diesel como `gen` síncrono controlado;
- `painel_info`, `inversor_info`, `cargas_info`, `bateria_info` e
  `barramento_info`, seguindo o contrato legado;
- `cargas_info[0].curva_carga`, com caminho relativo ao JSON. O CSV deve ter as
  colunas `hora,demanda_kw,dia_semana`, com 24 horas para `util` e 24 horas
  para `fim_semana`;
- `grafo_conexoes`, contendo as ligações entre os identificadores dos
  equipamentos;
- `geradordiesel_info[0]`, com os seguintes campos.

| Campo | Unidade | Uso |
|---|---:|---|
| `diesel_id` | texto | nome do equipamento e vínculo com o grafo |
| `potencia_nominal_kw` | kW | potência aparente de referência do grupo |
| `potencia_minima_kw` | kW | limite inferior operacional |
| `potencia_maxima_kw` | kW | limite superior operacional; default é a nominal |
| `tensao_nominal` | V | convertido para `vn_kv` no pandapower |
| `frequencia` | Hz | referência do equipamento |
| `fator_potencia` | pu | convertido para `cos_phi` |
| `xdss_pu` | pu | reatância subtransitória para curto-circuito |
| `rdss_ohm` | ohm | resistência subtransitória para curto-circuito |
| `quantidade` | inteiro/lista | quantidade de grupos |

Parâmetros econômicos opcionais do grupo:

| Campo | Unidade | Uso |
|---|---:|---|
| `custo_oleo_diesel_por_litro` | R$/L | preço do óleo diesel; default 0 |
| `consumo_especifico_litros_por_kwh` | L/kWh | consumo específico; default 0,25 |
| `custo_equipamento` | R$ por grupo | CAPEX opcional; zero significa equipamento existente |

Os aliases legados `custo_diesel_litro`, `consumo_diesel_l_kwh` e
`custo_investimento` também são aceitos. O custo do combustível é calculado
como `energia_diesel_kwh × consumo_especifico_litros_por_kwh ×
custo_oleo_diesel_por_litro`. O CAPEX é contabilizado uma vez por grupo,
multiplicado por `quantidade`, e fica separado do custo operacional.

O limite de operação pode ser informado no bloco do gerador, por exemplo:

```json
{
  "geradordiesel_info": [{
    "diesel_id": "Diesel_1",
    "potencia_nominal_kw": 275,
    "custo_oleo_diesel_por_litro": 6.50,
    "consumo_especifico_litros_por_kwh": 0.25,
    "custo_equipamento": 0,
    "operacao": {"tempo_operacao_h": 8}
  }]
}
```

`tempo_operacao_h` é o limite acumulado de horas de despacho no horizonte
simulado; zero impede o despacho e valor ausente não limita a operação. Para o
regime permanente, também pode ser configurado em
`estudos.regime_permanente.tempo_operacao_gerador_h` ou sobrescrito pela CLI
com `--tempo-operacao-gerador-h`.

O resultado do regime permanente inclui `analise_economica`, com horas reais de
operação, energia gerada, litros consumidos, custo do óleo, CAPEX considerado,
custo operacional e custo total do período. O custo do equipamento não é
anualizado nem rateado entre horas.

No modo ilhado, o adaptador cria um elemento `pandapower.gen` síncrono com
`slack=true`, preenchendo `sn_mva`, `vn_kv`, `xdss_pu`, `rdss_ohm`, `cos_phi`,
`min_p_mw` e `max_p_mw`. Assim o mesmo arquivo pode alimentar fluxo AC e a
análise de curto-circuito independente (`falhas.py`).

Para o regime permanente, `soc_inicial`, `soc_min` e `soc_max` do BESS são
percentuais entre 0 e 100. Os limites de potência e a capacidade são informados
em kW e kWh.

## Arquivo único

No arquivo `Entradas_microrrede_completa.json`, os equipamentos aparecem uma
única vez. O bloco `estudos` separa somente os parâmetros de execução:

- `estudos.regime_permanente`: `periodo`, `tipo_dia`, `ano` e `horas`;
- `estudos.transitorio`: `Passo_sim` e `Tempo_sim`.

O bloco `Config_Simulacao` continua no formato legado e identifica o caso
transitório padrão. O comando de regime permanente usa `estudos` quando os
parâmetros não são informados na linha de comando.

No transitório combinado, `geradordiesel_info` ativa o acoplamento do modelo
`GeradorDiesel` ao balanço de PV+BESS. O resultado inclui a série de potência,
frequência, tensão, SOC, degrau de carga, curto-circuito e os resultados de
fluxo/falhas da rede pandapower construída pelo mesmo JSON.

## Transitório isolado

Execute:

```powershell
.venv\Scripts\python.exe -m microrredes transitorio-gerador-diesel `
  --entrada Entradas\Entradas_transitorio_gerador_diesel.json `
  --saida resultados\transitorio_gerador_diesel.json

.venv\Scripts\python.exe -m microrredes transitorio-bess-fv `
  --entrada Entradas\Entradas_microrrede_completa.json `
  --saida resultados\transitorio_microrrede_completa.json
```

O bloco `Config_Simulacao` informa `Passo_sim` em segundos e `Tempo_sim` em
segundos. O bloco `rede_teste` informa a carga inicial, o fator de potência e
os parâmetros da linha entre o gerador e o PCC. O bloco `gerador_diesel`
contém:

- limites e condição inicial de potência;
- tensão e frequência nominais;
- inércia, droop, constantes de tempo do governador e do motor;
- ganho, referência e limites do AVR;
- `xdss_pu`, `xd_pu`, `rdss_ohm` e a constante de decaimento da corrente de
  curto.

Cada evento de `eventos` deve ter `tipo` e `inicio_s`. Use:

- `degrau_carga` com `carga_kw` para alterar a carga;
- `curto_circuito_3ph` com `duracao_s` e, opcionalmente,
  `resistencia_falta_ohm` e `reatancia_falta_ohm`.

O módulo integra as equações diferenciais de primeira ordem do governador,
motor, balanço de frequência, ângulo do rotor e AVR em
`Equipamentos/gerador_diesel.py`. O fluxo inicial e o `ikss` no PCC são
calculados pelo `pandapower.gen`; a evolução temporal usa o componente
dinâmico reutilizável. No arquivo único, esse componente é integrado ao
transitório FV+BESS; o arquivo separado continua disponível para ensaio
isolado.

O arquivo antigo `Entradas/gerador_diesel_teste.json` continua aceito. Também
são aceitos os aliases legados `geradordiesel_info`, `diesel_id`,
`tensao_nominal`, `frequencia` e `fp` no bloco do gerador.

## Ligacao do diesel em paralelo com a rede

O caso `Entradas/Entradas_transitorio_diesel_ligacao_rede.json` deixa a carga
atendida pela distribuidora desde o instante inicial e conecta o grupo em
`t=0,1 s`. Para configurar esse evento em outro arquivo, use:

```json
{
  "tipo": "ligacao_gerador_rede",
  "inicio_s": 0.1
}
```

Defina `conectado_rede: true` e `potencia_inicial_kw: 0` no gerador. Tambem
sao aceitos os tipos `ligacao_diesel_rede`, `conexao_gerador` e
`entrada_gerador_rede`. Antes do evento, `gerador_ligado` vale zero e
`rede_kw` atende a carga. Depois, o diesel e habilitado e a serie mostra a
resposta do governador/motor em `potencia_mecanica_diesel_kw`, frequencia e
tensao do PCC.

Execute com:

```powershell
.venv\Scripts\python.exe -m microrredes transitorio-bess-fv `
  --entrada Entradas\Entradas_transitorio_diesel_ligacao_rede.json `
  --saida resultados\transitorio_diesel_ligacao_rede.json
```
