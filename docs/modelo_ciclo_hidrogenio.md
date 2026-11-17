# Modelo integrado de producao e geracao com hidrogenio

## Escopo

O ciclo e composto por tres equipamentos: eletrolisador PEM (PEME), armazenamento de H2 e celula a combustivel PEM (PEMFC). O PEME consome energia eletrica e produz H2; a PEMFC consome H2 e injeta energia eletrica na microrrede. O inventario do tanque conecta os dois lados. Este modelo nao representa compressor, tratamento de agua, auxiliares (BoP), perdas termicas, pressao, temperatura, agua, purgas nem degradacao.

O comparativo de geracao deve manter duas alternativas distintas depois do tanque: PEMFC e motor reciprocante alimentado por H2. A PEMFC e o caminho eletroquimico mais coerente com o PEME; o motor e uma alternativa de gerador que precisa de modelo proprio de combustao, eficiencia, limites de carga e rampa. Eles compartilham o inventario do tanque, mas nao o mesmo modelo de stack.

## Convencoes e equacoes

Corrente positiva no PEME significa consumo e producao de H2. Corrente positiva na PEMFC significa geracao eletrica e consumo de H2. Para os dois equipamentos, parametros do equivalente eletrico sao por celula.

No PEME, usa-se o equivalente de um estado EEC 10: estado x = V_dle, corrente por string i_cell = I_stack/N_parallel, dinamica dV_dle/dt = (i_cell - V_dle/(R_act + R_con))/C_dle e tensao V_stack = N_series (V_rev + R_ohm i_cell + V_dle). A potencia CC absorvida e P_stack = V_stack I_stack.

No PEMFC, usa-se a forma de um estado do circuito de dupla camada: x = V_dle, dV_dle/dt = (i_cell - V_dle/(R_act + R_con))/C_dle e V_stack = N_series (V_oc - R_ohm i_cell - V_dle). A potencia CC exportada e P_stack = V_stack I_stack. O ponto permanente e calculado com dx/dt = 0.

As vazoes molares ideais decorrem da lei de Faraday, com F = 96485.33212 C/mol: producao PEME = N_series I_stack eta_F/(2F); consumo reagido PEMFC = N_series I_stack/(2F). A vazao de H2 retirada do tanque divide-se pela utilizacao de combustivel, quando ela e menor que 1. A conversao para kg/s multiplica a vazao molar pela massa molar de H2 (2.01588e-3 kg/mol).

O tanque usa balanco de massa: dm_H2/dt = vazao_produzida - vazao_consumida. O modelo deve limitar ou sinalizar operacao quando a massa sair dos limites 0 <= m_H2 <= capacidade. Ele nao calcula pressao sem volume, temperatura e equacao de estado.

## Interface com fluxo de potencia

No fluxo de potencia pandapower, o PEME e uma carga positiva. A PEMFC e uma injecao positiva de geracao (sgen) na operacao conectada a rede, com potencia reativa especificada ou fator de potencia. Em ilha, a PEMFC so pode manter a tensao se o equipamento e o controle forem tratados como fonte formadora de rede/slack; uma injecao sgen por si so nao define referencia angular e de tensao. Se o conversor PEMFC for apenas grid-following, a rede precisa de outro slack.

No regime permanente, a tensao de polarizacao e avaliada no equilibrio e o ponto de operacao retorna potencia e vazao de H2. Na simulacao transitoria, as correntes sao entradas dos modelos de stack e as tensoes de polarizacao sao estados. A evolucao de corrente/potencia do conversor nao e inferida pelo modelo eletroquimico: deve vir do controlador ou do estudo.

## Alternativa de geracao: motor reciprocante a H2

Para comparacao em estudos de microrrede, o motor comeca por um equivalente reduzido em `Equipamentos/gerador_motor_hidrogenio.py`. O estado e a potencia eletrica entregue P_e; a referencia e P_ref. A dinamica de primeira ordem com limitador de rampa e dP_e/dt = clip((P_ref - P_e)/tau_m, -rampa_max, +rampa_max), com P_e limitado entre zero e a potencia nominal. No regime permanente, P_e = P_ref dentro dos limites do equipamento. A vazao de H2 e mdot_H2 = P_e/(eta_e,net * PCI_H2), usando eficiencia eletrica liquida referida ao PCI. A mesma vazao alimenta o balanco do tanque.

Essa representacao nao modela combustao dentro do cilindro, torque, velocidade do eixo, sincronizacao do alternador, mistura de combustiveis, emissoes ou partida/parada. A curva de eficiencia e os limites/rampas devem vir do fabricante. O relatorio consultado indica, como referencia de archetypes de motores reciprocantes a gas configurados para H2, eficiencia liquida tipica de 40-45% (43-50% state-of-the-art) e rampa media de 20-50% da potencia nominal por minuto; trata-se de referencia de classe, nao de parametro universal de um motor H2 especifico.

Na comparacao de classe, o mesmo relatorio indica para PEMFC cerca de 50% de eficiencia liquida no PCI, dependente da carga, partida a frio de 5-10 min e rampa media acima de 10% da potencia nominal por minuto. PEMFC exige H2 de alta pureza; motor reciprocante tem resposta de rampa mais alta e maior tolerancia a impurezas, mas usa combustao e deve ser parametrizado com limites de emissao e configuracao do combustivel. Os numeros nao substituem dados de equipamento.

## PEMFC Padulles-I com resposta transitoria

O comando `transitorio-ciclo-hidrogenio` aceita `modelo_transitorio: "opem_padulles_i"` dentro de `gerador_hidrogenio_info`. O componente `Equipamentos/gerador_pemfc_opem.py` acompanha as pressoes parciais de H2 e O2 como estados:

```text
dPH2/dt = (PH2_equilibrio(I) - PH2) / tH2
dPO2/dt = (PO2_equilibrio(I) - PO2) / tO2
PH2_equilibrio = (qH2 - N0*I/(2F)) / KH2
PO2_equilibrio = (qH2/rho - N0*I/(4F)) / KO2
Vstack = N0*(E0 + R*T/(2F)*ln(PH2*sqrt(PO2))) - B*ln(C*I) - Rint*I
```

Os parametros aceitam os nomes do OPEM (`N0`, `E0`, `T`, `KH2`, `KO2`, `tH2`, `tO2`, `B`, `C`, `Rint`, `rho`, `qH2`) ou os nomes explicitos do projeto. Corrente inicial e degraus em `eventos` sao entradas prescritas. A serie temporal reporta corrente, tensao, termos de Nernst/ativacao/ohmica, potencia, PH2, PO2, utilizacao e H2 reagido.

O `Dynamic_Analysis` do OPEM calcula PH2/PO2 algebricamente para cada ponto de corrente. Este projeto usa as equacoes de tensao e balancos molares do Padulles-I e integra os estados de pressao no tempo para produzir um transitorio. E uma extensao temporal do modelo, nao uma reproducao bit a bit do algoritmo de varredura do OPEM. Consulte o [codigo Padulles1.py do OPEM](https://github.com/ECSIM/opem/blob/master/opem/Dynamic/Padulles1.py) e o [vetor de teste PadullesI](https://github.com/ECSIM/opem#library).

O passo deve ser no maximo `min(tH2,tO2)/5`. O fluxo `qH2` e uma alimentacao prescrita e e debitado do tanque continuamente; H2 reagido/utilizacao sao calculados a parte. O modelo nao inclui purga, recirculacao, pressao do tanque, auxiliares, conversor, sincronismo, controlador de corrente nem resposta da rede AC. Use parametros medidos do stack para resultados de engenharia. O exemplo executavel `Entradas/ciclo_pemfc_opem_padulles_demo.json` usa os parametros de referencia do OPEM e valores placeholder no eletrolisador, que fica desligado.

## Parametros e limites

Nao ha um conjunto universal de parametros para qualquer stack. Obter parametros eletricos de curva de polarizacao, ficha tecnica e ensaio de resposta; obter eficiencia faradaica e utilizacao de H2 de dados do equipamento. A eficiencia eletrica total da planta deve incluir conversor e auxiliares separadamente. Nao confundir eficiencia faradaica (balanco de H2) com eficiencia eletrica.

O EEC de um estado e reduzido e precisa de identificacao experimental para representar a dinamica do stack escolhido. A literatura tambem reporta modelos mais detalhados e modelos termicos; validar o equivalente escolhido antes de usar resultados como previsao de equipamento real.

## Referencias

- Tofighi-Milani, Fattaheian-Dehkordi e Lehtonen, “Electrolysers: A Review on Trends, Electrical Modeling, and Their Dynamic Responses”, IEEE Access, 2025, DOI [10.1109/ACCESS.2025.3546546](https://doi.org/10.1109/ACCESS.2025.3546546). Apresenta circuitos equivalentes PEME EEC 9 e EEC 10.
- San Martin, Ursua e Sanchis, “Modelling of PEM Fuel Cell Performance: Steady-State and Dynamic Experimental Validation”, Energies, 2014, [DOI 10.3390/en7020670](https://www.mdpi.com/1996-1073/7/2/670). Descreve modelo eletrico PEMFC e validacao estacionaria e dinamica, incluindo efeito de dupla camada.
- U.S. DOE / DESNZ, “Hydrogen to Power Costs and Barriers Assessment”, 2025, [relatorio](https://assets.publishing.service.gov.uk/media/69663541e8b93f59c3aecd76/hydrogen-to-power-cost-barriers.pdf). Compara tecnologias de geracao a hidrogenio, incluindo celulas a combustivel e motores reciprocantes.
- “Modelling and Simulation of a PEM Water Electrolysis System”, Electronics, 2020, [DOI 10.3390/electronics9050871](https://www.mdpi.com/2072-9292/9/5/871). Fonte para o balanco faradaico de producao de H2.
