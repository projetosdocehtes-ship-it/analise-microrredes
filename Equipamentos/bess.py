"""Componente independente de BESS com estado de carga e limites de potência."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ParametrosBESS:
    """Parâmetros mínimos para a simulação eletroquímica reduzida."""

    id_bess: str = "BESS_1"
    capacidade_kwh: float = 100.0
    potencia_max_carga_kw: float = 40.0
    potencia_max_descarga_kw: float = 40.0
    soc_inicial: float = 0.80
    soc_minimo: float = 0.10
    soc_maximo: float = 0.90
    eficiencia_carga: float = 0.95
    eficiencia_descarga: float = 0.95
    tensao_nominal_v: float = 480.0
    resistencia_interna_ohm: float = 0.02

    def __post_init__(self) -> None:
        if self.capacidade_kwh <= 0:
            raise ValueError("capacidade_kwh deve ser positiva")
        if self.potencia_max_carga_kw < 0 or self.potencia_max_descarga_kw < 0:
            raise ValueError("limites de potência não podem ser negativos")
        if not 0 <= self.soc_minimo <= self.soc_inicial <= self.soc_maximo <= 1:
            raise ValueError("SOC deve atender minimo <= inicial <= maximo entre 0 e 1")
        if not 0 < self.eficiencia_carga <= 1 or not 0 < self.eficiencia_descarga <= 1:
            raise ValueError("eficiências devem estar entre zero e um")
        if self.tensao_nominal_v <= 0 or self.resistencia_interna_ohm < 0:
            raise ValueError("tensão deve ser positiva e resistência não negativa")


@dataclass
class EstadoBESS:
    """Variáveis de estado e grandezas calculadas do BESS."""

    soc: float
    potencia_kw: float = 0.0
    tensao_v: float = 0.0
    corrente_a: float = 0.0


class BESS:
    """Modelo reduzido com convenção positiva para descarga."""

    def __init__(self, parametros: ParametrosBESS | None = None):
        self.parametros = parametros or ParametrosBESS()
        self.estado = EstadoBESS(soc=self.parametros.soc_inicial)
        self.historico: list[EstadoBESS] = []

    def equacao_diferencial_soc(self, potencia_kw: float) -> float:
        """Retorna ``dSOC/dt`` em 1/s; descarga positiva reduz o SOC."""

        p = float(potencia_kw)
        if p >= 0:
            return -p / (self.parametros.eficiencia_descarga * self.parametros.capacidade_kwh * 3600.0)
        return -p * self.parametros.eficiencia_carga / (self.parametros.capacidade_kwh * 3600.0)

    def tensao_circuito_aberto_v(self, soc: float | None = None) -> float:
        soc_atual = self.estado.soc if soc is None else soc
        return self.parametros.tensao_nominal_v * (0.90 + 0.10 * soc_atual)

    def limitar_potencia(self, potencia_kw: float, passo_s: float) -> float:
        if passo_s <= 0:
            raise ValueError("passo_s deve ser positivo")
        p = _limitar(
            potencia_kw,
            -self.parametros.potencia_max_carga_kw,
            self.parametros.potencia_max_descarga_kw,
        )
        passo_h = passo_s / 3600.0
        if p > 0:
            energia_disponivel = (
                (self.estado.soc - self.parametros.soc_minimo)
                * self.parametros.capacidade_kwh
                * self.parametros.eficiencia_descarga
                / max(passo_h, 1e-12)
            )
            return min(p, max(energia_disponivel, 0.0))
        energia_armazenavel = (
            (self.parametros.soc_maximo - self.estado.soc)
            * self.parametros.capacidade_kwh
            / (self.parametros.eficiencia_carga * max(passo_h, 1e-12))
        )
        return max(p, -max(energia_armazenavel, 0.0))

    def passo_potencia(self, passo_s: float, potencia_kw: float) -> EstadoBESS:
        """Integra o SOC por Euler explícito e atualiza tensão/corrente."""

        potencia_limitada = self.limitar_potencia(potencia_kw, passo_s)
        self.estado.potencia_kw = potencia_limitada
        self.estado.soc = _limitar(
            self.estado.soc + passo_s * self.equacao_diferencial_soc(potencia_limitada),
            self.parametros.soc_minimo,
            self.parametros.soc_maximo,
        )
        self.estado.tensao_v = self.tensao_circuito_aberto_v() - (
            potencia_limitada * 1000.0 / max(self.tensao_circuito_aberto_v() or 1.0, 1e-9)
        ) * self.parametros.resistencia_interna_ohm
        self.estado.tensao_v = max(self.estado.tensao_v, 0.0)
        self.estado.corrente_a = (
            potencia_limitada * 1000.0 / self.estado.tensao_v if self.estado.tensao_v > 0 else 0.0
        )
        self.historico.append(EstadoBESS(**asdict(self.estado)))
        return self.estado

    def passo_acao(self, passo_s: float, acao: str, potencia_requerida_kw: float = 0.0) -> EstadoBESS:
        """Adapta as ações legadas ``carregar``/``descarregar``/``espera``."""

        if acao == "carregar":
            potencia = -abs(potencia_requerida_kw)
        elif acao == "descarregar":
            potencia = abs(potencia_requerida_kw)
        elif acao in {"espera", "standby", "parado"}:
            potencia = 0.0
        else:
            raise ValueError(f"Ação de BESS inválida: {acao}")
        return self.passo_potencia(passo_s, potencia)

    def exportar_estado(self) -> dict[str, Any]:
        return {
            "parametros": asdict(self.parametros),
            "estado": asdict(self.estado),
            "historico": [asdict(item) for item in self.historico],
        }


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return min(max(float(valor), float(minimo)), float(maximo))


__all__ = ["BESS", "EstadoBESS", "ParametrosBESS"]
