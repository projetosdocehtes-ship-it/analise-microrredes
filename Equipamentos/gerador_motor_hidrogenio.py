"""Modelo reduzido de motor-gerador reciprocante alimentado por hidrogenio.

Este equivalente e independente do modelo PEMFC. Usa potencia eletrica como
estado, uma resposta de primeira ordem limitada por rampa e um balanço de H2
por PCI e eficiencia eletrica liquida. Nao representa combustao ou dinamica do
eixo do motor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PCI_H2_J_KG = 120.0e6


@dataclass(frozen=True)
class ParametrosMotorHidrogenio:
    """Parametros identificados ou fornecidos pelo fabricante.

    Args:
        potencia_nominal_kw: potencia eletrica nominal liquida.
        eficiencia_eletrica_liquida: eficiencia sobre PCI do hidrogenio.
        constante_tempo_s: constante de tempo do controle de potencia.
        rampa_max_kw_min: modulo da rampa maxima de potencia eletrica.
        fracao_carga_minima: carga minima relativa a potencia nominal; zero
            permite desligamento sem modelar partida/parada.
        pci_h2_j_kg: PCI do H2. O valor default e constante fisica de referencia.
    """

    potencia_nominal_kw: float
    eficiencia_eletrica_liquida: float
    constante_tempo_s: float | None = None
    rampa_max_kw_min: float | None = None
    fracao_carga_minima: float = 0.0
    pci_h2_j_kg: float = PCI_H2_J_KG

    def __post_init__(self) -> None:
        valores = (
            self.potencia_nominal_kw,
            self.eficiencia_eletrica_liquida,
            self.constante_tempo_s,
            self.rampa_max_kw_min,
            self.fracao_carga_minima,
            self.pci_h2_j_kg,
        )
        if not all(v is None or math.isfinite(v) for v in valores):
            raise ValueError("Todos os parametros do motor devem ser finitos.")
        if self.potencia_nominal_kw <= 0:
            raise ValueError("potencia_nominal_kw deve ser positiva.")
        if not 0 < self.eficiencia_eletrica_liquida <= 1:
            raise ValueError("eficiencia_eletrica_liquida deve estar em (0, 1].")
        if (self.constante_tempo_s is None) != (self.rampa_max_kw_min is None):
            raise ValueError("Informe constante_tempo_s e rampa_max_kw_min juntos.")
        if self.constante_tempo_s is not None and self.constante_tempo_s <= 0:
            raise ValueError("constante_tempo_s deve ser positiva.")
        if self.rampa_max_kw_min is not None and self.rampa_max_kw_min <= 0:
            raise ValueError("rampa_max_kw_min deve ser positiva.")
        if not 0 <= self.fracao_carga_minima < 1:
            raise ValueError("fracao_carga_minima deve estar em [0, 1).")
        if self.pci_h2_j_kg <= 0:
            raise ValueError("pci_h2_j_kg deve ser positivo.")


@dataclass(frozen=True)
class SaidaMotorHidrogenio:
    potencia_eletrica_kw: float
    consumo_h2_kg_s: float
    consumo_h2_kg_h: float


class GeradorMotorHidrogenio:
    """RHS e ponto de operacao de um gerador reciprocante a H2.

    O estado e ``potencia_eletrica_kw`` e a entrada e ``referencia_kw``.
    Positivo representa injecao de potencia na rede e consumo de H2.
    """

    def __init__(self, parametros: ParametrosMotorHidrogenio) -> None:
        self.parametros = parametros

    def _validar_referencia(self, referencia_kw: float) -> float:
        if not math.isfinite(referencia_kw):
            raise ValueError("referencia_kw deve ser finita.")
        p = self.parametros
        if referencia_kw < 0 or referencia_kw > p.potencia_nominal_kw:
            raise ValueError("referencia_kw deve estar entre zero e a potencia nominal.")
        if 0 < referencia_kw < p.fracao_carga_minima * p.potencia_nominal_kw:
            raise ValueError("A referencia esta abaixo da carga minima do motor.")
        return referencia_kw

    def saidas(self, potencia_eletrica_kw: float) -> SaidaMotorHidrogenio:
        """Calcula potencia injetada e consumo de H2 para o estado atual."""
        p = self.parametros
        if not math.isfinite(potencia_eletrica_kw):
            raise ValueError("potencia_eletrica_kw deve ser finita.")
        if not 0 <= potencia_eletrica_kw <= p.potencia_nominal_kw:
            raise ValueError("O estado de potencia deve estar entre zero e o nominal.")
        consumo_kg_s = (
            potencia_eletrica_kw * 1000.0
            / (p.eficiencia_eletrica_liquida * p.pci_h2_j_kg)
        )
        return SaidaMotorHidrogenio(
            potencia_eletrica_kw=potencia_eletrica_kw,
            consumo_h2_kg_s=consumo_kg_s,
            consumo_h2_kg_h=consumo_kg_s * 3600.0,
        )

    def derivada(self, potencia_eletrica_kw: float, referencia_kw: float) -> float:
        """Retorna dP/dt em kW/s para integrar junto ao balanco do tanque."""
        referencia = self._validar_referencia(referencia_kw)
        p = self.parametros
        if p.constante_tempo_s is None or p.rampa_max_kw_min is None:
            raise ValueError(
                "A dinâmica exige constante_tempo_s e rampa_max_kw_min identificados."
            )
        if not math.isfinite(potencia_eletrica_kw):
            raise ValueError("potencia_eletrica_kw deve ser finita.")
        if not 0 <= potencia_eletrica_kw <= p.potencia_nominal_kw:
            raise ValueError("O estado de potencia deve estar entre zero e o nominal.")

        rampa_limite_kw_s = p.rampa_max_kw_min / 60.0
        derivada_kw_s = (referencia - potencia_eletrica_kw) / p.constante_tempo_s
        derivada_kw_s = max(-rampa_limite_kw_s, min(rampa_limite_kw_s, derivada_kw_s))

        if potencia_eletrica_kw == 0 and derivada_kw_s < 0:
            return 0.0
        if potencia_eletrica_kw == p.potencia_nominal_kw and derivada_kw_s > 0:
            return 0.0
        return derivada_kw_s

    def ponto_permanente(self, referencia_kw: float) -> SaidaMotorHidrogenio:
        """Avalia o equilibrio (dP/dt = 0) para a referencia informada."""
        referencia = self._validar_referencia(referencia_kw)
        return self.saidas(referencia)

    def passo(self, potencia_eletrica_kw: float, referencia_kw: float, passo_s: float) -> float:
        """Avanca o estado de potencia por Euler explicito e aplica limites."""
        if not math.isfinite(passo_s) or passo_s <= 0:
            raise ValueError("passo_s deve ser positivo e finito.")
        proxima = potencia_eletrica_kw + passo_s * self.derivada(
            potencia_eletrica_kw, referencia_kw
        )
        return min(max(proxima, 0.0), self.parametros.potencia_nominal_kw)
