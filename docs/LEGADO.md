# Código legado

Os scripts antigos estão em `old/codigo/` e não participam da API nova. Eles incluem análises de fluxo de potência, cenários BESS/PV, análises estocásticas, otimização, tarifas e testes exploratórios. Os documentos e notebooks anteriores estão em `old/documentacao/` e `old/notebooks/`.

Os 74 arquivos antigos que estavam soltos na raiz (CSV, PNG, DOCX, ZIP, 7Z, log e o `Entradas.json` de outro esquema) estão em `old/artefatos_raiz/`. O conteúdo foi preservado para auditoria e comparação. Não se deve importar módulos de `old/` na camada `microrredes/`; novas funcionalidades devem entrar em módulos com contrato, testes e documentação.

O simulador dinâmico não foi arquivado: `sim-stable/` e `Equipamentos/` continuam na raiz por serem o núcleo novo informado para análises transitórias.
