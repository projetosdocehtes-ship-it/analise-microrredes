"""Análises econômicas fundamentais da energia consumida."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..dados.tarifas_aneel import TarifaSnapshot


@dataclass(frozen=True)
class PerfilConsumo:
    energia_ponta_kwh: float
    energia_fora_ponta_kwh: float
    demanda_ponta_kw: float
    demanda_fora_ponta_kw: float

    def __post_init__(self) -> None:
        if any(valor < 0 for valor in self.__dict__.values()):
            raise ValueError("As grandezas de consumo não podem ser negativas")


@dataclass(frozen=True)
class ImpostoICMS:
    aliquota: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.aliquota < 1:
            raise ValueError("A alíquota de ICMS deve estar entre 0 e 1")

    def aplicar_gross_up(self, valor_sem_icms: float) -> float:
        if valor_sem_icms < 0:
            raise ValueError("O valor tributável não pode ser negativo")
        return valor_sem_icms / (1.0 - self.aliquota)

    def valor(self, valor_sem_icms: float) -> float:
        return self.aplicar_gross_up(valor_sem_icms) - valor_sem_icms


class AnaliseFundamental:
    """Compara modalidades tarifárias usando um snapshot ANEEL e ICMS configurado."""

    def __init__(self, tarifas: TarifaSnapshot, icms: float = 0.0) -> None:
        self.tarifas = tarifas
        self.icms = ImpostoICMS(icms)

    def custo_azul(self, perfil: PerfilConsumo) -> dict[str, float]:
        tarifa = self.tarifas.azul
        consumo_sem_icms = (
            perfil.energia_ponta_kwh * (tarifa.get("tusd_ponta_consumo", 0.0) + tarifa.get("te_ponta", 0.0))
            + perfil.energia_fora_ponta_kwh * (tarifa.get("tusd_fora_ponta_consumo", 0.0) + tarifa.get("te_fora_ponta", 0.0))
        )
        demanda = (
            perfil.demanda_ponta_kw * tarifa.get("tusd_ponta_demanda", 0.0)
            + perfil.demanda_fora_ponta_kw * tarifa.get("tusd_fora_ponta_demanda", 0.0)
        )
        return self._resultado(consumo_sem_icms, demanda)

    def custo_verde(self, perfil: PerfilConsumo) -> dict[str, float]:
        tarifa = self.tarifas.verde
        consumo_sem_icms = (
            perfil.energia_ponta_kwh * (tarifa.get("tusd_ponta_consumo", 0.0) + tarifa.get("te_ponta", 0.0))
            + perfil.energia_fora_ponta_kwh * (tarifa.get("tusd_fora_ponta_consumo", 0.0) + tarifa.get("te_fora_ponta", 0.0))
        )
        demanda = max(perfil.demanda_ponta_kw, perfil.demanda_fora_ponta_kw) * tarifa.get("tusd_demanda", 0.0)
        return self._resultado(consumo_sem_icms, demanda)

    def comparar_modalidades(self, perfil: PerfilConsumo) -> dict[str, Any]:
        azul = self.custo_azul(perfil)
        verde = self.custo_verde(perfil)
        melhor = "azul" if azul["custo_total"] <= verde["custo_total"] else "verde"
        return {
            "analise": "fundamental_tarifaria",
            "fonte_tarifas": self.tarifas.to_dict(),
            "icms_aliquota": self.icms.aliquota,
            "modalidades": {"azul": azul, "verde": verde},
            "melhor_modalidade": melhor,
            "economia_da_melhor_modalidade": abs(azul["custo_total"] - verde["custo_total"]),
        }

    def _resultado(self, consumo_sem_icms: float, demanda: float) -> dict[str, float]:
        consumo_com_icms = self.icms.aplicar_gross_up(consumo_sem_icms)
        return {
            "consumo_sem_icms": consumo_sem_icms,
            "icms_sobre_consumo": self.icms.valor(consumo_sem_icms),
            "consumo_com_icms": consumo_com_icms,
            "demanda": demanda,
            "custo_total": consumo_com_icms + demanda,
        }


__all__ = ["AnaliseFundamental", "ImpostoICMS", "PerfilConsumo"]
