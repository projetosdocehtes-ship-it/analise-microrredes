"""Modelo elétrico de uma porta para um eletrolisador PEM."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ParametrosEletrolisadorPEM:
    """Parâmetros elétricos por célula e configuração do stack.

    As capacitâncias são opcionais para o cálculo estático. A variante
    dinâmica selecionada valida e exige as capacitâncias correspondentes.
    """

    V_rev_cell_V: float
    R_ohm_cell_Ohm: float
    R_act_cell_Ohm: float
    R_con_cell_Ohm: float
    n_series_cells: int
    C_dle_cell_F: float | None = None
    C_act_cell_F: float | None = None
    C_con_cell_F: float | None = None
    n_parallel_strings: int = 1
    variant: str = "combined_dle"
    id_eletrolisador: str = "Eletrolisador_PEM_1"

    def __post_init__(self) -> None:
        valores = {
            "V_rev_cell_V": self.V_rev_cell_V,
            "R_ohm_cell_Ohm": self.R_ohm_cell_Ohm,
            "R_act_cell_Ohm": self.R_act_cell_Ohm,
            "R_con_cell_Ohm": self.R_con_cell_Ohm,
        }
        for nome, valor in valores.items():
            if not _finito(valor):
                raise ValueError(f"{nome} deve ser finito")
        if self.V_rev_cell_V <= 0:
            raise ValueError("V_rev_cell_V deve ser positivo")
        if self.R_ohm_cell_Ohm < 0:
            raise ValueError("R_ohm_cell_Ohm não pode ser negativo")
        if self.R_act_cell_Ohm <= 0 or self.R_con_cell_Ohm <= 0:
            raise ValueError("R_act_cell_Ohm e R_con_cell_Ohm devem ser positivos")
        for nome in ("n_series_cells", "n_parallel_strings"):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
                raise ValueError(f"{nome} deve ser um inteiro positivo")
        if self.variant not in {"combined_dle", "separate_rc"}:
            raise ValueError("variant deve ser combined_dle ou separate_rc")
        for nome in ("C_dle_cell_F", "C_act_cell_F", "C_con_cell_F"):
            valor = getattr(self, nome)
            if valor is not None and (not _finito(valor) or valor <= 0):
                raise ValueError(f"{nome} deve ser positivo quando informado")

    def validar_dinamica(self) -> None:
        if self.variant == "combined_dle" and self.C_dle_cell_F is None:
            raise ValueError("combined_dle requer C_dle_cell_F positivo")
        if self.variant == "separate_rc":
            if self.C_act_cell_F is None or self.C_con_cell_F is None:
                raise ValueError("separate_rc requer C_act_cell_F e C_con_cell_F positivos")

    @property
    def constantes_tempo_s(self) -> tuple[float, ...]:
        self.validar_dinamica()
        if self.variant == "combined_dle":
            return ((self.R_act_cell_Ohm + self.R_con_cell_Ohm) * self.C_dle_cell_F,)
        return (
            self.R_act_cell_Ohm * self.C_act_cell_F,
            self.R_con_cell_Ohm * self.C_con_cell_F,
        )


@dataclass
class EstadoEletrolisadorPEM:
    """Quedas de polarização de cada célula, em volts."""

    V_dle_cell_V: float = 0.0
    V_act_cell_V: float = 0.0
    V_con_cell_V: float = 0.0


class EletrolisadorPEM:
    """EEC PEM de um estado (EEC 10) ou dois estados (EEC 9).

    A corrente do stack é uma entrada externa. ``equacoes_diferenciais``
    retorna as derivadas sem alterar o estado; ``passo`` oferece Euler
    explícito para simulações de passo fixo, como nos outros equipamentos.
    """

    def __init__(self, parametros: ParametrosEletrolisadorPEM):
        parametros.validar_dinamica()
        self.parametros = parametros
        self.estado = EstadoEletrolisadorPEM()
        self.historico: list[EstadoEletrolisadorPEM] = []

    def inicializar(
        self,
        i_stack_A: float = 0.0,
        estado_inicial: Sequence[float] | None = None,
    ) -> EstadoEletrolisadorPEM:
        """Inicializa em equilíbrio para a corrente ou em estados explícitos."""

        ponto = calcular_ponto_operacao_estacionario(self.parametros, i_stack_A)
        if estado_inicial is None:
            self.estado = EstadoEletrolisadorPEM(
                V_dle_cell_V=ponto["dle_voltage_cell_V"],
                V_act_cell_V=ponto["activation_voltage_cell_V"],
                V_con_cell_V=ponto["concentration_voltage_cell_V"],
            )
        else:
            valores = tuple(float(valor) for valor in estado_inicial)
            esperado = 1 if self.parametros.variant == "combined_dle" else 2
            if len(valores) != esperado or not all(_finito(valor) for valor in valores):
                raise ValueError(f"estado_inicial deve conter {esperado} valor(es) finito(s)")
            if esperado == 1:
                self.estado = EstadoEletrolisadorPEM(V_dle_cell_V=valores[0])
            else:
                self.estado = EstadoEletrolisadorPEM(
                    V_act_cell_V=valores[0], V_con_cell_V=valores[1]
                )
        self.historico = []
        return self.estado

    def calcular_saida(
        self,
        i_stack_A: float,
        estado: EstadoEletrolisadorPEM | None = None,
    ) -> dict[str, Any]:
        corrente = _corrente_finita(i_stack_A)
        estado_atual = estado or self.estado
        if self.parametros.variant == "combined_dle":
            v_dle = float(estado_atual.V_dle_cell_V)
            v_act = 0.0
            v_con = 0.0
        else:
            v_dle = 0.0
            v_act = float(estado_atual.V_act_cell_V)
            v_con = float(estado_atual.V_con_cell_V)
        return _calcular_saida(
            self.parametros,
            corrente,
            v_dle_cell_V=v_dle,
            v_act_cell_V=v_act,
            v_con_cell_V=v_con,
        )

    def ponto_operacao_estacionario(self, i_stack_A: float) -> dict[str, Any]:
        return calcular_ponto_operacao_estacionario(self.parametros, i_stack_A)

    def equacoes_diferenciais(self, i_stack_A: float) -> dict[str, float]:
        """Retorna as derivadas do modelo sem atualizar o estado interno."""

        corrente_celula = _corrente_finita(i_stack_A) / self.parametros.n_parallel_strings
        p = self.parametros
        if p.variant == "combined_dle":
            resistencia_dle = p.R_act_cell_Ohm + p.R_con_cell_Ohm
            derivada = (
                corrente_celula - self.estado.V_dle_cell_V / resistencia_dle
            ) / p.C_dle_cell_F
            return {"d_V_dle_cell_V_dt": derivada}
        return {
            "d_V_act_cell_V_dt": (
                corrente_celula - self.estado.V_act_cell_V / p.R_act_cell_Ohm
            ) / p.C_act_cell_F,
            "d_V_con_cell_V_dt": (
                corrente_celula - self.estado.V_con_cell_V / p.R_con_cell_Ohm
            ) / p.C_con_cell_F,
        }

    def passo(self, passo_s: float, i_stack_A: float) -> EstadoEletrolisadorPEM:
        """Integra um passo explícito de Euler e armazena o estado atualizado."""

        if not _finito(passo_s) or passo_s <= 0:
            raise ValueError("passo_s deve ser positivo e finito")
        derivadas = self.equacoes_diferenciais(i_stack_A)
        if self.parametros.variant == "combined_dle":
            self.estado.V_dle_cell_V += passo_s * derivadas["d_V_dle_cell_V_dt"]
        else:
            self.estado.V_act_cell_V += passo_s * derivadas["d_V_act_cell_V_dt"]
            self.estado.V_con_cell_V += passo_s * derivadas["d_V_con_cell_V_dt"]
        self.historico.append(EstadoEletrolisadorPEM(**asdict(self.estado)))
        return self.estado

    def exportar_estado(self) -> dict[str, Any]:
        return {
            "parametros": asdict(self.parametros),
            "estado": asdict(self.estado),
            "historico": [asdict(item) for item in self.historico],
        }


def calcular_ponto_operacao_estacionario(
    parametros: ParametrosEletrolisadorPEM,
    i_stack_A: float,
) -> dict[str, Any]:
    """Calcula o equilíbrio algébrico sem exigir capacitâncias dinâmicas."""

    corrente = _corrente_finita(i_stack_A)
    corrente_celula = corrente / parametros.n_parallel_strings
    if parametros.variant == "combined_dle":
        v_dle = (parametros.R_act_cell_Ohm + parametros.R_con_cell_Ohm) * corrente_celula
        v_act = v_con = 0.0
    else:
        v_dle = 0.0
        v_act = parametros.R_act_cell_Ohm * corrente_celula
        v_con = parametros.R_con_cell_Ohm * corrente_celula
    return _calcular_saida(
        parametros,
        corrente,
        v_dle_cell_V=v_dle,
        v_act_cell_V=v_act,
        v_con_cell_V=v_con,
    )


def _calcular_saida(
    parametros: ParametrosEletrolisadorPEM,
    i_stack_A: float,
    *,
    v_dle_cell_V: float,
    v_act_cell_V: float,
    v_con_cell_V: float,
) -> dict[str, Any]:
    corrente_celula = i_stack_A / parametros.n_parallel_strings
    v_ohmic = parametros.R_ohm_cell_Ohm * corrente_celula
    v_polarizacao = v_dle_cell_V + v_act_cell_V + v_con_cell_V
    v_celula = parametros.V_rev_cell_V + v_ohmic + v_polarizacao
    v_stack = parametros.n_series_cells * v_celula
    return {
        "variant": parametros.variant,
        "current_stack_A": i_stack_A,
        "current_per_string_A": corrente_celula,
        "reversible_voltage_cell_V": parametros.V_rev_cell_V,
        "ohmic_voltage_cell_V": v_ohmic,
        "dle_voltage_cell_V": v_dle_cell_V,
        "activation_voltage_cell_V": v_act_cell_V,
        "concentration_voltage_cell_V": v_con_cell_V,
        "polarization_voltage_cell_V": v_polarizacao,
        "cell_voltage_V": v_celula,
        "stack_voltage_V": v_stack,
        "stack_power_W": v_stack * i_stack_A,
    }


def _corrente_finita(valor: float) -> float:
    if isinstance(valor, bool) or not _finito(valor):
        raise ValueError("i_stack_A deve ser um escalar finito")
    return float(valor)


def _finito(valor: Any) -> bool:
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError, OverflowError):
        return False


__all__ = [
    "EletrolisadorPEM",
    "EstadoEletrolisadorPEM",
    "ParametrosEletrolisadorPEM",
    "calcular_ponto_operacao_estacionario",
]
