# Arquivo de falhas transitórias

O cenário inicial de perda de strings está em:

`sim-stable/Arquivos_Temp_Json/Falhas_sim.json`

Ele representa:

- energização em `t = 0 s`;
- perda de 4 de 16 strings do `PV_1` em `t = 0,5 s`;
- duração da falha de `0,25 s`;
- retorno das strings em `t = 0,75 s`.

O tipo `Perda_String_FV` agora é classificado para `falhas_paineis` e reduz a quantidade de strings paralelas usadas no cálculo de potência durante a janela do evento.

O `sim.py` aceita falhas embutidas em `Entradas.json` ou carrega automaticamente `Falhas_sim.json` da pasta `Arquivos_Temp_Json`. Ainda é necessário fornecer um `Arquivos_Temp_Json/Entradas.json` completo e compatível com o simulador para executar o transitório integral; o antigo `Entradas.json` da raiz está preservado em `old/artefatos_raiz/` e pertence a outro esquema de entrada.

## Execução reproduzível do caso on-grid

Para gerar imediatamente as curvas em segundos a partir de um `Entradas.Json` externo:

```powershell
python -m microrredes transitorio-bess-fv `
  --entrada D:\downloads\Downloads2\Entradas.Json `
  --consumo-dia-kwh 650 --pv-kwp 80 --bess-kwh 100 --bess-kw 40 `
  --strings-fv 16 --strings-perdidas 4 --forcar-on-grid `
  --saida resultados\transitorio\resultado_transitorio_bess_fv.json `
  --graficos-dir resultados\transitorio
```

Para gerar também um gráfico HTML interativo, inclua:

```powershell
  --html-interativo resultados\transitorio\transitorio_interativo.html
```

O HTML contém todos os passos da simulação, funciona offline e permite ver
os valores ao passar o cursor, ampliar um intervalo arrastando e usar a roda
do mouse para zoom. Os PNGs feitos com Matplotlib continuam disponíveis.

Esse comando usa `Passo_sim` e `Tempo_sim` do arquivo de entrada, aplica a
falha de `t = 0,5 s` a `0,75 s` e salva duas figuras: balanço de potência/SOC
e grandezas no PCC. O modelo é transitório reduzido por funções de primeira
ordem, adequado para o estudo de energização e contingência em segundos; ele
deve ser distinguido de um EMT detalhado das chaves e do filtro do inversor.
