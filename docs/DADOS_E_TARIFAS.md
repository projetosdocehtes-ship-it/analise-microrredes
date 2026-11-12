# Dados tarifários e ICMS

## Fonte de verdade

O módulo `microrredes.dados.tarifas_aneel.ClienteTarifasANEEL` consulta o conjunto oficial de tarifas de aplicação das distribuidoras da ANEEL por meio da API CKAN. Se a API CKAN estiver indisponível, ele tenta o CSV oficial do mesmo recurso, filtrando a distribuidora e o grupo sem alterar a fonte de verdade. A consulta seleciona a vigência aplicável à data de referência e mantém a origem no resultado (`ANEEL_CKAN` ou `ANEEL_CSV`).

Fonte: <https://dadosabertos.aneel.gov.br/dataset/tarifas-distribuidoras-energia-eletrica>

Recurso CSV: <https://dadosabertos.aneel.gov.br/dataset/5a583f3e-1646-4f67-bf0f-69db4203e89e/resource/fcf2906c-7c32-4b9b-a637-054e7a5234f4/download/tarifas-homologadas-distribuidoras-energia-eletrica.csv>

## Cache local

Após uma consulta online válida, o cliente grava automaticamente os registros
filtrados em `microrredes/dados/cache/tarifas_aneel_cache.json`. O cache possui
versão de schema, distribuidora/grupo, registros usados, vigência, fonte e
data UTC da atualização. Em uma nova execução sem conexão, o resultado é
marcado como `ANEEL_CACHE` e inclui a idade do cache e eventual aviso de
expiração. A validade padrão é de 7 dias; o cache vencido continua disponível
offline, mas fica explicitamente sinalizado.

Para usar outro arquivo ou exigir cache fresco:

```powershell
python -m microrredes fundamentais `
  --cache-tarifas D:\dados\tarifas_aneel_cache.json `
  --ttl-cache-dias 7 --nao-usar-cache-expirado
```

O arquivo é ignorado pelo Git para não versionar valores tarifários locais;
ele é preenchido na primeira consulta bem-sucedida à ANEEL.

O fallback local não representa garantia de atualização. Ele só é usado com `permitir_fallback=True` ou `--usar-fallback`, e o resultado fica marcado como `fallback_local_nao_atualizado`.

## Qualidade e linhagem

As regras mínimas são:

- `DQ-TAR-001`: resposta CKAN deve informar sucesso e registros;
- `DQ-TAR-002`: registros devem pertencer ao grupo solicitado;
- `DQ-TAR-003`: seleção deve preferir `Tarifa de Aplicação` e maior vigência válida;
- `DQ-TAR-004`: modalidades devem ter componentes positivos suficientes para o cálculo;
- `DQ-TAR-005`: valores monetários devem ser normalizados de formato brasileiro e unidades MWh/kWh;
- `DQ-TAR-006`: o snapshot deve carregar fonte, vigência, instante UTC e contagem de registros.

Falhas de esquema, domínio e conectividade são classificadas como erro de fonte. Não há credenciais ou payload sensível nessa integração.

## ICMS

Use `icms=0.19` para 19%. O cálculo do consumo é:

```text
valor_com_ICMS = valor_sem_ICMS / (1 - aliquota)
ICMS = valor_com_ICMS - valor_sem_ICMS
```

A alíquota deve ser conferida pelo responsável pelo estudo para o estado, classe, consumidor e período aplicáveis. PIS/COFINS, bandeiras, descontos, créditos de energia e regras específicas de SCEE ainda não fazem parte deste contrato e devem ser adicionados separadamente.
