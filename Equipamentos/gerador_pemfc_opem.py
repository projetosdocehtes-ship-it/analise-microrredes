"""Modelo transitório PEMFC baseado no modelo de pressões Padullès-I do OPEM.

O modelo integra os estados de pressão parcial de H2 e O2 no domínio do tempo,
e calcula a tensão terminal com a equação de Nernst e perdas de ativação e
ohmicas. Os parâmetros de gás são identificados para o stack estudado.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any
from collections.abc import Sequence

from .hidrogenio import MASSA_MOLAR_H2_KG_MOL


FARADAY_C_KMOL = 96_485_332.12
CONSTANTE_GAS_J_KMOL_K = 8_314.462618


@dataclass(frozen=True)
class ParametrosGeradorPEMFCOpem:
    """Parâmetros Padullès-I no formato de unidades do OPEM.

    q_h2_kmol_s é o fluxo de H2 alimentado pelo tanque. O fluxo de O2 é
    calculado como q_H2 / rho_h2_o2. B_ativacao_V, C_ativacao_A_inv e
    R_interna_stack_Ohm são parâmetros do stack usados na equação de tensão.
    """

    n_series_cells: int
    E0_cell_V: float
    temperatura_K: float
    KH2_kmol_s_atm: float
    KO2_kmol_s_atm: float
    tau_h2_s: float
    tau_o2_s: float
    q_h2_kmol_s: float
    rho_h2_o2: float
    B_ativacao_V: float
    C_ativacao_A_inv: float
    R_interna_stack_Ohm: float
    id_gerador: str = "PEMFC_Padulles_I"

    def __post_init__(self) -> None:
        if isinstance(self.n_series_cells, bool) or not isinstance(self.n_series_cells, int) or self.n_series_cells < 1:
            raise ValueError("n_series_cells deve ser um inteiro positivo")
        for nome in (
            "E0_cell_V",
            "temperatura_K",
            "KH2_kmol_s_atm",
            "KO2_kmol_s_atm",
            "tau_h2_s",
            "tau_o2_s",
            "q_h2_kmol_s",
            "rho_h2_o2",
            "B_ativacao_V",
            "C_ativacao_A_inv",
            "R_interna_stack_Ohm",
        ):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not _finito(valor):
                raise ValueError(f"{nome} deve ser numérico e finito")
        for nome in (
            "E0_cell_V",
            "temperatura_K",
            "KH2_kmol_s_atm",
            "KO2_kmol_s_atm",
            "tau_h2_s",
            "tau_o2_s",
            "q_h2_kmol_s",
            "rho_h2_o2",
            "B_ativacao_V",
            "C_ativacao_A_inv",
        ):
            if getattr(self, nome) <= 0:
                raise ValueError(f"{nome} deve ser positivo")
        if self.R_interna_stack_Ohm < 0:
            raise ValueError("R_interna_stack_Ohm não pode ser negativa")

    @property
    def q_o2_kmol_s(self) -> float:
        return self.q_h2_kmol_s / self.rho_h2_o2

    @property
    def menor_constante_tempo_s(self) -> float:
        return min(self.tau_h2_s, self.tau_o2_s)


@dataclass
class EstadoGeradorPEMFCOpem:
    pressao_h2_atm: float
    pressao_o2_atm: float


class GeradorPEMFCOpem:
    """PEMFC dinâmico com estados gasosos Padullès-I e saída elétrica OPEM."""

    def __init__(self, parametros: ParametrosGeradorPEMFCOpem):
        self.parametros = parametros
        self.estado = EstadoGeradorPEMFCOpem(1.0, 1.0)
        self.historico: list[EstadoGeradorPEMFCOpem] = []

    def inicializar(
        self,
        corrente_stack_A: float = 0.0,
        estado_inicial: Sequence[float] | None = None,
    ) -> EstadoGeradorPEMFCOpem:
        corrente = _corrente(corrente_stack_A)
        if estado_inicial is None:
            p_h2, p_o2 = self._pressao_equilibrio(corrente)
        else:
            valores = tuple(float(valor) for valor in estado_inicial)
            if len(valores) != 2 or not all(_finito(valor) and valor > 0 for valor in valores):
                raise ValueError("estado_inicial deve conter pressões H2 e O2 positivas, em atm")
            p_h2, p_o2 = valores
        self.estado = EstadoGeradorPEMFCOpem(p_h2, p_o2)
        self.historico = []
        return self.estado

    def calcular_saida(
        self,
        corrente_stack_A: float,
        estado: EstadoGeradorPEMFCOpem | None = None,
    ) -> dict[str, float]:
        corrente = _corrente(corrente_stack_A)
        atual = estado or self.estado
        p = self.parametros
        if atual.pressao_h2_atm <= 0 or atual.pressao_o2_atm <= 0:
            raise ValueError("pressões parciais de H2 e O2 devem permanecer positivas")

        e_nernst_cell = p.E0_cell_V + (
            CONSTANTE_GAS_J_KMOL_K * p.temperatura_K / (2.0 * FARADAY_C_KMOL)
        ) * math.log(atual.pressao_h2_atm * math.sqrt(atual.pressao_o2_atm))
        e_nernst_stack = p.n_series_cells * e_nernst_cell
        queda_ativacao = (
            p.B_ativacao_V * math.log(p.C_ativacao_A_inv * corrente)
            if corrente > 0
            else 0.0
        )
        queda_ohmica = p.R_interna_stack_Ohm * corrente
        tensao_stack = e_nernst_stack - queda_ativacao - queda_ohmica
        if tensao_stack <= 0:
            raise ValueError(
                "corrente/parâmetros fora da faixa: tensão terminal PEMFC não positiva"
            )

        h2_reagido_kmol_s = self._consumo_h2_reagido_kmol_s(corrente)
        o2_reagido_kmol_s = self._consumo_o2_reagido_kmol_s(corrente)
        fluxo_h2_reagido_kg_s = h2_reagido_kmol_s * 1000.0 * MASSA_MOLAR_H2_KG_MOL
        fluxo_h2_tanque_kg_s = p.q_h2_kmol_s * 1000.0 * MASSA_MOLAR_H2_KG_MOL
        return {
            "current_stack_A": corrente,
            "stack_voltage_V": tensao_stack,
            "stack_power_W": tensao_stack * corrente,
            "nernst_voltage_stack_V": e_nernst_stack,
            "activation_voltage_drop_V": queda_ativacao,
            "ohmic_voltage_drop_V": queda_ohmica,
            "partial_pressure_h2_atm": atual.pressao_h2_atm,
            "partial_pressure_o2_atm": atual.pressao_o2_atm,
            "h2_feed_kmol_s": p.q_h2_kmol_s,
            "o2_feed_kmol_s": p.q_o2_kmol_s,
            "h2_reacted_kmol_s": h2_reagido_kmol_s,
            "o2_reacted_kmol_s": o2_reagido_kmol_s,
            "h2_reacted_kg_s": fluxo_h2_reagido_kg_s,
            "h2_tank_flow_kg_s": fluxo_h2_tanque_kg_s,
            "h2_utilization": (
                h2_reagido_kmol_s / p.q_h2_kmol_s if p.q_h2_kmol_s > 0 else 0.0
            ),
        }

    def equacoes_diferenciais(self, corrente_stack_A: float) -> dict[str, float]:
        corrente = _corrente(corrente_stack_A)
        p_h2_equilibrio, p_o2_equilibrio = self._pressao_equilibrio(corrente)
        return {
            "d_pressao_h2_atm_dt": (
                p_h2_equilibrio - self.estado.pressao_h2_atm
            ) / self.parametros.tau_h2_s,
            "d_pressao_o2_atm_dt": (
                p_o2_equilibrio - self.estado.pressao_o2_atm
            ) / self.parametros.tau_o2_s,
        }

    def passo(self, passo_s: float, corrente_stack_A: float) -> EstadoGeradorPEMFCOpem:
        dt = _numero_finito(passo_s, "passo_s")
        if dt <= 0:
            raise ValueError("passo_s deve ser positivo")
        if dt > self.parametros.menor_constante_tempo_s / 5.0:
            raise ValueError("passo_s deve ser no máximo 1/5 da menor constante de tempo")
        derivadas = self.equacoes_diferenciais(corrente_stack_A)
        proximo_h2 = self.estado.pressao_h2_atm + dt * derivadas["d_pressao_h2_atm_dt"]
        proximo_o2 = self.estado.pressao_o2_atm + dt * derivadas["d_pressao_o2_atm_dt"]
        if proximo_h2 <= 0 or proximo_o2 <= 0:
            raise ValueError(
                "vazão de alimentação insuficiente: a pressão parcial calculada ficou não positiva"
            )
        self.estado = EstadoGeradorPEMFCOpem(proximo_h2, proximo_o2)
        self.historico.append(EstadoGeradorPEMFCOpem(**asdict(self.estado)))
        return self.estado

    def exportar_estado(self) -> dict[str, Any]:
        return {
            "parametros": asdict(self.parametros),
            "estado": asdict(self.estado),
            "historico": [asdict(item) for item in self.historico],
        }

    def _pressao_equilibrio(self, corrente_stack_A: float) -> tuple[float, float]:
        p = self.parametros
        h2_consumido = self._consumo_h2_reagido_kmol_s(corrente_stack_A)
        o2_consumido = self._consumo_o2_reagido_kmol_s(corrente_stack_A)
        p_h2 = (p.q_h2_kmol_s - h2_consumido) / p.KH2_kmol_s_atm
        p_o2 = (p.q_o2_kmol_s - o2_consumido) / p.KO2_kmol_s_atm
        if p_h2 <= 0 or p_o2 <= 0:
            raise ValueError(
                "vazão de alimentação OPEM insuficiente para corrente: aumente q_h2_kmol_s "
                "ou reduza a corrente"
            )
        return p_h2, p_o2

    def _consumo_h2_reagido_kmol_s(self, corrente_stack_A: float) -> float:
        return self.parametros.n_series_cells * corrente_stack_A / (2.0 * FARADAY_C_KMOL)

    def _consumo_o2_reagido_kmol_s(self, corrente_stack_A: float) -> float:
        return self.parametros.n_series_cells * corrente_stack_A / (4.0 * FARADAY_C_KMOL)


def _corrente(valor: Any) -> float:
    corrente = _numero_finito(valor, "corrente_stack_A")
    if corrente < 0:
        raise ValueError("corrente_stack_A deve ser não negativa no modo de geração")
    return corrente


def _numero_finito(valor: Any, nome: str) -> float:
    if isinstance(valor, bool):
        raise ValueError(f"{nome} deve ser numérico e finito")  # noqa: TRY004
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{nome} deve ser numérico e finito") from exc
    if not math.isfinite(numero):
        raise ValueError(f"{nome} deve ser numérico e finito")
    return numero


def _finito(valor: Any) -> bool:
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError, OverflowError):
        return False


__all__ = [
    "EstadoGeradorPEMFCOpem",
    "GeradorPEMFCOpem",
    "ParametrosGeradorPEMFCOpem",
]
