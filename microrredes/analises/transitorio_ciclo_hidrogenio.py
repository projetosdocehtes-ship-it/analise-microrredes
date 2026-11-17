"""Simulação reduzida integrada de produção, estoque e geração com H₂ PEM."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
import math
from pathlib import Path
from typing import Any

from Equipamentos.celula_combustivel_pem import (
    CelulaCombustivelPEM,
    ParametrosCelulaCombustivelPEM,
)
from Equipamentos.eletrolisador_pem import EletrolisadorPEM, ParametrosEletrolisadorPEM
from Equipamentos.hidrogenio import (
    ParametrosTanqueHidrogenio,
    TanqueHidrogenio,
    calcular_vazao_h2_celula_combustivel,
    calcular_vazao_h2_eletrolisador,
)
from Equipamentos.gerador_motor_hidrogenio import (
    GeradorMotorHidrogenio,
    ParametrosMotorHidrogenio,
)
from Equipamentos.gerador_pemfc_opem import (
    GeradorPEMFCOpem,
    ParametrosGeradorPEMFCOpem,
)


@dataclass(frozen=True)
class EventoCorrenteCicloHidrogenio:
    componente: str
    inicio_s: float
    corrente_stack_A: float | None = None
    duracao_s: float | None = None
    potencia_referencia_kw: float | None = None

    def __post_init__(self) -> None:
        if self.componente not in {"eletrolisador", "gerador"}:
            raise ValueError("componente do evento deve ser eletrolisador ou gerador")
        if not _finito(self.inicio_s) or self.inicio_s < 0:
            raise ValueError("inicio_s deve ser não negativo e finito")
        if self.corrente_stack_A is not None and (
            not _finito(self.corrente_stack_A) or self.corrente_stack_A < 0
        ):
            raise ValueError("corrente_stack_A deve ser não negativa e finita")
        if self.potencia_referencia_kw is not None and (
            not _finito(self.potencia_referencia_kw) or self.potencia_referencia_kw < 0
        ):
            raise ValueError("potencia_referencia_kw deve ser não negativa e finita")
        if self.componente == "eletrolisador" and self.corrente_stack_A is None:
            raise ValueError("eventos do eletrolisador devem informar corrente_stack_A")
        if self.componente == "gerador" and (
            (self.corrente_stack_A is None) == (self.potencia_referencia_kw is None)
        ):
            raise ValueError(
                "eventos do gerador devem informar corrente_stack_A (PEMFC) "
                "ou potencia_referencia_kw (motor), exatamente um"
            )
        if self.duracao_s is not None and (
            not _finito(self.duracao_s) or self.duracao_s <= 0
        ):
            raise ValueError("duracao_s deve ser positiva e finita")

    @property
    def fim_s(self) -> float | None:
        return None if self.duracao_s is None else self.inicio_s + self.duracao_s

    def ativo(self, instante_s: float) -> bool:
        return instante_s >= self.inicio_s and (
            self.fim_s is None or instante_s < self.fim_s
        )


@dataclass(frozen=True)
class ConfiguracaoTransitorioCicloHidrogenio:
    eletrolisador: ParametrosEletrolisadorPEM
    gerador: (
        ParametrosCelulaCombustivelPEM
        | ParametrosGeradorPEMFCOpem
        | ParametrosMotorHidrogenio
    )
    tanque: ParametrosTanqueHidrogenio
    eficiencia_faradaica: float
    utilizacao_h2: float | None
    passo_s: float
    duracao_s: float
    corrente_eletrolisador_inicial_A: float = 0.0
    corrente_gerador_inicial_A: float = 0.0
    potencia_gerador_inicial_kw: float = 0.0
    potencia_gerador_referencia_kw: float = 0.0
    quantidade_eletrolisadores: int = 1
    quantidade_geradores: int = 1
    estado_inicial_eletrolisador: tuple[float, ...] | None = None
    estado_inicial_gerador: tuple[float, ...] | None = None
    eventos: tuple[EventoCorrenteCicloHidrogenio, ...] = ()

    def __post_init__(self) -> None:
        self.eletrolisador.validar_dinamica()
        if not _finito(self.passo_s) or self.passo_s <= 0:
            raise ValueError("passo_s deve ser positivo e finito")
        if not _finito(self.duracao_s) or self.duracao_s <= 0:
            raise ValueError("duracao_s deve ser positiva e finita")
        if not 0 < self.eficiencia_faradaica <= 1:
            raise ValueError("eficiencia_faradaica deve estar no intervalo (0, 1]")
        if self.utilizacao_h2 is not None and not 0 < self.utilizacao_h2 <= 1:
            raise ValueError("utilizacao_h2 deve estar no intervalo (0, 1]")
        for nome in ("quantidade_eletrolisadores", "quantidade_geradores"):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
                raise ValueError(f"{nome} deve ser um inteiro positivo")
        for nome in ("corrente_eletrolisador_inicial_A", "corrente_gerador_inicial_A"):
            valor = getattr(self, nome)
            if not _finito(valor) or valor < 0:
                raise ValueError(f"{nome} deve ser não negativa e finita")
        if not _finito(self.potencia_gerador_inicial_kw) or self.potencia_gerador_inicial_kw < 0:
            raise ValueError("potencia_gerador_inicial_kw deve ser não negativa e finita")
        if not _finito(self.potencia_gerador_referencia_kw) or self.potencia_gerador_referencia_kw < 0:
            raise ValueError("potencia_gerador_referencia_kw deve ser não negativa e finita")
        if isinstance(self.gerador, ParametrosMotorHidrogenio):
            if self.gerador.constante_tempo_s is None or self.gerador.rampa_max_kw_min is None:
                raise ValueError("O modelo transitório do motor requer constante de tempo e rampa máxima")
            if self.potencia_gerador_inicial_kw > self.gerador.potencia_nominal_kw:
                raise ValueError("A potência inicial do motor excede o valor nominal")
            if self.potencia_gerador_referencia_kw > self.gerador.potencia_nominal_kw:
                raise ValueError("A referência de potência do motor excede o valor nominal")
            tau_gerador = self.gerador.constante_tempo_s
            if any(
                evento.componente == "gerador" and evento.potencia_referencia_kw is None
                for evento in self.eventos
            ):
                raise ValueError("eventos do motor devem informar potencia_referencia_kw")
            for evento in self.eventos:
                if evento.componente == "gerador" and evento.potencia_referencia_kw is not None:
                    GeradorMotorHidrogenio(self.gerador)._validar_referencia(
                        evento.potencia_referencia_kw
                    )
        elif isinstance(self.gerador, ParametrosGeradorPEMFCOpem):
            tau_gerador = self.gerador.menor_constante_tempo_s
            correntes = [self.corrente_gerador_inicial_A]
            correntes.extend(
                evento.corrente_stack_A
                for evento in self.eventos
                if evento.componente == "gerador"
                and evento.corrente_stack_A is not None
                and evento.inicio_s <= self.duracao_s
            )
            corrente_maxima = max(correntes, default=0.0)
            h2_consumido = (
                self.gerador.n_series_cells
                * corrente_maxima
                / (2.0 * 96_485_332.12)
            )
            o2_consumido = (
                self.gerador.n_series_cells
                * corrente_maxima
                / (4.0 * 96_485_332.12)
            )
            if h2_consumido >= self.gerador.q_h2_kmol_s:
                raise ValueError("q_h2_kmol_s não atende a maior corrente PEMFC configurada")
            if o2_consumido >= self.gerador.q_o2_kmol_s:
                raise ValueError("q_h2_kmol_s/rho_h2_o2 não atende a maior corrente PEMFC")
            if any(
                evento.componente == "gerador" and evento.potencia_referencia_kw is not None
                for evento in self.eventos
            ):
                raise ValueError("eventos da PEMFC devem informar corrente_stack_A")
        else:
            tau_gerador = self.gerador.constante_tempo_s
            if any(
                evento.componente == "gerador" and evento.corrente_stack_A is None
                for evento in self.eventos
            ):
                raise ValueError("eventos da PEMFC devem informar corrente_stack_A")
            if any(
                evento.componente == "gerador" and evento.potencia_referencia_kw is not None
                for evento in self.eventos
            ):
                raise ValueError("eventos da PEMFC não usam potencia_referencia_kw")
        menor_tau = min(
            min(self.eletrolisador.constantes_tempo_s),
            tau_gerador,
        )
        if self.passo_s > menor_tau / 5.0:
            raise ValueError("passo_s deve ser no máximo 1/5 da menor constante de tempo")

    @classmethod
    def from_json(cls, caminho: str | Path) -> "ConfiguracaoTransitorioCicloHidrogenio":
        arquivo = Path(caminho).expanduser().resolve()
        if not arquivo.is_file():
            raise FileNotFoundError(f"Arquivo de configuração não encontrado: {arquivo}")
        try:
            documento = json.loads(arquivo.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON de configuração inválido: {arquivo}") from exc
        if not isinstance(documento, dict):
            raise ValueError("A configuração do ciclo de H₂ deve ser um objeto JSON")

        dados_el = _registro(documento, "eletrolisador_pem_info")
        dados_fc = _registro(documento, "gerador_hidrogenio_info")
        if not dados_fc:
            dados_fc = _registro(documento, "celula_combustivel_pem_info")
        dados_motor = _registro(documento, "motor_hidrogenio_info")
        dados_tanque = _registro(documento, "armazenamento_hidrogenio_info")
        if not dados_tanque:
            dados_tanque = _registro(documento, "tanque_hidrogenio_info")
        if not dados_el or not (dados_fc or dados_motor) or not dados_tanque:
            raise ValueError(
                "Informe eletrolisador_pem_info, um gerador PEMFC ou motor_hidrogenio_info e "
                "armazenamento_hidrogenio_info"
            )
        if dados_fc and dados_motor:
            raise ValueError(
                "No transitório de ciclo selecione apenas um gerador por execução: PEMFC ou motor H2"
            )

        p_el = _parametros_eletrolisador(dados_el)
        if dados_motor:
            p_gerador = _parametros_motor(dados_motor)
        elif str(dados_fc.get("modelo_transitorio", "")).strip().lower().replace("-", "_") in {
            "opem_padulles_i",
            "padulles_i",
        }:
            p_gerador = _parametros_gerador_opem(dados_fc)
        else:
            p_gerador = _parametros_gerador(dados_fc)
        p_tanque = ParametrosTanqueHidrogenio(
            capacidade_kg=_numero(dados_tanque.get("capacidade_kg"), "capacidade_kg"),
            massa_inicial_kg=_numero(
                dados_tanque.get("massa_inicial_kg"), "massa_inicial_kg"
            ),
        )

        estudos = documento.get("estudos") or {}
        estudo = {}
        if isinstance(estudos, dict):
            estudo = (
                estudos.get("transitorio_ciclo_hidrogenio")
                or estudos.get("transitorio_hidrogenio")
                or {}
            )
        if isinstance(estudo, list):
            estudo = estudo[0] if estudo else {}
        if not isinstance(estudo, dict):
            raise ValueError("estudos.transitorio_ciclo_hidrogenio deve ser um objeto")

        dados_eventos = documento.get("eventos", [])
        if not isinstance(dados_eventos, list) or any(
            not isinstance(evento, dict) for evento in dados_eventos
        ):
            raise ValueError("eventos deve ser uma lista de objetos")
        eventos = tuple(
            EventoCorrenteCicloHidrogenio(
                componente=str(item.get("componente", "")),
                inicio_s=_numero(item.get("inicio_s"), "inicio_s"),
                corrente_stack_A=_opcional_numero(
                    item.get("corrente_stack_A"), "corrente_stack_A"
                ),
                duracao_s=(
                    _numero(item["duracao_s"], "duracao_s")
                    if item.get("duracao_s") is not None
                    else None
                ),
                potencia_referencia_kw=_opcional_numero(
                    item.get("potencia_referencia_kw"), "potencia_referencia_kw"
                ),
            )
            for item in dados_eventos
        )
        return cls(
            eletrolisador=p_el,
            gerador=p_gerador,
            tanque=p_tanque,
            eficiencia_faradaica=_numero(
                dados_el.get("eficiencia_faradaica"), "eficiencia_faradaica"
            ),
            utilizacao_h2=(
                _numero(dados_fc.get("utilizacao_h2"), "utilizacao_h2")
                if dados_fc and not isinstance(p_gerador, ParametrosGeradorPEMFCOpem)
                else None
            ),
            passo_s=_numero(estudo.get("passo_s"), "passo_s"),
            duracao_s=_numero(estudo.get("duracao_s"), "duracao_s"),
            corrente_eletrolisador_inicial_A=_numero(
                estudo.get("corrente_eletrolisador_inicial_A", 0.0),
                "corrente_eletrolisador_inicial_A",
            ),
            corrente_gerador_inicial_A=(
                _numero(estudo.get("corrente_gerador_inicial_A", 0.0), "corrente_gerador_inicial_A")
                if dados_fc
                else 0.0
            ),
            potencia_gerador_inicial_kw=(
                _numero(
                    estudo.get("potencia_gerador_inicial_kw", dados_motor.get("potencia_inicial_kw", 0.0)),
                    "potencia_gerador_inicial_kw",
                )
                if dados_motor
                else 0.0
            ),
            potencia_gerador_referencia_kw=(
                _numero(
                    estudo.get("potencia_gerador_referencia_kw", dados_motor.get("potencia_referencia_kw", 0.0)),
                    "potencia_gerador_referencia_kw",
                )
                if dados_motor
                else 0.0
            ),
            quantidade_eletrolisadores=_inteiro(
                dados_el.get("quantidade", 1), "quantidade_eletrolisadores"
            ),
            quantidade_geradores=_inteiro(
                (dados_motor or dados_fc).get("quantidade", 1), "quantidade_geradores"
            ),
            estado_inicial_eletrolisador=_estado(estudo.get("estado_inicial_eletrolisador")),
            estado_inicial_gerador=_estado(estudo.get("estado_inicial_gerador")),
            eventos=eventos,
        )


class TransitorioCicloHidrogenio:
    """Integra PEME, tanque e uma alternativa de gerador a hidrogênio."""

    def __init__(self, configuracao: ConfiguracaoTransitorioCicloHidrogenio):
        self.configuracao = configuracao

    def executar(self) -> dict[str, Any]:
        cfg = self.configuracao
        tempo = self._linha_do_tempo()
        eletrolisador = EletrolisadorPEM(cfg.eletrolisador)
        eletrolisador.inicializar(
            cfg.corrente_eletrolisador_inicial_A,
            cfg.estado_inicial_eletrolisador,
        )
        eh_motor = isinstance(cfg.gerador, ParametrosMotorHidrogenio)
        eh_padulles = isinstance(cfg.gerador, ParametrosGeradorPEMFCOpem)
        if eh_motor:
            gerador = GeradorMotorHidrogenio(cfg.gerador)
            potencia_gerador_kw = cfg.potencia_gerador_inicial_kw
        elif eh_padulles:
            gerador = GeradorPEMFCOpem(cfg.gerador)
            gerador.inicializar(
                cfg.corrente_gerador_inicial_A,
                cfg.estado_inicial_gerador,
            )
        else:
            gerador = CelulaCombustivelPEM(cfg.gerador)
            gerador.inicializar(
                cfg.corrente_gerador_inicial_A,
                cfg.estado_inicial_gerador,
            )
        tanque = TanqueHidrogenio(cfg.tanque)
        serie: list[dict[str, Any]] = []

        for indice, instante in enumerate(tempo):
            corrente_el, evento_el = self._corrente_no_instante(instante, "eletrolisador")
            saida_el = eletrolisador.calcular_saida(corrente_el)
            vazao_prod = calcular_vazao_h2_eletrolisador(
                cfg.eletrolisador.n_series_cells,
                corrente_el,
                cfg.eficiencia_faradaica,
                cfg.quantidade_eletrolisadores,
            )
            if eh_motor:
                referencia_gerador_kw, evento_gerador = self._referencia_motor_no_instante(instante)
                saida_gerador = gerador.saidas(potencia_gerador_kw)
                potencia_gerador_total_W = saida_gerador.potencia_eletrica_kw * 1000.0 * cfg.quantidade_geradores
                consumo_h2_kg_s = saida_gerador.consumo_h2_kg_s * cfg.quantidade_geradores
                tensao_gerador_stack_V = None
                nernst_gerador_stack_V = None
                queda_ativacao_gerador_V = None
                queda_ohmica_gerador_V = None
                corrente_gerador_A = None
                estado_gerador_v_dle = None
                estado_gerador_p_kw = potencia_gerador_kw
                pressao_h2_gerador_atm = None
                pressao_o2_gerador_atm = None
                utilizacao_h2_gerador = None
                h2_reagido_kg_s = None
            elif eh_padulles:
                corrente_gerador_A, evento_gerador = self._corrente_no_instante(instante, "gerador")
                saida_gerador = gerador.calcular_saida(corrente_gerador_A)
                potencia_gerador_total_W = saida_gerador["stack_power_W"] * cfg.quantidade_geradores
                consumo_h2_kg_s = (
                    saida_gerador["h2_tank_flow_kg_s"] * cfg.quantidade_geradores
                )
                referencia_gerador_kw = None
                tensao_gerador_stack_V = saida_gerador["stack_voltage_V"]
                nernst_gerador_stack_V = saida_gerador["nernst_voltage_stack_V"]
                queda_ativacao_gerador_V = saida_gerador["activation_voltage_drop_V"]
                queda_ohmica_gerador_V = saida_gerador["ohmic_voltage_drop_V"]
                estado_gerador_v_dle = None
                estado_gerador_p_kw = None
                pressao_h2_gerador_atm = saida_gerador["partial_pressure_h2_atm"]
                pressao_o2_gerador_atm = saida_gerador["partial_pressure_o2_atm"]
                utilizacao_h2_gerador = saida_gerador["h2_utilization"]
                h2_reagido_kg_s = saida_gerador["h2_reacted_kg_s"] * cfg.quantidade_geradores
            else:
                corrente_gerador_A, evento_gerador = self._corrente_no_instante(instante, "gerador")
                saida_gerador = gerador.calcular_saida(corrente_gerador_A)
                vazao_cons = calcular_vazao_h2_celula_combustivel(
                    cfg.gerador.n_series_cells,
                    corrente_gerador_A,
                    cfg.utilizacao_h2,
                    cfg.quantidade_geradores,
                )
                potencia_gerador_total_W = saida_gerador["stack_power_W"] * cfg.quantidade_geradores
                consumo_h2_kg_s = vazao_cons["vazao_h2_tanque_kg_s"]
                referencia_gerador_kw = None
                tensao_gerador_stack_V = saida_gerador["stack_voltage_V"]
                nernst_gerador_stack_V = None
                queda_ativacao_gerador_V = None
                queda_ohmica_gerador_V = None
                estado_gerador_v_dle = gerador.estado.V_dle_cell_V
                estado_gerador_p_kw = None
                pressao_h2_gerador_atm = None
                pressao_o2_gerador_atm = None
                utilizacao_h2_gerador = cfg.utilizacao_h2
                h2_reagido_kg_s = consumo_h2_kg_s
            serie.append(
                {
                    "tempo_s": round(instante, 9),
                    "corrente_eletrolisador_A": round(corrente_el, 9),
                    "corrente_gerador_A": (
                        round(corrente_gerador_A, 9) if corrente_gerador_A is not None else None
                    ),
                    "potencia_gerador_referencia_kw": (
                        round(referencia_gerador_kw, 9)
                        if referencia_gerador_kw is not None
                        else None
                    ),
                    "tipo_gerador_hidrogenio": (
                        "motor_reciprocante"
                        if eh_motor
                        else "pemfc_opem_padulles_i"
                        if eh_padulles
                        else "pemfc"
                    ),
                    "evento_eletrolisador": evento_el,
                    "evento_gerador": evento_gerador,
                    "massa_h2_tanque_kg": round(tanque.estado.massa_h2_kg, 12),
                    "producao_h2_kg_s": vazao_prod["vazao_h2_kg_s"],
                    "consumo_h2_kg_s": consumo_h2_kg_s,
                    "potencia_eletrolisador_stack_W": round(
                        saida_el["stack_power_W"] * cfg.quantidade_eletrolisadores, 9
                    ),
                    "potencia_gerador_W": round(potencia_gerador_total_W, 9),
                    "potencia_gerador_stack_W": round(potencia_gerador_total_W, 9),
                    "potencia_liquida_W": round(
                        potencia_gerador_total_W
                        - saida_el["stack_power_W"] * cfg.quantidade_eletrolisadores,
                        9,
                    ),
                    "potencia_liquida_stacks_W": round(
                        potencia_gerador_total_W
                        - saida_el["stack_power_W"] * cfg.quantidade_eletrolisadores,
                        9,
                    ),
                    "tensao_eletrolisador_stack_V": round(saida_el["stack_voltage_V"], 9),
                    "tensao_gerador_stack_V": (
                        round(tensao_gerador_stack_V, 9)
                        if tensao_gerador_stack_V is not None
                        else None
                    ),
                    "nernst_gerador_stack_V": (
                        round(nernst_gerador_stack_V, 9)
                        if nernst_gerador_stack_V is not None
                        else None
                    ),
                    "queda_ativacao_gerador_V": (
                        round(queda_ativacao_gerador_V, 9)
                        if queda_ativacao_gerador_V is not None
                        else None
                    ),
                    "queda_ohmica_gerador_V": (
                        round(queda_ohmica_gerador_V, 9)
                        if queda_ohmica_gerador_V is not None
                        else None
                    ),
                    "estado_eletrolisador_V_dle_cell_V": round(
                        eletrolisador.estado.V_dle_cell_V, 9
                    ),
                    "estado_gerador_V_dle_cell_V": (
                        round(estado_gerador_v_dle, 9)
                        if estado_gerador_v_dle is not None
                        else None
                    ),
                    "estado_gerador_potencia_kw": (
                        round(estado_gerador_p_kw, 9)
                        if estado_gerador_p_kw is not None
                        else None
                    ),
                    "pressao_h2_gerador_atm": (
                        round(pressao_h2_gerador_atm, 12)
                        if pressao_h2_gerador_atm is not None
                        else None
                    ),
                    "pressao_o2_gerador_atm": (
                        round(pressao_o2_gerador_atm, 12)
                        if pressao_o2_gerador_atm is not None
                        else None
                    ),
                    "utilizacao_h2_gerador": (
                        round(utilizacao_h2_gerador, 12)
                        if utilizacao_h2_gerador is not None
                        else None
                    ),
                    "h2_reagido_kg_s": h2_reagido_kg_s,
                }
            )
            if indice + 1 < len(tempo):
                dt = tempo[indice + 1] - instante
                tanque.passo(
                    dt,
                    vazao_prod["vazao_h2_kg_s"],
                    consumo_h2_kg_s,
                )
                eletrolisador.passo(dt, corrente_el)
                if eh_motor:
                    potencia_gerador_kw = gerador.passo(
                        potencia_gerador_kw, referencia_gerador_kw, dt
                    )
                elif eh_padulles:
                    gerador.passo(dt, corrente_gerador_A)
                else:
                    gerador.passo(dt, corrente_gerador_A)

        return {
            "tipo_analise": (
                "transitorio_ciclo_hidrogenio_motor"
                if eh_motor
                else "transitorio_ciclo_hidrogenio_pemfc_opem_padulles_i"
                if eh_padulles
                else "transitorio_ciclo_hidrogenio_pemfc"
            ),
            "fronteira": (
                "eletrolisador_cc_tanque_massa_motor_gerador_h2"
                if eh_motor
                else "eletrolisador_tanque_pressao_gases_pemfc_padulles_i"
                if eh_padulles
                else "eletrolisador_cc_tanque_massa_pemfc_cc"
            ),
            "configuracao": _jsonable(asdict(cfg)),
            "modelo_gerador_padulles_i": (
                {
                    "descricao": "H2/O2 partial pressures are first-order states; stack voltage follows Nernst minus B*ln(C*I) and Rint*I.",
                    "alimentacao_h2": "q_h2_kmol_s is continuously debited from the tank; reacted H2 and utilization are reported separately; purges/recirculation are not modeled.",
                }
                if eh_padulles
                else None
            ),
            "premissas": {
                "eletrolisador": "corrente positiva consome eletricidade e produz H₂ pela lei de Faraday",
                "gerador": (
                    "motor reciprocante: estado de potência com primeira ordem limitada por rampa; consumo de H₂ por eficiência líquida no PCI"
                    if eh_motor
                    else "PEMFC: corrente positiva entrega eletricidade e consome H₂ pela lei de Faraday"
                ),
                "armazenamento": "balanço de massa ideal; pressão, temperatura, compressão e perdas do tanque não modeladas",
                "interface_eletrica": (
                    "PEME e PEMFC reportam potência CC do stack; o motor reporta potência elétrica líquida; perdas de conversão, sincronismo e auxiliares fora do modelo"
                ),
                "eficiencia_faradaica": "parâmetro obrigatório do eletrolisador, a identificar por ensaio ou ficha técnica",
                "utilizacao_h2": (
                    "não usada no motor; consumo calculado pela eficiência elétrica líquida"
                    if eh_motor
                    else "parâmetro obrigatório da PEMFC; 1 representa consumo estequiométrico ideal"
                ),
                "integracao": "Euler explícito; passo até 1/5 da menor constante de tempo",
            },
            "resumo": _resumo(serie),
            "serie_temporal": serie,
        }

    def _linha_do_tempo(self) -> list[float]:
        cfg = self.configuracao
        n = int(math.floor(cfg.duracao_s / cfg.passo_s))
        pontos = {
            round(indice * cfg.passo_s, 12)
            for indice in range(n + 1)
            if indice * cfg.passo_s < cfg.duracao_s
        }
        pontos.add(cfg.duracao_s)
        for evento in cfg.eventos:
            if evento.inicio_s <= cfg.duracao_s:
                pontos.add(evento.inicio_s)
            if evento.fim_s is not None and evento.fim_s <= cfg.duracao_s:
                pontos.add(evento.fim_s)
        return sorted(pontos)

    def _corrente_no_instante(self, instante: float, componente: str) -> tuple[float, str | None]:
        corrente = (
            self.configuracao.corrente_eletrolisador_inicial_A
            if componente == "eletrolisador"
            else self.configuracao.corrente_gerador_inicial_A
        )
        ativo = None
        for evento in self.configuracao.eventos:
            if evento.componente == componente and evento.ativo(instante):
                corrente = evento.corrente_stack_A
                ativo = componente
        return corrente, ativo

    def _referencia_motor_no_instante(self, instante: float) -> tuple[float, str | None]:
        referencia = self.configuracao.potencia_gerador_referencia_kw
        ativo = None
        for evento in self.configuracao.eventos:
            if (
                evento.componente == "gerador"
                and evento.ativo(instante)
                and evento.potencia_referencia_kw is not None
            ):
                referencia = evento.potencia_referencia_kw
                ativo = "gerador"
        return referencia, ativo


def comparar_geradores_hidrogenio(
    entrada_pemfc: str | Path,
    entrada_motor: str | Path,
) -> dict[str, Any]:
    """Executa dois ciclos com PEMFC e motor usando a mesma base de produção.

    Os arquivos podem ter perfis de geração diferentes, mas devem compartilhar
    parâmetros, corrente e eventos do eletrolisador, tanque e passo/duração.
    """
    cfg_pemfc = ConfiguracaoTransitorioCicloHidrogenio.from_json(entrada_pemfc)
    cfg_motor = ConfiguracaoTransitorioCicloHidrogenio.from_json(entrada_motor)
    if not isinstance(
        cfg_pemfc.gerador,
        (ParametrosCelulaCombustivelPEM, ParametrosGeradorPEMFCOpem),
    ):
        raise ValueError("entrada_pemfc deve configurar um gerador PEMFC")
    if not isinstance(cfg_motor.gerador, ParametrosMotorHidrogenio):
        raise ValueError("entrada_motor deve configurar motor_hidrogenio_info")

    def base_comum(cfg: ConfiguracaoTransitorioCicloHidrogenio) -> tuple[Any, ...]:
        eventos_eletrolisador = tuple(
            evento for evento in cfg.eventos if evento.componente == "eletrolisador"
        )
        return (
            cfg.eletrolisador,
            cfg.tanque,
            cfg.eficiencia_faradaica,
            cfg.passo_s,
            cfg.duracao_s,
            cfg.corrente_eletrolisador_inicial_A,
            cfg.quantidade_eletrolisadores,
            cfg.estado_inicial_eletrolisador,
            eventos_eletrolisador,
        )

    if base_comum(cfg_pemfc) != base_comum(cfg_motor):
        raise ValueError(
            "Os cenários devem usar o mesmo PEME, tanque, perfil de corrente do PEME, "
            "passo e duração para comparar os geradores"
        )

    resultado_pemfc = TransitorioCicloHidrogenio(cfg_pemfc).executar()
    resultado_motor = TransitorioCicloHidrogenio(cfg_motor).executar()
    metricas = (
        "massa_h2_consumida_kg",
        "energia_gerador_kwh",
        "potencia_gerador_max_W",
        "massa_h2_final_kg",
    )
    diferencas = {
        chave: round(
            resultado_motor["resumo"][chave] - resultado_pemfc["resumo"][chave],
            12,
        )
        for chave in metricas
    }
    return {
        "tipo_analise": "comparacao_transitoria_geradores_hidrogenio",
        "premissas_comuns": (
            "PEME, tanque, perfil de produção, passo e duração idênticos; "
            "cada cenário conserva sua própria referência e dinâmica de geração"
        ),
        "limite_comparacao": (
            "potência PEMFC é medida no stack CC e potência do motor é elétrica líquida; "
            "comparar consumo de H2 e aplicar perdas de conversores/auxiliares antes de comparar potência AC"
        ),
        "diferenca_motor_menos_pemfc": diferencas,
        "pemfc": resultado_pemfc,
        "motor_hidrogenio": resultado_motor,
    }


def _parametros_eletrolisador(dados: dict[str, Any]) -> ParametrosEletrolisadorPEM:
    campos = {campo.name for campo in fields(ParametrosEletrolisadorPEM)}
    filtrados = {chave: valor for chave, valor in dados.items() if chave in campos}
    obrigatorios = (
        "V_rev_cell_V",
        "R_ohm_cell_Ohm",
        "R_act_cell_Ohm",
        "R_con_cell_Ohm",
        "n_series_cells",
    )
    if any(filtrados.get(chave) is None for chave in obrigatorios):
        raise ValueError("eletrolisador_pem_info deve conter os parâmetros elétricos por célula")
    for chave in (
        "V_rev_cell_V", "R_ohm_cell_Ohm", "R_act_cell_Ohm", "R_con_cell_Ohm",
        "C_dle_cell_F", "C_act_cell_F", "C_con_cell_F",
    ):
        if filtrados.get(chave) is not None:
            filtrados[chave] = _numero(filtrados[chave], chave)
    filtrados["n_series_cells"] = _inteiro(filtrados["n_series_cells"], "n_series_cells")
    filtrados["n_parallel_strings"] = _inteiro(
        filtrados.get("n_parallel_strings", 1), "n_parallel_strings"
    )
    filtrados["variant"] = str(filtrados.get("variant") or "combined_dle")
    return ParametrosEletrolisadorPEM(**filtrados)


def _parametros_gerador(dados: dict[str, Any]) -> ParametrosCelulaCombustivelPEM:
    campos = {campo.name for campo in fields(ParametrosCelulaCombustivelPEM)}
    filtrados = {chave: valor for chave, valor in dados.items() if chave in campos}
    obrigatorios = (
        "V_oc_cell_V", "R_ohm_cell_Ohm", "R_act_cell_Ohm", "R_con_cell_Ohm",
        "C_dle_cell_F", "n_series_cells",
    )
    if any(filtrados.get(chave) is None for chave in obrigatorios):
        raise ValueError("gerador_hidrogenio_info deve conter os parâmetros do stack PEMFC")
    for chave in (
        "V_oc_cell_V", "R_ohm_cell_Ohm", "R_act_cell_Ohm", "R_con_cell_Ohm", "C_dle_cell_F"
    ):
        filtrados[chave] = _numero(filtrados[chave], chave)
    filtrados["n_series_cells"] = _inteiro(filtrados["n_series_cells"], "n_series_cells")
    filtrados["n_parallel_strings"] = _inteiro(
        filtrados.get("n_parallel_strings", 1), "n_parallel_strings"
    )
    if "id_gerador" not in filtrados and dados.get("gerador_id"):
        filtrados["id_gerador"] = str(dados["gerador_id"])
    return ParametrosCelulaCombustivelPEM(**filtrados)


def _parametros_gerador_opem(dados: dict[str, Any]) -> ParametrosGeradorPEMFCOpem:
    aliases = {
        "n_series_cells": ("n_series_cells", "N0"),
        "E0_cell_V": ("E0_cell_V", "E0"),
        "temperatura_K": ("temperatura_K", "T"),
        "KH2_kmol_s_atm": ("KH2_kmol_s_atm", "KH2"),
        "KO2_kmol_s_atm": ("KO2_kmol_s_atm", "KO2"),
        "tau_h2_s": ("tau_h2_s", "tH2"),
        "tau_o2_s": ("tau_o2_s", "tO2"),
        "q_h2_kmol_s": ("q_h2_kmol_s", "qH2"),
        "rho_h2_o2": ("rho_h2_o2", "rho"),
        "B_ativacao_V": ("B_ativacao_V", "B"),
        "C_ativacao_A_inv": ("C_ativacao_A_inv", "C"),
        "R_interna_stack_Ohm": ("R_interna_stack_Ohm", "Rint"),
    }
    filtrados: dict[str, Any] = {}
    for campo, nomes in aliases.items():
        valor = next((dados[nome] for nome in nomes if dados.get(nome) is not None), None)
        if valor is None:
            raise ValueError(
                "gerador_hidrogenio_info no modelo OPEM Padulles-I deve informar "
                + ", ".join(nomes)
            )
        filtrados[campo] = (
            _inteiro(valor, campo)
            if campo == "n_series_cells"
            else _numero(valor, campo)
        )
    filtrados["id_gerador"] = str(
        dados.get("id_gerador") or dados.get("gerador_id") or "PEMFC_Padulles_I"
    )
    return ParametrosGeradorPEMFCOpem(**filtrados)


def _parametros_motor(dados: dict[str, Any]) -> ParametrosMotorHidrogenio:
    campos = {campo.name for campo in fields(ParametrosMotorHidrogenio)}
    filtrados = {chave: valor for chave, valor in dados.items() if chave in campos}
    for chave in (
        "potencia_nominal_kw",
        "eficiencia_eletrica_liquida",
        "constante_tempo_s",
        "rampa_max_kw_min",
        "fracao_carga_minima",
        "pci_h2_j_kg",
    ):
        if filtrados.get(chave) is not None:
            filtrados[chave] = _numero(filtrados[chave], chave)
    if "potencia_nominal_kw" not in filtrados or "eficiencia_eletrica_liquida" not in filtrados:
        raise ValueError(
            "motor_hidrogenio_info deve informar potencia_nominal_kw e eficiencia_eletrica_liquida"
        )
    return ParametrosMotorHidrogenio(**filtrados)


def _registro(documento: dict[str, Any], chave: str) -> dict[str, Any]:
    valor = documento.get(chave) or []
    if isinstance(valor, dict):
        return valor
    if not isinstance(valor, list):
        raise ValueError(f"{chave} deve ser um objeto ou lista de objetos")
    if not valor:
        return {}
    if not isinstance(valor[0], dict):
        raise ValueError(f"{chave}[0] deve ser um objeto")
    return valor[0]


def _estado(valor: Any) -> tuple[float, ...] | None:
    if valor is None:
        return None
    if not isinstance(valor, list):
        raise ValueError("estado inicial deve ser uma lista")
    return tuple(_numero(item, "estado_inicial") for item in valor)


def _inteiro(valor: Any, nome: str) -> int:
    numero = _numero(valor, nome)
    if numero < 1 or not numero.is_integer():
        raise ValueError(f"{nome} deve ser um inteiro positivo")
    return int(numero)


def _numero(valor: Any, nome: str) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{nome} deve ser numérico e finito") from exc
    if not math.isfinite(numero):
        raise ValueError(f"{nome} deve ser numérico e finito")
    return numero


def _opcional_numero(valor: Any, nome: str) -> float | None:
    return None if valor is None or valor == "" else _numero(valor, nome)


def _finito(valor: Any) -> bool:
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError, OverflowError):
        return False


def _jsonable(valor: Any) -> Any:
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, dict):
        return {chave: _jsonable(item) for chave, item in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_jsonable(item) for item in valor]
    return valor


def _resumo(serie: list[dict[str, Any]]) -> dict[str, Any]:
    massa = [item["massa_h2_tanque_kg"] for item in serie]
    p_gerador = [item["potencia_gerador_W"] for item in serie]
    p_eletrolisador = [item["potencia_eletrolisador_stack_W"] for item in serie]
    intervalos = [
        serie[indice + 1]["tempo_s"] - item["tempo_s"]
        for indice, item in enumerate(serie[:-1])
    ]
    massa_h2_produzida = sum(
        item["producao_h2_kg_s"] * dt for item, dt in zip(serie, intervalos)
    )
    massa_h2_consumida = sum(
        item["consumo_h2_kg_s"] * dt for item, dt in zip(serie, intervalos)
    )
    energia_gerador = sum(
        item["potencia_gerador_W"] * dt / 3.6e6
        for item, dt in zip(serie, intervalos)
    )
    energia_eletrolisador = sum(
        item["potencia_eletrolisador_stack_W"] * dt / 3.6e6
        for item, dt in zip(serie, intervalos)
    )
    resumo = {
        "amostras": len(serie),
        "duracao_s": serie[-1]["tempo_s"] if serie else 0.0,
        "massa_h2_inicial_kg": massa[0] if massa else None,
        "massa_h2_final_kg": massa[-1] if massa else None,
        "potencia_gerador_max_W": max(p_gerador, default=None),
        "potencia_eletrolisador_max_W": max(p_eletrolisador, default=None),
        "massa_h2_produzida_kg": round(massa_h2_produzida, 12),
        "massa_h2_consumida_kg": round(massa_h2_consumida, 12),
        "energia_gerador_kwh": round(energia_gerador, 9),
        "energia_eletrolisador_kwh": round(energia_eletrolisador, 9),
    }
    pressao_h2 = [
        item["pressao_h2_gerador_atm"]
        for item in serie
        if item["pressao_h2_gerador_atm"] is not None
    ]
    pressao_o2 = [
        item["pressao_o2_gerador_atm"]
        for item in serie
        if item["pressao_o2_gerador_atm"] is not None
    ]
    utilizacao = [
        item["utilizacao_h2_gerador"]
        for item in serie
        if item["utilizacao_h2_gerador"] is not None
    ]
    if pressao_h2:
        resumo.update({
            "pressao_h2_gerador_min_atm": round(min(pressao_h2), 9),
            "pressao_h2_gerador_max_atm": round(max(pressao_h2), 9),
            "pressao_o2_gerador_min_atm": round(min(pressao_o2), 9),
            "pressao_o2_gerador_max_atm": round(max(pressao_o2), 9),
            "utilizacao_h2_gerador_max": round(max(utilizacao), 9),
        })
    return resumo


__all__ = [
    "ConfiguracaoTransitorioCicloHidrogenio",
    "EventoCorrenteCicloHidrogenio",
    "TransitorioCicloHidrogenio",
    "comparar_geradores_hidrogenio",
]
