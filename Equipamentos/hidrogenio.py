"""Balanço reduzido de hidrogênio para stacks PEM e tanque de massa."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


FARADAY_C_MOL = 96485.33212
MASSA_MOLAR_H2_KG_MOL = 2.01588e-3


def calcular_vazao_h2_eletrolisador(
    n_series_cells: int,
    corrente_stack_A: float,
    eficiencia_faradaica: float,
    quantidade: int = 1,
) -> dict[str, float]:
    """Calcula a produção de H₂ pela lei de Faraday.

    A eficiência faradaica deve vir de ensaio ou ficha técnica. Correntes de
    strings paralelas já são somadas em ``corrente_stack_A``; por isso o
    número de strings paralelas não altera a forma reduzida ``N_s * I_stack``.
    """

    _validar_inteiro(n_series_cells, "n_series_cells")
    _validar_inteiro(quantidade, "quantidade")
    corrente = _numero_finito(corrente_stack_A, "corrente_stack_A")
    eficiencia = _numero_finito(eficiencia_faradaica, "eficiencia_faradaica")
    if corrente < 0:
        raise ValueError("corrente_stack_A deve ser não negativa no modo de produção")
    if not 0 < eficiencia <= 1:
        raise ValueError("eficiencia_faradaica deve estar no intervalo (0, 1]")

    mol_s = (
        n_series_cells
        * corrente
        * eficiencia
        * quantidade
        / (2.0 * FARADAY_C_MOL)
    )
    kg_s = mol_s * MASSA_MOLAR_H2_KG_MOL
    return {
        "vazao_molar_h2_mol_s": mol_s,
        "vazao_h2_kg_s": kg_s,
        "vazao_h2_kg_h": kg_s * 3600.0,
    }


def calcular_vazao_h2_celula_combustivel(
    n_series_cells: int,
    corrente_stack_A: float,
    utilizacao_h2: float = 1.0,
    quantidade: int = 1,
) -> dict[str, float]:
    """Calcula consumo de H₂ por Faraday, incluindo H₂ não utilizado.

    ``utilizacao_h2=1`` é o limite estequiométrico ideal; purgas e perdas só
    entram quando se informa a utilização medida do sistema.
    """

    _validar_inteiro(n_series_cells, "n_series_cells")
    _validar_inteiro(quantidade, "quantidade")
    corrente = _numero_finito(corrente_stack_A, "corrente_stack_A")
    utilizacao = _numero_finito(utilizacao_h2, "utilizacao_h2")
    if corrente < 0:
        raise ValueError("corrente_stack_A deve ser não negativa no modo de geração")
    if not 0 < utilizacao <= 1:
        raise ValueError("utilizacao_h2 deve estar no intervalo (0, 1]")

    mol_s_reagidos = n_series_cells * corrente * quantidade / (2.0 * FARADAY_C_MOL)
    mol_s_alimentados = mol_s_reagidos / utilizacao
    kg_s_reagidos = mol_s_reagidos * MASSA_MOLAR_H2_KG_MOL
    kg_s_alimentados = mol_s_alimentados * MASSA_MOLAR_H2_KG_MOL
    return {
        "vazao_h2_reagido_kg_s": kg_s_reagidos,
        "vazao_h2_reagido_kg_h": kg_s_reagidos * 3600.0,
        "vazao_h2_tanque_kg_s": kg_s_alimentados,
        "vazao_h2_tanque_kg_h": kg_s_alimentados * 3600.0,
    }


@dataclass(frozen=True)
class ParametrosTanqueHidrogenio:
    """Capacidade e massa inicial; não calcula pressão nem temperatura."""

    capacidade_kg: float
    massa_inicial_kg: float

    def __post_init__(self) -> None:
        capacidade = _numero_finito(self.capacidade_kg, "capacidade_kg")
        massa = _numero_finito(self.massa_inicial_kg, "massa_inicial_kg")
        if capacidade <= 0:
            raise ValueError("capacidade_kg deve ser positiva")
        if not 0 <= massa <= capacidade:
            raise ValueError("massa_inicial_kg deve estar entre zero e capacidade_kg")


@dataclass
class EstadoTanqueHidrogenio:
    massa_h2_kg: float


class TanqueHidrogenio:
    """Inventário de massa de H₂ com balanço discreto e limites rígidos."""

    def __init__(self, parametros: ParametrosTanqueHidrogenio):
        self.parametros = parametros
        self.estado = EstadoTanqueHidrogenio(parametros.massa_inicial_kg)

    def passo(
        self,
        passo_s: float,
        producao_kg_s: float,
        consumo_kg_s: float,
    ) -> EstadoTanqueHidrogenio:
        dt = _numero_finito(passo_s, "passo_s")
        producao = _numero_finito(producao_kg_s, "producao_kg_s")
        consumo = _numero_finito(consumo_kg_s, "consumo_kg_s")
        if dt <= 0 or producao < 0 or consumo < 0:
            raise ValueError("passo_s deve ser positivo; vazões não podem ser negativas")
        massa = self.estado.massa_h2_kg + (producao - consumo) * dt
        capacidade = self.parametros.capacidade_kg
        tolerancia = max(capacidade, 1.0) * 1e-12
        if massa < -tolerancia:
            raise ValueError(
                f"estoque de H₂ insuficiente: balanço resultaria em {massa:.9g} kg"
            )
        if massa > capacidade + tolerancia:
            raise ValueError(
                f"capacidade do tanque excedida: balanço resultaria em {massa:.9g} kg"
            )
        self.estado.massa_h2_kg = min(max(massa, 0.0), capacidade)
        return self.estado


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


def _validar_inteiro(valor: Any, nome: str) -> None:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise ValueError(f"{nome} deve ser um inteiro positivo")


__all__ = [
    "FARADAY_C_MOL",
    "MASSA_MOLAR_H2_KG_MOL",
    "EstadoTanqueHidrogenio",
    "ParametrosTanqueHidrogenio",
    "TanqueHidrogenio",
    "calcular_vazao_h2_celula_combustivel",
    "calcular_vazao_h2_eletrolisador",
]
