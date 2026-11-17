"""Equivalente elétrico estático e dinâmico para uma célula a combustível PEM."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ParametrosCelulaCombustivelPEM:
    """Parâmetros elétricos identificados por célula e configuração do stack."""

    V_oc_cell_V: float
    R_ohm_cell_Ohm: float
    R_act_cell_Ohm: float
    R_con_cell_Ohm: float
    C_dle_cell_F: float
    n_series_cells: int
    n_parallel_strings: int = 1
    id_gerador: str = "Celula_Combustivel_PEM_1"

    def __post_init__(self) -> None:
        for nome in (
            "V_oc_cell_V",
            "R_ohm_cell_Ohm",
            "R_act_cell_Ohm",
            "R_con_cell_Ohm",
            "C_dle_cell_F",
        ):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not _finito(valor):
                raise ValueError(f"{nome} deve ser finito")
        if self.V_oc_cell_V <= 0:
            raise ValueError("V_oc_cell_V deve ser positiva")
        if self.R_ohm_cell_Ohm < 0:
            raise ValueError("R_ohm_cell_Ohm não pode ser negativa")
        if self.R_act_cell_Ohm <= 0 or self.R_con_cell_Ohm <= 0:
            raise ValueError("R_act_cell_Ohm e R_con_cell_Ohm devem ser positivas")
        if self.C_dle_cell_F <= 0:
            raise ValueError("C_dle_cell_F deve ser positiva")
        for nome in ("n_series_cells", "n_parallel_strings"):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
                raise ValueError(f"{nome} deve ser um inteiro positivo")

    @property
    def constante_tempo_s(self) -> float:
        return (self.R_act_cell_Ohm + self.R_con_cell_Ohm) * self.C_dle_cell_F


@dataclass
class EstadoCelulaCombustivelPEM:
    """Sobretensão de ativação/concentração agrupada, em V por célula."""

    V_dle_cell_V: float = 0.0


class CelulaCombustivelPEM:
    """Modelo PEMFC EEC de um estado para estudos de sistema elétrico.

    A corrente positiva é fornecida pela célula ao circuito. O estado RC é
    uma queda de polarização, portanto reduz a tensão terminal do stack.
    Temperatura, pressões dos reagentes, compressor, purga e inversor ficam
    fora desta fronteira reduzida.
    """

    def __init__(self, parametros: ParametrosCelulaCombustivelPEM):
        self.parametros = parametros
        self.estado = EstadoCelulaCombustivelPEM()
        self.historico: list[EstadoCelulaCombustivelPEM] = []

    def inicializar(
        self,
        corrente_stack_A: float = 0.0,
        estado_inicial: Sequence[float] | None = None,
    ) -> EstadoCelulaCombustivelPEM:
        corrente = _corrente_geracao(corrente_stack_A)
        if estado_inicial is None:
            corrente_celula = corrente / self.parametros.n_parallel_strings
            queda = (
                self.parametros.R_act_cell_Ohm + self.parametros.R_con_cell_Ohm
            ) * corrente_celula
            self.estado = EstadoCelulaCombustivelPEM(V_dle_cell_V=queda)
        else:
            valores = tuple(float(valor) for valor in estado_inicial)
            if len(valores) != 1 or not _finito(valores[0]):
                raise ValueError("estado_inicial deve conter uma queda de polarização finita")
            self.estado = EstadoCelulaCombustivelPEM(V_dle_cell_V=valores[0])
        self.historico = []
        return self.estado

    def calcular_saida(
        self,
        corrente_stack_A: float,
        estado: EstadoCelulaCombustivelPEM | None = None,
    ) -> dict[str, Any]:
        corrente = _corrente_geracao(corrente_stack_A)
        estado_atual = estado or self.estado
        corrente_celula = corrente / self.parametros.n_parallel_strings
        queda_ohmica = self.parametros.R_ohm_cell_Ohm * corrente_celula
        queda_polarizacao = float(estado_atual.V_dle_cell_V)
        tensao_celula = (
            self.parametros.V_oc_cell_V - queda_ohmica - queda_polarizacao
        )
        if tensao_celula <= 0:
            raise ValueError(
                "corrente/estado fora da faixa elétrica: tensão de célula PEMFC não positiva"
            )
        tensao_stack = self.parametros.n_series_cells * tensao_celula
        return {
            "current_stack_A": corrente,
            "current_per_string_A": corrente_celula,
            "open_circuit_voltage_cell_V": self.parametros.V_oc_cell_V,
            "ohmic_voltage_drop_cell_V": queda_ohmica,
            "polarization_voltage_drop_cell_V": queda_polarizacao,
            "cell_voltage_V": tensao_celula,
            "stack_voltage_V": tensao_stack,
            "stack_power_W": tensao_stack * corrente,
        }

    def ponto_operacao_estacionario(self, corrente_stack_A: float) -> dict[str, Any]:
        return calcular_ponto_operacao_estacionario(self.parametros, corrente_stack_A)

    def equacoes_diferenciais(self, corrente_stack_A: float) -> dict[str, float]:
        corrente = _corrente_geracao(corrente_stack_A)
        corrente_celula = corrente / self.parametros.n_parallel_strings
        resistencia_polarizacao = (
            self.parametros.R_act_cell_Ohm + self.parametros.R_con_cell_Ohm
        )
        return {
            "d_V_dle_cell_V_dt": (
                corrente_celula - self.estado.V_dle_cell_V / resistencia_polarizacao
            )
            / self.parametros.C_dle_cell_F
        }

    def passo(self, passo_s: float, corrente_stack_A: float) -> EstadoCelulaCombustivelPEM:
        dt = _numero_finito(passo_s, "passo_s")
        if dt <= 0:
            raise ValueError("passo_s deve ser positivo")
        derivada = self.equacoes_diferenciais(corrente_stack_A)["d_V_dle_cell_V_dt"]
        self.estado.V_dle_cell_V += dt * derivada
        self.historico.append(EstadoCelulaCombustivelPEM(**asdict(self.estado)))
        return self.estado

    def exportar_estado(self) -> dict[str, Any]:
        return {
            "parametros": asdict(self.parametros),
            "estado": asdict(self.estado),
            "historico": [asdict(item) for item in self.historico],
        }


def calcular_ponto_operacao_estacionario(
    parametros: ParametrosCelulaCombustivelPEM,
    corrente_stack_A: float,
) -> dict[str, Any]:
    """Calcula a tensão terminal de geração em equilíbrio do estado RC."""

    corrente = _corrente_geracao(corrente_stack_A)
    corrente_celula = corrente / parametros.n_parallel_strings
    queda_polarizacao = (
        parametros.R_act_cell_Ohm + parametros.R_con_cell_Ohm
    ) * corrente_celula
    queda_ohmica = parametros.R_ohm_cell_Ohm * corrente_celula
    tensao_celula = parametros.V_oc_cell_V - queda_ohmica - queda_polarizacao
    if tensao_celula <= 0:
        raise ValueError("corrente fora da faixa: tensão de célula PEMFC não positiva")
    tensao_stack = parametros.n_series_cells * tensao_celula
    return {
        "current_stack_A": corrente,
        "current_per_string_A": corrente_celula,
        "open_circuit_voltage_cell_V": parametros.V_oc_cell_V,
        "ohmic_voltage_drop_cell_V": queda_ohmica,
        "polarization_voltage_drop_cell_V": queda_polarizacao,
        "cell_voltage_V": tensao_celula,
        "stack_voltage_V": tensao_stack,
        "stack_power_W": tensao_stack * corrente,
    }


def _corrente_geracao(valor: float) -> float:
    corrente = _numero_finito(valor, "corrente_stack_A")
    if corrente < 0:
        raise ValueError("corrente_stack_A deve ser não negativa no modo de geração")
    return corrente


def _numero_finito(valor: Any, nome: str) -> float:
    if isinstance(valor, bool):
        raise ValueError(f"{nome} deve ser numérico e finito")
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
    "CelulaCombustivelPEM",
    "EstadoCelulaCombustivelPEM",
    "ParametrosCelulaCombustivelPEM",
    "calcular_ponto_operacao_estacionario",
]
